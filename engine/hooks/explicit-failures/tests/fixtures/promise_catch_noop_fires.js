export function loadQuotes(url) {
  return fetch(url)
    .then((r) => r.json())
    .catch(() => {});
}

export function loadPrices(url) {
  return fetch(url).then((r) => r.json()).catch(e => null);
}
