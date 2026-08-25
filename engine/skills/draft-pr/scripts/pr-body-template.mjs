#!/usr/bin/env node
import { loadDrafterConfig, renderPrBodyTemplate } from '@neko-catpital-labs/drafter-core';

async function main() {
  const configPath = process.argv[2];
  const config = await loadDrafterConfig({ explicitPath: configPath || undefined });
  process.stdout.write(renderPrBodyTemplate(config));
}

main();
