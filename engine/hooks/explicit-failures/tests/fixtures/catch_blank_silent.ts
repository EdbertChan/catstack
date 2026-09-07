export function parseConfig(raw: string): { status: string; value?: unknown; reason?: string } {
  try {
    return { status: "ok", value: JSON.parse(raw) };
  } catch (e) {
    console.error("parseConfig: invalid JSON", raw.slice(0, 80), e);
    return { status: "unparsed", reason: String(e) };
  }
}

export function parseAll(inputs: string[]): unknown[] {
  const out: unknown[] = [];
  for (const raw of inputs) {
    try {
      out.push(JSON.parse(raw));
    } catch (e) {
      throw new Error(`parseAll: input ${out.length} is not JSON: ${String(e)}`);
    }
  }
  return out;
}
