#!/usr/bin/env node
import { loadDrafterConfig, renderPrBodyTemplate } from '@neko-catpital-labs/drafter-core';
import { MEASURED_TEMPLATE } from './measured-section.mjs';
import { NOT_RUN_TEMPLATE_LINE } from './not-run-blocker.mjs';

const BEFORE_HEADING = '## Test Plan';

export const WORKED_EXAMPLE_TEMPLATE = `## Worked Example

One real case per behavior change, end to end. Drop this section when the slice changes no behavior.

Before — what the code returned for job <id>, pasted as the tool printed it:

\`\`\`
<literal output: the function's return value, the debugger window, the log lines>
\`\`\`

After — the same input on this branch:

\`\`\`
<literal output>
\`\`\`

The line that made the difference, quoted from \`path/to/rule-or-code\`:

\`\`\`
<exact rule, pattern, or statement>
\`\`\`

Result: <the label, value, or state the reader will see, in one sentence>.

Back test — every real case this change touches, with a before column and an after column.
`;

function withMeasured(template) {
  const at = template.indexOf(`\n${BEFORE_HEADING}\n`);
  if (at === -1) {
    console.error(`pr-body-template: no ${BEFORE_HEADING} heading in the base template; ## Worked Example and ## Measured were added at the end instead.`);
    return `${template.replace(/\n*$/, '\n\n')}${WORKED_EXAMPLE_TEMPLATE}\n${MEASURED_TEMPLATE}`;
  }
  return `${template.slice(0, at + 1)}${WORKED_EXAMPLE_TEMPLATE}\n${MEASURED_TEMPLATE}\n${template.slice(at + 1)}`;
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
