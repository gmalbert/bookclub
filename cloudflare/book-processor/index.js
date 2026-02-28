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

      // 2. Extract ASIN
      const asin = extractAsin(fullUrl);
      if (!asin) {
        return new Response("Could not extract ASIN from URL", { status: 422 });
      }

      // 3. Search Hardcover (ASIN == ISBN-10 for books)
      const bookData = await searchHardcover(asin, env.HARDCOVER_API_TOKEN);
      if (!bookData) {
        return new Response(`No Hardcover result for ASIN ${asin}`, { status: 404 });
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
 * Follow up to 5 redirects to resolve a short-link into its final URL.
 */
async function resolveUrl(url) {
  let current = url;
  for (let i = 0; i < 5; i++) {
    const resp = await fetch(current, {
      method: "HEAD",
      redirect: "manual",
    });
    const location = resp.headers.get("location");
    if (!location) break;
    current = location;
    // Stop once we land on amazon.com
    if (current.includes("amazon.com")) break;
  }
  return current;
}

/**
 * Extract a 10-character Amazon ASIN from a full amazon.com URL.
 * Handles /dp/ASIN, /gp/product/ASIN, and bare /ASIN patterns.
 */
function extractAsin(url) {
  const patterns = [
    /\/dp\/([A-Z0-9]{10})/i,
    /\/gp\/product\/([A-Z0-9]{10})/i,
    /\/product\/([A-Z0-9]{10})/i,
    /\/([A-Z0-9]{10})(?:[/?]|$)/,
  ];
  for (const re of patterns) {
    const m = url.match(re);
    if (m) return m[1].toUpperCase();
  }
  return null;
}

/**
 * Search Hardcover for a book using the ASIN as an ISBN query.
 * Falls back to a broader search if the ISBN query returns nothing.
 * Returns a normalised book object or null.
 */
async function searchHardcover(asin, token) {
  // Try direct ISBN match first
  let hit = await runHardcoverSearch(asin, token, 5);
  if (!hit) {
    // Nothing found — the ASIN might not be ISBN-10; return null
    return null;
  }
  return normaliseHit(hit);
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
