export function parseConfig(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {}
  return null;
}

export function parseAll(inputs: string[]): unknown[] {
  const out: unknown[] = [];
  for (const raw of inputs) {
    try {
      out.push(JSON.parse(raw));
    } catch (e) {
      continue;
    }
  }
  return out;
}
