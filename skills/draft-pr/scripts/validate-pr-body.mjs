#!/usr/bin/env node
import { readFileSync } from 'node:fs';
import { loadDrafterConfig, validatePrBody, getPrBodyWarnings } from '@neko-catpital-labs/drafter-core';

function usage() {
  console.error(`Usage: node scripts/validate-pr-body.mjs (--body-file <file> | --body <markdown>) [--require-visual-proof] [--changed-files-file <file>] [--diff-file <file>] [--config <file>]`);
  process.exit(1);
}

function parseArgs(argv) {
  const parsed = { body: '', bodyFile: '', requiresVisualProof: false, changedFilesFile: '', diffFile: '', config: '' };
  for (let i = 0; i < argv.length; i++) {
    switch (argv[i]) {
      case '--body': parsed.body = argv[++i] || ''; break;
      case '--body-file': parsed.bodyFile = argv[++i] || ''; break;
      case '--require-visual-proof': parsed.requiresVisualProof = true; break;
      case '--changed-files-file': parsed.changedFilesFile = argv[++i] || ''; break;
      case '--diff-file': parsed.diffFile = argv[++i] || ''; break;
      case '--config': parsed.config = argv[++i] || ''; break;
      case '--help': usage(); break;
      default:
        console.error(`Unknown option: ${argv[i]}`);
        usage();
    }
  }
  if (Boolean(parsed.body) === Boolean(parsed.bodyFile)) {
    console.error('Pass exactly one of --body or --body-file.');
    usage();
  }
  return parsed;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const body = args.bodyFile ? readFileSync(args.bodyFile, 'utf-8') : args.body;
  const changedFiles = args.changedFilesFile
    ? readFileSync(args.changedFilesFile, 'utf-8').split('\n').map((l) => l.trim()).filter(Boolean)
    : undefined;
  const diffText = args.diffFile ? readFileSync(args.diffFile, 'utf-8') : undefined;
  const config = await loadDrafterConfig({ explicitPath: args.config || undefined });

  const result = await validatePrBody(body, { requiresVisualProof: args.requiresVisualProof, changedFiles, diffText, config });
  const warnings = getPrBodyWarnings(body, { changedFiles, diffText, config });

  if (result.errors.length > 0) {
    console.error('PR body validation failed:');
    for (const error of result.errors) console.error(`- ${error}`);
    process.exit(1);
  }

  if (warnings.length > 0) {
    console.error('PR body validation warnings:');
    for (const warning of warnings) console.error(`- ${warning}`);
  }

  console.log('PR body validation passed.');
}

main();
