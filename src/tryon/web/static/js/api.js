// Talking to the server. Every call either resolves with JSON or throws an Error with a message fit to show.

async function request(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch (err) {
    if (err.name === "AbortError") throw err;
    throw new Error("We can't reach the server. Check that it is still running, then try again.");
  }
  let body = null;
  try { body = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) {
    const detail = body && (typeof body.detail === "string" ? body.detail : "That request was not valid.");
    throw new Error(detail || `The server had a problem (${res.status}). Please try again.`);
  }
  return body;
}

export const api = {
  meta: () => request("/api/meta"),
  catalog: () => request("/api/catalog"),
  analyze(blob, audience, signal) {
    const form = new FormData();
    form.append("photo", blob, "photo.jpg");
    form.append("audience", audience);
    return request("/api/analyze", { method: "POST", body: form, signal });
  },
  recommend(body, signal) {
    return request("/api/recommend", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal });
  },
};
