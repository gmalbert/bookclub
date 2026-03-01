/**
 * Cloudflare HTTP Worker — bookclub-book-processor
 *
 * Accepts a POST from the email-worker with:
 *   { amazonUrl: string, senderEmail: string, subject: string }
 *
 * Steps:
 *  1. Verify shared secret
 *  2. Resolve any short-link (amzn.to / a.co) to a full amazon.com URL
 *  3. Extract the ASIN (= ISBN-10 for most books)
 *  4. Search Hardcover API for the book
 *  5. Fetch current book_selections.csv from GitHub
 *  6. Deduplicate and append the new row
 *  7. Commit the updated CSV back to GitHub
 */

const HARDCOVER_API = "https://api.hardcover.app/v1/graphql";
const GH_API_BASE = "https://api.github.com";
const CSV_PATH = "data_files/book_selections.csv";
const QUEUE_PATH = "data_files/pending_queue.csv";

const SEARCH_QUERY = `
query SearchBooks($query: String!, $perPage: Int!) {
  search(query: $query, query_type: "Book", per_page: $perPage, page: 1) {
    results
  }
}`;

// ── Entry point ──────────────────────────────────────────────────────────────

export default {
  async fetch(request, env, _ctx) {
    // Only accept POST
    if (request.method !== "POST") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    // Verify shared secret
    const secret = request.headers.get("X-Worker-Secret");
    if (!env.WORKER_SECRET || secret !== env.WORKER_SECRET) {
      return new Response("Unauthorized", { status: 401 });
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return new Response("Bad JSON", { status: 400 });
    }

    const { amazonUrl, senderEmail } = body;
    if (!amazonUrl) {
      return new Response("Missing amazonUrl", { status: 400 });
    }

    try {
      // 1. Resolve short links → full URL
      const fullUrl = await resolveUrl(amazonUrl);
      console.log(`[book-processor] original URL: ${amazonUrl}`);
      console.log(`[book-processor] resolved URL: ${fullUrl}`);

      // 2. Extract ASIN
      const asin = extractAsin(fullUrl);
      if (!asin) {
        console.log(`[book-processor] could not extract ASIN, queuing for review`);
        await appendToGithubQueue({
          sender_email: senderEmail,
          original_url: amazonUrl,
          resolved_url: fullUrl,
          asin: "",
          scraped_title: "",
          scraped_author: "",
        }, env);
        return new Response(
          JSON.stringify({ queued: true, message: "Could not extract ASIN — added to review queue" }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      console.log(`[book-processor] extracted ASIN: ${asin}`);

      // 3. Search Hardcover (ASIN == ISBN-10 for books)
      const bookData = await searchHardcover(asin, env.HARDCOVER_API_TOKEN);
      if (!bookData) {
        // Scrape title/author for the queue so reviewer has context
        const { title, author } = await scrapeAmazonTitleAuthor(asin);
        console.log(`[book-processor] no Hardcover result, queuing: "${title}" by "${author}"`);
        await appendToGithubQueue({
          sender_email: senderEmail,
          original_url: amazonUrl,
          resolved_url: fullUrl,
          asin,
          scraped_title: title,
          scraped_author: author,
        }, env);
        return new Response(
          JSON.stringify({ queued: true, message: `No Hardcover result for "${title || asin}" — added to review queue` }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }

      // 4. Add to GitHub CSV
      const { added, message } = await appendToGithubCsv(bookData, env);
      console.log(`[book-processor] ${message} (submitted by ${senderEmail})`);

      return new Response(JSON.stringify({ added, message }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    } catch (err) {
      console.error("[book-processor] error:", err);
      return new Response(`Internal error: ${err.message}`, { status: 500 });
    }
  },
};

// ── Helpers ──────────────────────────────────────────────────────────────────

/**
 * Follow up to 10 redirects to resolve a short-link into its final URL.
 * Uses GET with a browser-like User-Agent since Amazon often ignores HEAD.
 */
async function resolveUrl(url) {
  let current = url;
  for (let i = 0; i < 10; i++) {
    const resp = await fetch(current, {
      method: "GET",
      redirect: "manual",
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          + "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
      },
    });
    const location = resp.headers.get("location");
    if (!location) break;
    // Make relative redirects absolute
    current = location.startsWith("http") ? location : new URL(location, current).href;
    // Stop once we land on a full amazon.com product URL with an ASIN candidate
    if (current.includes("amazon.com") && (/\/dp\/|\/(gp\/)|B[A-Z0-9]{9}/.test(current))) break;
  }
  return current;
}

/**
 * Extract a 10-character Amazon ASIN from a full amazon.com URL.
 * Handles /dp/ASIN, /gp/product/ASIN, and bare /ASIN patterns.
 */
function extractAsin(url) {
  const patterns = [
    /\/dp\/([A-Z0-9]{10})/i,               // /dp/ASIN  (most common)
    /\/gp\/product\/([A-Z0-9]{10})/i,      // /gp/product/ASIN
    /\/gp\/aw\/d\/([A-Z0-9]{10})/i,        // mobile /gp/aw/d/ASIN
    /\/product\/([A-Z0-9]{10})/i,          // /product/ASIN
    /\/exec\/obidos\/(?:ASIN\/)?([A-Z0-9]{10})/i, // old-style obidos links
    /[?&]asin=([A-Z0-9]{10})/i,            // ?asin= query param
    /[?&]keywords=([A-Z0-9]{10})(?:&|$)/i, // ?keywords=ASIN
    /\/(B[A-Z0-9]{9})(?:[\/?#]|$)/,        // bare B-ASIN in path (B always starts ASINs)
  ];
  for (const re of patterns) {
    const m = url.match(re);
    if (m) return m[1].toUpperCase();
  }
  return null;
}

/**
 * Search Hardcover for a book using the ASIN as an ISBN query.
 * If the ASIN is a Kindle/B-ASIN (not an ISBN), falls back to scraping the
 * Amazon page for the title and searching Hardcover by title instead.
 * Returns a normalised book object or null.
 */
async function searchHardcover(asin, token) {
  // Try direct ISBN/ASIN search first (works for print editions)
  let hit = await runHardcoverSearch(asin, token, 5);
  if (hit) return normaliseHit(hit);

  // B-ASINs are Kindle/digital — try scraping the Amazon page for title+author
  if (asin.startsWith("B")) {
    console.log(`[book-processor] B-ASIN detected, fetching Amazon page for title...`);
    const { title, author } = await scrapeAmazonTitleAuthor(asin);
    if (title) {
      console.log(`[book-processor] scraped title: "${title}", author: "${author}"`);
      const query = author ? `${title} ${author}` : title;
      hit = await runHardcoverSearch(query, token, 5);
      if (hit) return normaliseHit(hit);
    }
  }

  return null;
}

/**
 * Fetch an Amazon product page and extract the book title and author
 * from the page's <title> tag or OG meta tags.
 * Returns { title, author } — either may be an empty string if not found.
 */
async function scrapeAmazonTitleAuthor(asin) {
  try {
    const url = `https://www.amazon.com/dp/${asin}`;
    const resp = await fetch(url, {
      headers: {
        "User-Agent":
          "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          + "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
      },
    });
    if (!resp.ok) return { title: "", author: "" };
    const html = await resp.text();

    // Try og:title first (usually "Book Title: Subtitle")
    let title = "";
    const ogTitle = html.match(/<meta[^>]+property=["']og:title["'][^>]+content=["']([^"']+)["']/i);
    if (ogTitle) {
      title = ogTitle[1].trim();
    } else {
      // Fall back to <title> tag — Amazon format: "Amazon.com: Book Title: ..."
      const titleTag = html.match(/<title>([^<]+)<\/title>/i);
      if (titleTag) {
        title = titleTag[1]
          .replace(/^Amazon\.com\s*:\s*/i, "")
          .replace(/\s*:\s*Amazon\.com.*$/i, "")
          .replace(/\s*\(.*\)\s*$/, "") // strip "(Kindle Edition)" etc.
          .trim();
      }
    }

    // Try to extract author from the byline span
    let author = "";
    const byline = html.match(/class="[^"]*byline[^"]*"[^>]*>[\s\S]*?<span[^>]*>([^<]{3,60})<\/span>/i);
    if (byline) author = byline[1].replace(/^by\s+/i, "").trim();

    return { title, author };
  } catch (e) {
    console.log(`[book-processor] Amazon scrape failed: ${e.message}`);
    return { title: "", author: "" };
  }
}

async function runHardcoverSearch(query, token, perPage) {
  const resp = await fetch(HARDCOVER_API, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: token,
    },
    body: JSON.stringify({
      query: SEARCH_QUERY,
      variables: { query, perPage },
    }),
  });

  if (!resp.ok) return null;
  const json = await resp.json();
  const hits = json?.data?.search?.results?.hits ?? [];
  return hits.length > 0 ? hits[0] : null;
}

/**
 * Convert a Hardcover search hit into the flat object shape
 * expected by the book_selections.csv schema.
 */
function normaliseHit(hit) {
  const doc = hit.document ?? hit;
  const authorNames = Array.isArray(doc.author_names)
    ? doc.author_names.join(", ")
    : doc.author_names ?? "";
  const genres = Array.isArray(doc.genres)
    ? doc.genres.join(", ")
    : doc.genres ?? "";

  return {
    id: String(doc.id ?? ""),
    title: doc.title ?? "",
    author_names: authorNames,
    release_year: doc.release_year ?? "",
    pages: doc.pages ?? "",
    rating: doc.rating ?? "",
    ratings_count: doc.ratings_count ?? "",
    genres,
    description: doc.description ?? "",
    image_url: doc.image?.url ?? "",
    added_date: new Date().toISOString().replace("T", " ").slice(0, 19),
  };
}

// ── GitHub CSV helpers ───────────────────────────────────────────────────────

/**
 * Fetch the current CSV from GitHub, append the new book row, and commit.
 * Returns { added: boolean, message: string }.
 */
async function appendToGithubCsv(bookData, env) {
  const apiUrl = `${GH_API_BASE}/repos/${env.GITHUB_REPO}/contents/${CSV_PATH}`;
  const headers = buildGhHeaders(env.GITHUB_TOKEN);

  // Fetch existing file
  const getResp = await fetch(apiUrl, { headers });
  if (!getResp.ok) throw new Error(`GitHub GET failed: ${getResp.status}`);
  const fileJson = await getResp.json();
  const currentSha = fileJson.sha;
  const csvText = atob(fileJson.content.replace(/\n/g, ""));

  // Check duplicate
  const lines = csvText.split("\n");
  const existing = lines.slice(1).some((line) => {
    const firstCell = line.split(",")[0].replace(/^"|"$/g, "");
    return firstCell === bookData.id;
  });
  if (existing) {
    return { added: false, message: `"${bookData.title}" is already in the list` };
  }

  // Append new row
  const newRow = toCsvRow([
    bookData.id,
    bookData.title,
    bookData.author_names,
    bookData.release_year,
    bookData.pages,
    bookData.rating,
    bookData.ratings_count,
    bookData.genres,
    bookData.description,
    bookData.image_url,
    bookData.added_date,
  ]);

  // Make sure the file ends with a newline before appending
  const updatedCsv = csvText.trimEnd() + "\n" + newRow + "\n";

  // Commit
  const commitResp = await fetch(apiUrl, {
    method: "PUT",
    headers: { ...headers, "Content-Type": "application/json" },
    body: JSON.stringify({
      message: `feat: add "${bookData.title}" via email submission`,
      content: btoa(unescape(encodeURIComponent(updatedCsv))),
      sha: currentSha,
    }),
  });

  if (!commitResp.ok) {
    const errBody = await commitResp.text();
    throw new Error(`GitHub PUT failed (${commitResp.status}): ${errBody}`);
  }

  return { added: true, message: `"${bookData.title}" added to book list` };
}

function buildGhHeaders(token) {
  return {
    Authorization: `token ${token}`,
    Accept: "application/vnd.github.v3+json",
    "User-Agent": "bookclub-worker",
  };
}

/**
 * Append a failed submission to pending_queue.csv in GitHub for manual review.
 */
async function appendToGithubQueue(entry, env) {
  try {
    const apiUrl = `${GH_API_BASE}/repos/${env.GITHUB_REPO}/contents/${QUEUE_PATH}`;
    const headers = buildGhHeaders(env.GITHUB_TOKEN);

    const getResp = await fetch(apiUrl, { headers });
    if (!getResp.ok) return; // fail silently — don't block the response
    const fileJson = await getResp.json();
    const currentSha = fileJson.sha;
    const csvText = atob(fileJson.content.replace(/\n/g, ""));

    const newRow = toCsvRow([
      new Date().toISOString().replace("T", " ").slice(0, 19),
      entry.sender_email ?? "",
      entry.original_url ?? "",
      entry.resolved_url ?? "",
      entry.asin ?? "",
      entry.scraped_title ?? "",
      entry.scraped_author ?? "",
      "pending",
    ]);

    const updatedCsv = csvText.trimEnd() + "\n" + newRow + "\n";

    await fetch(apiUrl, {
      method: "PUT",
      headers: { ...headers, "Content-Type": "application/json" },
      body: JSON.stringify({
        message: `chore: queue "${entry.scraped_title || entry.asin || entry.original_url}" for review`,
        content: btoa(unescape(encodeURIComponent(updatedCsv))),
        sha: currentSha,
      }),
    });
  } catch (e) {
    console.log(`[book-processor] queue write failed: ${e.message}`);
  }
}

/**
 * Convert an array of string values into a single RFC-4180 CSV row.
 * Fields containing commas, quotes, or newlines are double-quoted;
 * internal double-quotes are escaped as "".
 */
function toCsvRow(fields) {
  return fields
    .map((v) => {
      const s = v == null ? "" : String(v);
      if (s.includes(",") || s.includes('"') || s.includes("\n") || s.includes("\r")) {
        return '"' + s.replace(/"/g, '""') + '"';
      }
      return s;
    })
    .join(",");
}
