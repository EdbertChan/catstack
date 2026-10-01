#!/usr/bin/env node
import { loadDrafterConfig, renderPrBodyTemplate } from '@neko-catpital-labs/drafter-core';
import { MEASURED_TEMPLATE } from './measured-section.mjs';

const BEFORE_HEADING = '## Test Plan';

function withMeasured(template) {
  const at = template.indexOf(`\n${BEFORE_HEADING}\n`);
  if (at === -1) {
    console.error(`pr-body-template: no ${BEFORE_HEADING} heading in the base template; ## Measured was added at the end instead.`);
    return `${template.replace(/\n*$/, '\n\n')}${MEASURED_TEMPLATE}`;
  }
  return `${template.slice(0, at + 1)}${MEASURED_TEMPLATE}\n${template.slice(at + 1)}`;
}

async function main() {
  const configPath = process.argv[2];
  const config = await loadDrafterConfig({ explicitPath: configPath || undefined });
  process.stdout.write(withMeasured(renderPrBodyTemplate(config)));
}

main();
