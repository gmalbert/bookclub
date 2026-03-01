/**
 * Cloudflare Email Worker — bookclub-email-worker
 *
 * Triggered by Cloudflare Email Routing whenever an email arrives at the
 * configured address (e.g. books@yourdomain.com).
 *
 * It scans the raw email for an Amazon product URL and forwards it to the
 * book-processor HTTP Worker for Hardcover lookup + GitHub commit.
 */

// Matches amazon.com product URLs and common short-link forms
const AMAZON_URL_RE =
  /https?:\/\/(?:www\.amazon\.com\/[^\s"'<>\])}]+|amzn\.to\/[^\s"'<>\])}]+|a\.co\/[^\s"'<>\])}]+)/gi;

export default {
  async email(message, env, _ctx) {
    // Read the full raw RFC-2822 email as text
    const raw = await new Response(message.raw).text();

    const matches = raw.match(AMAZON_URL_RE);
    if (!matches || matches.length === 0) {
      // No Amazon URL found — silently drop
      return;
    }

    // Strip trailing punctuation AND quoted-printable artifacts (=, =3D, etc.)
    const amazonUrl = matches[0]
      .replace(/=([0-9A-Fa-f]{2})/g, (_, h) => String.fromCharCode(parseInt(h, 16))) // decode =XX
      .replace(/=+$/, "")          // strip trailing bare = (soft line-break)
      .replace(/[)>\].,;'"]+$/, ""); // strip trailing punctuation

    const payload = {
      amazonUrl,
      senderEmail: message.from,
      subject: message.headers.get("subject") ?? "",
    };

    const resp = await fetch(env.BOOK_PROCESSOR_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Worker-Secret": env.WORKER_SECRET,
      },
      body: JSON.stringify(payload),
    });

    if (!resp.ok) {
      const body = await resp.text();
      console.error(`book-processor returned ${resp.status}: ${body}`);
    }
  },
};
