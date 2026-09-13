export const MAX_GRADE = 11;
export const MAX_LONG_WORD_SHARE = 0.25;
export const MIN_WORDS = 20;
export const MAX_SUMMARY_WORDS = 150;

function syllables(word) {
  let w = word.toLowerCase().replace(/[^a-z]/g, '');
  if (!w) return 0;
  if (w.length <= 3) return 1;
  w = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, '').replace(/^y/, '');
  return Math.max(1, (w.match(/[aeiouy]{1,2}/g) || []).length);
}

function sectionText(body, heading) {
  const match = new RegExp(`^## ${heading}[ \\t]*\\n([\\s\\S]*?)(?=^## |(?![\\s\\S]))`, 'm').exec(body || '');
  return match ? match[1] : null;
}

export function summaryText(body) {
  const section = sectionText(body, 'Summary');
  if (section === null) return null;
  return section
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/`[^`\n]*`/g, 'X')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1')
    .trim();
}

export function scoreSummary(body) {
  const text = summaryText(body);
  if (text === null) {
    return { status: 'unchecked', reason: 'no ## Summary section to score' };
  }
  const words = text.match(/[A-Za-z][A-Za-z'-]*/g) || [];
  if (words.length < MIN_WORDS) {
    return {
      status: 'unchecked',
      reason: `Summary has ${words.length} words; under ${MIN_WORDS} the score is too noisy to trust`,
    };
  }
  const sentences = text.split(/[.!?;:]+(?:\s|$)|\n\s*\n/).filter((s) => /\w/.test(s));
  const counts = words.map(syllables);
  const totalSyllables = counts.reduce((a, b) => a + b, 0);
  const grade = 0.39 * (words.length / sentences.length) + 11.8 * (totalSyllables / words.length) - 15.59;
  const longShare = counts.filter((n) => n >= 3).length / words.length;
  const roundedGrade = Math.round(grade * 10) / 10;
  const percent = Math.round(longShare * 100);
  const hard = roundedGrade > MAX_GRADE || longShare > MAX_LONG_WORD_SHARE;
  return { status: hard ? 'hard' : 'clean', grade: roundedGrade, longPercent: percent };
}

export function readingGradeError(score) {
  return (
    `Summary is too hard to read: reading grade ${score.grade} (limit ${MAX_GRADE}), ` +
    `${score.longPercent}% words of three or more syllables (limit ${Math.round(MAX_LONG_WORD_SHARE * 100)}%). ` +
    'Rewrite it for someone who never saw the code: short sentences, everyday words, ' +
    'and explain or cut every term coined while working (see the diu skill).'
  );
}

export function summaryWordCount(body) {
  const section = sectionText(body, 'Summary');
  if (section === null) {
    return { status: 'unchecked', reason: 'no ## Summary section to count' };
  }
  const words = (section.match(/\S+/g) || []).filter((token) => /[A-Za-z0-9]/.test(token)).length;
  return { status: words > MAX_SUMMARY_WORDS ? 'hard' : 'clean', words };
}

export function wordCapError(count) {
  return (
    `Summary is too long: ${count.words} words (limit ${MAX_SUMMARY_WORDS}). ` +
    `Rewrite it with the diu skill and cut at least ${count.words - MAX_SUMMARY_WORDS} words: ` +
    'say what changed for a person, then the problem and the fix. Detail belongs in later sections.'
  );
}

export const CODE_NAME_SECTIONS = ['Summary', 'Review Claim'];

const FILE_EXTENSIONS = new Set([
  'py', 'mjs', 'cjs', 'js', 'jsx', 'ts', 'tsx', 'md', 'mdc', 'json', 'yml', 'yaml', 'toml', 'ini', 'cfg',
  'sh', 'bash', 'zsh', 'txt', 'tsv', 'csv', 'html', 'css', 'go', 'rs', 'rb', 'java', 'kt', 'swift',
  'c', 'h', 'cpp', 'sql', 'lock', 'xml', 'plist',
]);

const TOKEN =
  /```([\s\S]*?)```|`([^`\n]+)`|<!--[\s\S]*?-->|\]\([^)\s]*\)|https?:\/\/[^\s)>]+|<\/?[A-Za-z][^>]*>|([\w./~-]+)/g;

function changedFileNames(changedFiles) {
  const names = new Map();
  const add = (name, kind) => {
    if (name && !names.has(name)) names.set(name, kind);
  };
  for (const file of changedFiles || []) {
    const parts = file.split('/').filter((part) => part && part !== '.' && part !== '..');
    const base = parts.pop();
    for (const folder of parts) add(folder, 'changed folder name');
    if (base) {
      add(base, 'changed file name');
      add(base.replace(/\.[^.]+$/, ''), 'changed file name');
    }
  }
  return names;
}

function wordKind(word, changedNames) {
  if (changedNames.has(word)) return changedNames.get(word);
  if (word.includes('/')) return 'file path';
  const extension = /\w\.([A-Za-z0-9]+)$/.exec(word);
  if (extension && FILE_EXTENSIONS.has(extension[1])) return 'file path';
  if (/[A-Za-z0-9]_+[A-Za-z0-9]/.test(word)) return 'snake_case';
  if (/^[a-z][a-z0-9]*[A-Z]/.test(word)) return 'camelCase';
  return null;
}

function sectionCodeNames(section, changedNames) {
  const found = [];
  const add = (name, kind) => {
    if (name && !found.some((f) => f.name === name)) found.push({ name, kind });
  };
  for (const match of section.matchAll(TOKEN)) {
    const [, fenced, inline, word] = match;
    if (fenced !== undefined) {
      const firstLine = fenced.replace(/^[\w-]*\n/, '').split('\n').map((l) => l.trim()).find(Boolean);
      add((firstLine || 'code block').slice(0, 60), 'code block');
    } else if (inline !== undefined) {
      add(inline.trim(), 'in backticks');
    } else if (word !== undefined) {
      const cleaned = word.replace(/^(?:[-_]+|\.{2,})/, '').replace(/[._-]+$/, '');
      if (!/[A-Za-z]/.test(cleaned)) continue;
      const kind = wordKind(cleaned, changedNames);
      if (kind) add(cleaned, kind);
    }
  }
  return found;
}

export function findCodeNames(body, changedFiles = []) {
  const changedNames = changedFileNames(changedFiles);
  const found = [];
  const missing = [];
  for (const heading of CODE_NAME_SECTIONS) {
    const section = sectionText(body, heading);
    if (section === null) {
      missing.push(`## ${heading}`);
      continue;
    }
    const names = sectionCodeNames(section, changedNames);
    if (names.length > 0) found.push({ section: heading, names });
  }
  const reason = missing.length > 0 ? `no ${missing.join(' or ')} section to read` : undefined;
  if (found.length > 0) return { status: 'hard', found, reason };
  if (reason) return { status: 'unchecked', found, reason };
  return { status: 'clean', found };
}

export function codeNameError(result) {
  const where = result.found
    .map(({ section, names }) => `${section}: ${names.map(({ name, kind }) => `"${name}" (${kind})`).join(', ')}`)
    .join('; ');
  return (
    `Summary and Review Claim must not use code names. Found in ${where}. ` +
    'Say what the part does in everyday words; put the name in a later section such as Test Plan.'
  );
}
