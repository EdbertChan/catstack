---
name: report-rendering
description: "Apply when a report, analysis, or write-up is finished and someone other than the author will read it. Ship it as a single self-contained HTML file, and a PDF where a fixed page is wanted. Markdown split across several files in a repo is a working artifact, not a delivered report. Reach for it on: a multi-section analysis, a report with figures, anything to be handed to someone without a checkout, or any request to 'show me the report'."
disable-model-invocation: true
---

# Render the report

A report that only exists as markdown in a repo has not been delivered. It has
been left where the author was working. The reader either lacks a checkout, or
has one and must open several files in the right order and imagine the figures
in place.

Ship one file that opens by double-clicking it.

## Must always

- **One self-contained HTML file.** Embed every figure as a `data:` URI rather
  than linking a path. A document that breaks when moved is not a deliverable.
  Inline the CSS for the same reason.
- **Concatenate the sections in reading order**, with a table of contents and
  each source path shown beside its section, so a reader can find the file
  behind any claim.
- **Add print styles.** `page-break-before` on each top-level section, and
  unstick any `position: sticky` table headers, which otherwise repeat or
  vanish across page boundaries. Without this the PDF is unusable even though
  the HTML looks correct.
- **Produce the PDF from the same HTML**, so the two cannot disagree.
- **Commit both**, and say where they are. A rendered report that lives only in
  a temp directory has the same problem as the markdown did.

## Must never

- Hand back a list of markdown paths in response to "show me the report."
- Link figures by relative path in a document intended to be sent anywhere.
- Reach for pandoc, LaTeX, or a new dependency when the machine already has a
  browser. The recipe below needs nothing else.
- Render a report whose numbers have not passed their own gate. Rendering makes
  a claim easier to circulate, which is a reason to be more careful about what
  is in it, not less. See [[principle-report-the-disqualifier]].

## The recipe

Markdown to self-contained HTML to PDF, with no toolchain beyond a browser:

```python
import base64, markdown
from pathlib import Path

md = markdown.Markdown(extensions=["tables", "fenced_code", "toc", "sane_lists"])
parts = []
for title, path in SECTIONS:
    md.reset()
    parts.append(f"<section><h1>{title}</h1>{md.convert(Path(path).read_text())}</section>")

fig = base64.b64encode(Path(FIGURE).read_bytes()).decode()
parts.append(f'<figure><img src="data:image/png;base64,{fig}"/></figure>')
Path("report.html").write_text(TEMPLATE.format(body="".join(parts)))
```

```sh
google-chrome --headless --disable-gpu --no-sandbox \
  --print-to-pdf=report.pdf --print-to-pdf-no-header report.html
```

`md.reset()` between sections matters: the `toc` extension accumulates state
across calls, so without it later sections inherit earlier anchors.

## Grounding

- Single-file, self-contained documents as a distribution format → the MHTML
  and `data:` URI approach; RFC 2397, "The 'data' URL scheme" (1998)
  <https://doi.org/10.17487/RFC2397>.
- Literate and reproducible reporting, where the document and the analysis that
  produced it are one artifact → Donald E. Knuth, "Literate Programming,"
  *The Computer Journal* 27(2), 97-111 (1984)
  <https://doi.org/10.1093/comjnl/27.2.97>; Roger D. Peng, "Reproducible
  Research in Computational Science," *Science* 334(6060), 1226-1227 (2011)
  <https://doi.org/10.1126/science.1213847>.
- Delivering a result in the form the reader can act on, rather than the form
  the author worked in: **no known prior art** as a stated principle; it is
  ordinary practice rather than a named result.

Related: [[principle-report-the-disqualifier]] (what the report must contain
before it is worth rendering).
