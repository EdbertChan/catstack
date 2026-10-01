#!/usr/bin/env node
import { loadDrafterConfig, renderPrBodyTemplate } from '@neko-catpital-labs/drafter-core';
import { MEASURED_TEMPLATE } from './measured-section.mjs';
import { NOT_RUN_TEMPLATE_LINE } from './not-run-blocker.mjs';

const BEFORE_HEADING = '## Test Plan';

function withMeasured(template) {
  const at = template.indexOf(`\n${BEFORE_HEADING}\n`);
  if (at === -1) {
    console.error(`pr-body-template: no ${BEFORE_HEADING} heading in the base template; ## Measured was added at the end instead.`);
    return `${template.replace(/\n*$/, '\n\n')}${MEASURED_TEMPLATE}`;
  }
  return `${template.slice(0, at + 1)}${MEASURED_TEMPLATE}\n${template.slice(at + 1)}`;
}

function withNotRunRow(template) {
  const heading = template.indexOf(`\n${BEFORE_HEADING}\n`);
  const close = heading === -1 ? -1 : template.indexOf('\n</details>', heading);
  if (close === -1) {
    console.error(`pr-body-template: no collapsed ${BEFORE_HEADING} block in the base template; the "Not run:" row guidance was left out.`);
    return template;
  }
  return `${template.slice(0, close)}\n${NOT_RUN_TEMPLATE_LINE}\n${template.slice(close)}`;
}

async function main() {
  const configPath = process.argv[2];
  const config = await loadDrafterConfig({ explicitPath: configPath || undefined });
  process.stdout.write(withNotRunRow(withMeasured(renderPrBodyTemplate(config))));
}

main();
