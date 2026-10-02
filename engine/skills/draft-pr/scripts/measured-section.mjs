const HEADING = 'Measured';
const ROW_LABELS = ['base', 'head'];

const FENCE_LINE = /^ {0,3}(`{3,}|~{3,})/;
const SECTION_HEADING_LINE = /^## (.*?)[ \t]*$/;
const DETAILS_OPEN_TAG = /<details\b/gi;
const DETAILS_CLOSE_TAG = /<\/details\s*>/gi;
const ROW_LINE = /^\s*(?:[-*+]\s+)?\**(base|head)\b[^:\n]*:(.*)$/i;
const NONE_LINE = /^\s*(?:[-*+]\s+)?none:(.*)$/i;
const INLINE_CODE = /`([^`\n]+)`/g;

export const MEASURED_TEMPLATE = [
  `## ${HEADING}`,
  '',
  'Command: `exact repro command`',
  '',
  '- base:',
  '- head:',
  '',
  'Paste the command\'s real output on each row, inline in backticks or in a code block under the row.',
  'When this slice has nothing to measure, replace the rows with the single line `none: <reason>`.',
  '',
].join('\n');

export function scanLines(body) {
  const lines = [];
  let fence = null;
  let depth = 0;
  for (const text of (body || '').split(/\r?\n/)) {
    const marker = FENCE_LINE.exec(text);
    if (fence) {
      const closes = marker && marker[1][0] === fence[0] && marker[1].length >= fence.length && text.trim() === marker[1];
      if (closes) fence = null;
      lines.push({ text, kind: closes ? 'fence' : 'code', collapsed: depth > 0 });
      continue;
    }
    if (marker) {
      fence = marker[1];
      lines.push({ text, kind: 'fence', collapsed: depth > 0 });
      continue;
    }
    const before = depth;
    const opens = (text.match(DETAILS_OPEN_TAG) || []).length;
    const closes = (text.match(DETAILS_CLOSE_TAG) || []).length;
    depth = Math.max(0, depth + opens - closes);
    lines.push({ text, kind: 'text', collapsed: before > 0 || depth > 0 });
  }
  return lines;
}

export function headingName(line) {
  if (line.kind !== 'text') return null;
  const match = SECTION_HEADING_LINE.exec(line.text);
  return match ? match[1] : null;
}

export function sectionLines(lines, start) {
  const section = [];
  for (let i = start + 1; i < lines.length; i++) {
    if (headingName(lines[i]) !== null) break;
    section.push(lines[i]);
  }
  return section;
}

function hasInlineOutput(text) {
  return [...text.matchAll(INLINE_CODE)].some((match) => match[1].trim() !== '');
}

function readSection(section) {
  const filled = new Set();
  let current = null;
  let noneSeen = false;
  let noneReason = '';
  for (const line of section) {
    if (line.collapsed) continue;
    if (line.kind === 'code') {
      if (current && line.text.trim() !== '') filled.add(current);
      continue;
    }
    if (line.kind !== 'text') continue;
    const row = ROW_LINE.exec(line.text);
    if (row) {
      current = row[1].toLowerCase();
      if (hasInlineOutput(row[2])) filled.add(current);
      continue;
    }
    const none = NONE_LINE.exec(line.text);
    if (none) {
      noneSeen = true;
      const reason = none[1].trim();
      if (/[A-Za-z0-9]/.test(reason)) noneReason = reason;
    }
  }
  return { filled, noneSeen, noneReason };
}

export function checkMeasured(body) {
  const lines = scanLines(body);
  const headings = [];
  lines.forEach((line, index) => {
    if (headingName(line) === HEADING) headings.push({ index, collapsed: line.collapsed });
  });
  if (headings.length === 0) return { status: 'hard', kind: 'missing' };
  const visible = headings.find((heading) => !heading.collapsed);
  if (!visible) return { status: 'hard', kind: 'collapsed' };

  const { filled, noneSeen, noneReason } = readSection(sectionLines(lines, visible.index));
  const missing = ROW_LABELS.filter((label) => !filled.has(label));
  if (missing.length === 0) return { status: 'clean', form: 'rows' };
  if (noneSeen && filled.size === 0) {
    if (noneReason) return { status: 'clean', form: 'none', reason: noneReason };
    return { status: 'hard', kind: 'none-without-reason' };
  }
  return { status: 'hard', kind: 'rows', missing };
}

const HOW =
  'Give a `base:` row and a `head:` row, each with the repro command\'s real pasted output ' +
  '(inline in backticks, or in a code block under the row), or the single line `none: <reason>` ' +
  'when this slice has nothing to measure.';

export function measuredError(result) {
  switch (result.kind) {
    case 'missing':
      return `Missing required section: ## ${HEADING}. ${HOW}`;
    case 'collapsed':
      return `## ${HEADING} must be visible: it only appears inside <details>. Move the heading and its rows out of the collapsed block. ${HOW}`;
    case 'none-without-reason':
      return `## ${HEADING} says \`none:\` with no reason. Write \`none: <reason>\`, or give base and head rows with pasted output.`;
    default:
      return `## ${HEADING} needs pasted output on a visible base row and a visible head row; missing: ${result.missing.join(', ')}. ${HOW}`;
  }
}

export function measuredNote(result) {
  if (result.status === 'clean' && result.form === 'none') {
    return `Measured \`none:\` reason "${result.reason}" is not checked: nothing here judges whether this slice truly has nothing to measure.`;
  }
  return null;
}
