#!/usr/bin/env node
import { loadDrafterCore } from './drafter-core-flag.mjs';

const UNCHECKED_EXIT = 3;

async function main() {
  const configPath = process.argv[2];
  const drafter = await loadDrafterCore();
  if (!drafter) process.exit(UNCHECKED_EXIT);
  const config = await drafter.loadDrafterConfig({ explicitPath: configPath || undefined });
  process.stdout.write(drafter.renderPrBodyTemplate(config));
}

main();
