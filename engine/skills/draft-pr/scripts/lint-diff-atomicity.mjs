#!/usr/bin/env node
import { loadDrafterConfig, lintDiffAtomicityForGit, formatDiffAtomicityFindings } from '@neko-catpital-labs/drafter-core';
import { execFileSync } from 'node:child_process';

function usage() {
  console.error('Usage: node scripts/lint-diff-atomicity.mjs [--base <ref>] [--root <path>] [--review-lane <lane>] [--config <file>]');
}

function hasGitRef(root, ref) {
  try {
    execFileSync('git', ['rev-parse', '--verify', `${ref}^{commit}`], { cwd: root, stdio: 'ignore' });
    return true;
  } catch {
    return false;
  }
}

function defaultBase(root) {
  const candidates = [];
  if (process.env.GITHUB_BASE_REF) candidates.push(`origin/${process.env.GITHUB_BASE_REF}`);
  candidates.push('origin/main', 'origin/master', 'main', 'master');
  for (const candidate of candidates) {
    if (hasGitRef(root, candidate)) return candidate;
  }
  return '';
}

function parseArgs(argv) {
  const parsed = { base: process.env.DRAFTER_DIFF_ATOMICITY_BASE || '', root: process.cwd(), reviewLane: '', config: '' };
  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--base': parsed.base = argv[++i] || ''; break;
      case '--root': parsed.root = argv[++i] || ''; break;
      case '--review-lane': parsed.reviewLane = argv[++i] || ''; break;
      case '--config': parsed.config = argv[++i] || ''; break;
      case '--help': usage(); process.exit(0); break;
      default:
        console.error(`Unknown argument: ${argv[i]}`);
        usage();
        process.exit(2);
    }
  }
  return parsed;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const base = args.base || defaultBase(args.root);
  if (!base) {
    console.error('Could not resolve a base ref. Pass --base <ref>.');
    process.exit(2);
  }

  const config = await loadDrafterConfig({ cwd: args.root, explicitPath: args.config || undefined });
  const findings = lintDiffAtomicityForGit({ root: args.root, baseRef: base, reviewLane: args.reviewLane, config });
  const fatal = findings.filter((f) => f.severity === 'fatal');
  const warnings = findings.filter((f) => f.severity === 'warning');

  if (fatal.length > 0) {
    console.error('Diff atomicity validation failed:');
    for (const line of formatDiffAtomicityFindings(fatal)) console.error(`  ${line}`);
    for (const line of formatDiffAtomicityFindings(warnings)) console.error(`  warning: ${line}`);
    process.exit(1);
  }

  if (warnings.length > 0) {
    console.error('Diff atomicity warnings:');
    for (const line of formatDiffAtomicityFindings(warnings)) console.error(`  ${line}`);
    process.exit(0);
  }

  console.log('Diff atomicity validation passed.');
}

main();
