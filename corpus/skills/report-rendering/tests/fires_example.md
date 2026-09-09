`disable-model-invocation: true` means the model never reads this
skill's `description:` to decide whether to apply it -- that text isn't
even loaded into context. The only way this skill activates is an
explicit `/report-rendering` invocation.

The agent has finished a five-section spend analysis. It exists as five
markdown files and three PNG charts in a scratch directory, and each section
links its figures by relative path. The user says "show me the report," and
the agent is about to reply with the list of file paths -- to a reader who
has no checkout and will forward this to two other people. Before replying,
the agent explicitly invokes `/report-rendering` to load the full principle.

This skill fires here specifically because of that explicit invocation
-- a finished multi-section analysis with figures, about to be handed to
someone as markdown paths, is exactly the pattern the skill targets once
loaded (concatenate the sections in reading order into one self-contained
HTML file with a table of contents and each source path beside its section,
embed each chart as a data URI, add the page-break and unstick-sticky-header
print styles, print the PDF from that same HTML with headless Chrome, and
commit both rather than leaving them in the scratch directory), but no
amount of matching prose alone would have triggered it.
