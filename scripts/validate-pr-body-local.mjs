#!/usr/bin/env node
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PREFLIGHT = 'engine/skills/make-pr/scripts/preflight.py';
const VALIDATOR = 'engine/skills/draft-pr/scripts/validate-pr-body.mjs';
const UNCHECKED = 'UNCHECKED: PR body rules not checked (drafter-core not installed)';

function usage(reason) {
  if (reason) console.error(reason);
  console.error('Usage: node scripts/validate-pr-body-local.mjs --body-file <file> --base <branch>');
  process.exit(2);
}

function parseArgs(argv) {
  const parsed = { bodyFile: '', base: '' };
  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--body-file': parsed.bodyFile = argv[++i] || ''; break;
      case '--base': parsed.base = argv[++i] || ''; break;
      case '--help': usage(); break;
      default: usage(`Unknown option: ${argv[i]}`);
    }
  }
  if (!parsed.bodyFile) usage('Missing --body-file <file>.');
  if (!parsed.base) usage('Missing --base <branch>.');
  return parsed;
}

function run(cmd, args) {
  const res = spawnSync(cmd, args, { cwd: REPO_ROOT, encoding: 'utf-8' });
  if (res.error) {
    console.error(`validate-pr-body-local: could not start \`${cmd} ${args.join(' ')}\`: ${res.error.message}`);
    process.exit(1);
  }
  return res;
}

function echo(res) {
  if (res.stdout) process.stdout.write(res.stdout);
  if (res.stderr) process.stderr.write(res.stderr);
}

function git(args) {
  const res = run('git', args);
  if (res.status !== 0) {
    console.error(`validate-pr-body-local: \`git ${args.join(' ')}\` exited ${res.status}: ${res.stderr.trim()}`);
    process.exit(1);
  }
  return res.stdout.trim();
}

function resolveBase(base) {
  const remote = `origin/${base}`;
  return run('git', ['rev-parse', '--verify', '--quiet', remote]).status === 0 ? remote : base;
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const bodyFile = resolve(args.bodyFile);
  if (!existsSync(bodyFile)) usage(`Body file not found: ${bodyFile}`);
  const ref = resolveBase(args.base);

  const preflight = run('python3', [PREFLIGHT, '--dry-run', '--base', ref]);
  if (preflight.status !== 0) {
    echo(preflight);
    console.error(`validate-pr-body-local: ${PREFLIGHT} exited ${preflight.status} against ${ref}`);
    process.exit(1);
  }

  const mergeBase = git(['merge-base', ref, 'HEAD']);
  const changed = git(['diff', '--name-only', mergeBase]);
  const tmp = mkdtempSync(join(tmpdir(), 'validate-pr-body-local-'));
  let validator;
  try {
    const changedFile = join(tmp, 'changed-files.txt');
    writeFileSync(changedFile, changed ? `${changed}\n` : '');
    validator = run(process.execPath, [VALIDATOR, '--body-file', bodyFile, '--changed-files-file', changedFile]);
  } finally {
    rmSync(tmp, { recursive: true, force: true });
  }

  const stderr = validator.stderr || '';
  if (stderr.includes('ERR_MODULE_NOT_FOUND') && stderr.includes('@neko-catpital-labs/drafter-core')) {
    console.log(UNCHECKED);
    process.exit(0);
  }
  echo(validator);
  if (validator.status === null) {
    console.error(`validate-pr-body-local: ${VALIDATOR} was killed by ${validator.signal}`);
    process.exit(1);
  }
  process.exit(validator.status);
}

main();
