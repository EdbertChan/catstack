#!/usr/bin/env node
import { readFileSync } from 'node:fs';

const MERGE_QUEUE_PREFIX = 'mergify/merge-queue/';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 1) {
    const flag = argv[i];
    const value = argv[i + 1];
    if (flag === '--head-ref') args.headRef = value;
    else if (flag === '--pr-number') args.prNumber = value;
    else if (flag === '--body-file') args.bodyFile = value;
    else continue;
    i += 1;
  }
  return args;
}

function fencedYamlBlocks(body) {
  const blocks = [];
  let current = null;
  for (const line of body.split('\n')) {
    const trimmed = line.trim();
    if (current === null && trimmed === '```yaml') current = [];
    else if (current !== null && trimmed === '```') {
      blocks.push(current);
      current = null;
    } else if (current !== null) current.push(line);
  }
  return blocks;
}

export function queuedPrNumbers(body) {
  const numbers = [];
  for (const block of fencedYamlBlocks(body)) {
    let inList = false;
    for (const line of block) {
      if (line === 'pull_requests:') {
        inList = true;
        continue;
      }
      if (!inList) continue;
      if (line && !line.startsWith(' ')) break;
      const item = line.trim();
      if (!item.startsWith('- number:')) continue;
      const value = item.slice('- number:'.length).trim();
      if (/^[1-9][0-9]*$/.test(value)) numbers.push(Number(value));
    }
  }
  return numbers;
}

export function targets({ headRef, prNumber, body }) {
  if (!headRef || !headRef.startsWith(MERGE_QUEUE_PREFIX)) {
    return { ok: true, numbers: [Number(prNumber)] };
  }
  const numbers = queuedPrNumbers(body);
  if (numbers.length === 0) {
    return {
      ok: false,
      error: `merge-queue PR #${prNumber} (${headRef}) names no pull_requests in its payload; cannot tell which PR body to check, so failing closed.`,
    };
  }
  return { ok: true, numbers };
}

function main() {
  const { headRef, prNumber, bodyFile } = parseArgs(process.argv.slice(2));
  if (!prNumber || !bodyFile) {
    console.error('usage: pr-body-targets.mjs --head-ref <ref> --pr-number <n> --body-file <file>');
    process.exit(2);
  }
  const result = targets({ headRef, prNumber, body: readFileSync(bodyFile, 'utf8') });
  if (!result.ok) {
    console.error(result.error);
    process.exit(1);
  }
  console.log(result.numbers.join('\n'));
}

if (import.meta.url === `file://${process.argv[1]}`) main();
