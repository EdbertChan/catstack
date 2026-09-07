export function loadQuotes(url) {
  return fetch(url)
    .then((r) => r.json())
    .catch((err) => {
      console.warn("loadQuotes failed", url, err);
      return { status: "unavailable", reason: String(err) };
    });
}
