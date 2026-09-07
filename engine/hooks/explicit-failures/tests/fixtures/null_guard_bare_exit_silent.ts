type Row = { ticker: string | null; px: number | null; status: string; reason?: string };

export function priceRows(rows: Array<{ ticker?: string }>, quotes: Map<string, number>): Row[] {
  const out: Row[] = [];
  for (const row of rows) {
    if (!row.ticker) {
      out.push({ ticker: null, px: null, status: "unparsed", reason: "row has no ticker" });
      continue;
    }
    const px = quotes.get(row.ticker);
    if (px == null) {
      out.push({ ticker: row.ticker, px: null, status: "unpriced", reason: "no quote" });
      continue;
    }
    out.push({ ticker: row.ticker, px, status: "ok" });
  }
  if (out.length === 0) throw new Error("priceRows: no rows produced from a non-empty source");
  return out;
}
