import { scanLines, headingName, sectionLines } from './measured-section.mjs';

const HEADING = 'Test Plan';
const ROW_PREFIX = String.raw`^\s*(?:[-*+]\s+)?(?:\[[ xX]\]\s+)?[*_]*`;
const NOT_RUN_ROW = new RegExp(`${ROW_PREFIX}Not run:`, 'i');
const BLOCKER_LABEL = /Blocker:(.*)$/i;

export const NOT_RUN_TEMPLATE_LINE =
  'A check that was not run gets its own row, `- Not run: <check>. Blocker: <what stops it>`; delete this line when every check ran.';

function blockerText(text) {
  const rest = (BLOCKER_LABEL.exec(text) || [])[1] || '';
  return /[A-Za-z0-9]/.test(rest) ? rest.replace(/^[\s*_]+/, '').trim() : '';
}

function nextNonEmptyText(section, from) {
  for (let i = from + 1; i < section.length; i++) {
    if (section[i].text.trim() === '') continue;
    return section[i].kind === 'text' ? section[i].text : null;
  }
  return null;
}

export function checkNotRunRows(body) {
  const lines = scanLines(body);
  const start = lines.findIndex((line) => headingName(line) === HEADING);
  if (start === -1) return { status: 'unchecked', reason: `no ## ${HEADING} section to read` };

  const section = sectionLines(lines, start);
  const bare = [];
  const blockers = [];
  section.forEach((line, index) => {
    if (line.kind !== 'text' || !NOT_RUN_ROW.test(line.text)) return;
    let blocker = blockerText(line.text);
    if (!blocker) {
      const next = nextNonEmptyText(section, index);
      if (next !== null && !NOT_RUN_ROW.test(next)) blocker = blockerText(next);
    }
    if (blocker) blockers.push(blocker);
    else bare.push(line.text.trim());
  });
  if (bare.length > 0) return { status: 'hard', bare };
  return { status: 'clean', rows: blockers.length, blockers };
}

export function notRunError(result) {
  const rows = result.bare.map((row) => `"${row}"`).join('; ');
  return (
    `${result.bare.length} ${HEADING} "Not run:" row names no blocker: ${rows}. ` +
    'Either run the check and paste its result, or say what stops it with ' +
    '`Blocker: <what stops it>` on the same line or on the next line.'
  );
}

export function notRunNote(result) {
  if (result.status === 'unchecked') return `Not-run blocker check unchecked: ${result.reason}.`;
  if (result.status === 'clean' && result.rows > 0) {
    const named = result.blockers.map((blocker) => `"${blocker}"`).join('; ');
    return `Not-run blocker ${named} is not checked: nothing here judges whether the blocker is real or could have been removed.`;
  }
  return null;
}
