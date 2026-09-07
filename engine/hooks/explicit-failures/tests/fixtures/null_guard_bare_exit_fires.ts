export function priceRows(rows: Array<{ ticker?: string }>, quotes: Map<string, number>) {
  const out: Array<{ ticker: string; px: number }> = [];
  for (const row of rows) {
    if (!row.ticker) continue;
    const px = quotes.get(row.ticker);
    if (px == null) { continue; }
    out.push({ ticker: row.ticker, px });
  }
  if (out.length === 0) return [];
  return out;
}

export function firstLot(lots: number[]): number | null {
  if (lots === undefined) {
    return null;
  }
  return lots[0];
}
