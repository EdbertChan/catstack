export const MAX_GRADE = 11;
export const MAX_LONG_WORD_SHARE = 0.25;
export const MIN_WORDS = 20;

function syllables(word) {
  let w = word.toLowerCase().replace(/[^a-z]/g, '');
  if (!w) return 0;
  if (w.length <= 3) return 1;
  w = w.replace(/(?:[^laeiouy]es|ed|[^laeiouy]e)$/, '').replace(/^y/, '');
  return Math.max(1, (w.match(/[aeiouy]{1,2}/g) || []).length);
}

export function summaryText(body) {
  const match = /^## Summary[ \t]*\n([\s\S]*?)(?=^## |(?![\s\S]))/m.exec(body || '');
  if (!match) return null;
  return match[1]
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
