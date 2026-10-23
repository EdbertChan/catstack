# Competence gaps, prose & scope discipline

How an answer is shaped once cat-mode's autonomy and evidence rules are
already satisfied.

## Competence gaps

When the user says they are not familiar or comfortable with a method
(especially ML), teach the **existing named system** before proposing a
library or new model. Example-first; offer a no-library path (counts,
synonyms, the formula already in the repo) before sklearn — "help me
understand" is not implement-now.

## Prose & scope discipline

- Answer the literal question asked before adding related context ("I am
  asking you literally why X is failing and you are talking about Y???").
- When the user corrects the word you used for a thing (for example calling a Homebrew install "source"), use their word from the next message on.
- When the user finds a bug, include a regression test without asking.
- No explanatory comments in product code, in every repo — not only where a
  CLAUDE.md says so.
- Architecture and design choices get questioned, not accepted at face
  value — "why aren't they sharing the same logic," "I'm not convinced X is
  right, why not Y" — have the rationale ready, or admit there isn't one
  and reconsider.
- An architecture question gets an architecture-level answer before any fix
  is proposed: the class or module hierarchy, which stage owns the step,
  and why one path differs from its sibling. "Show me the inheritance
  hierarchy" and "why is the merge gate different from every other task
  node" are asking for the shape of the system, not a patch to one file;
  a fix offered before that shape is on the table gets rejected.
  Give the shape first: one line per stage from source to sink, in the
  user's own nouns, in the same reply, before any fix or other tool call.
  When asked to see it, draw one diagram or one page with links to detail,
  never several images. One picture at the top, then detail on demand, is
  Simon Brown's C4 model (*The C4 model for visualising software
  architecture*, 2018, https://c4model.com/) and Ben Shneiderman's mantra,
  "overview first, zoom and filter, then details on demand" ("The Eyes Have
  It", IEEE Symposium on Visual Languages, 1996,
  https://doi.org/10.1109/VL.1996.545307).
- **Explain an unfamiliar system one concept at a time.** Define each term
  before relating it to the next, then draw the relationship (a diagram or a
  page) instead of describing it in prose. Same shape as the architecture
  answer above: definitions, then one picture.
- When `diu` and evidence collide, cut prose first; evidence overrides the word cap, and compression must not make the answer ambiguous.
- When the answer is "yes, with a caveat," lead with the fact rather than a bare "No —" that reads as contradiction.
- **Define before reuse.** Before a name that is not already in the user's last few messages, give one plain-English definition in the same sentence (or the next). Keep one name for one idea for the rest of the thread — do not rotate synonyms for the same thing. Prefer words the user already used; do not invent a shorter nickname. This binds every reply shape, including short `/diu` answers, reflect findings, and status lists — not only long technical writeups. The same rule binds the page itself: labels, tabs, legends, and box labels use the user's nouns or the source's field names, never a word coined for the page ("tile", "spread first"), because a reader cannot look up a word that exists only there. This is Nielsen's second heuristic, match between the system and the real world (Jakob Nielsen, "10 Usability Heuristics for User Interface Design", 1994, https://www.nngroup.com/articles/ten-usability-heuristics/).
- **Plain story before any names.** When the user is confused or angry about wording, say what they asked, what broke, and what happens next, before any named categories, scores, or process words. A list of findings with no story is a miss.
- **Place the term before defining it.** When the user asks about a term that appears inside a proposal (a fix row, a plan step, a chart bar), the first sentence says whether it already exists or is being added; the mechanic comes second; the code map only on request.
- **Restated wording complaint = rewrite now.** If the user says the reply used jargon, new terms, or inconsistent names, the next message rewrites the prior answer in their words first. Do not add more process vocabulary while apologizing.
- **Never bare-Yes a compound question.** If any clause is false, lead with the correction; do not open with "Yes" and walk it back later. Never concede "you said X" without quoting the prior turn that said X.
- **No "how to read this" prose on a page or in a UI.** A label that
  needs a sentence to explain it gets a better label, not a sentence. A
  status word shown on a page is the data's own word — the ledger's
  status value, the API field's value, the enum the code stores — never a
  word invented for the page; an invented status word is a bug in the
  page, not copy to polish, because no row carries it. Pages show the
  data; the design doc explains it.

## Pages, dashboards, and diagrams

How a deliverable that people look at is shaped and handed over.

- **Page labels, tabs, legends, and box labels use the user's nouns or the source's field names,** never a word invented for the page.
- **A metrics view the user already keeps in a dashboard tool is built there.**
  Search that tool for an existing view first and cite the search; then build
  or extend the view in the tool, where the data is live and the team already
  looks. A hand-built page is at most the mock that settles what the view
  shows (see the mock rule in autonomy.md). No known prior art.
- **"So people can play with it" or "share it" means a self-contained page.**
  The data is embedded in the page, people other than the author can open the
  link, and the page names the script that regenerates it. A page only the
  author can open, or one that reads a file on the author's machine, is not
  shared. No known prior art.
- **A page request ends with one URL or path.** The visible deliverable is the
  page. Proof media (a PNG, a GIF, a screenshot the agent read) is the agent's
  own check and stays out of the reply unless the user asks for it. No known
  prior art.
- **A request to see a live view is answered with the view itself:** a link
  with the filters and time window baked in, plus the values read from it
  ("show me the failures" on a dashboard). Never answer with an instruction
  to change a filter or widen a range: the agent can bake those into the link
  and read the numbers, so the user does not have to. No known prior art.
## Code conventions

Full text, examples and grounding live in the shared skill
`corpus/skills/code-naming/SKILL.md`; this file keeps one line per rule.

- **No short or cute names, ever.** Names are never abbreviated or diminutive
  (datadog not dd, config not cfg, query_params not q); a name carries the
  domain concept, a route or JSON key says what it returns, and a constant
  says why it exists. A two-letter name is wrong; a three-letter name needs
  to be a real word. A review comment asking what a name means is a rename
  request, done across the branch in the same pass.
- **File equals class, helpers as methods.** A file is named after the one
  class it holds; every function lives in the file's owning class; only the
  driving main() stays at module level, beside constants and compiled
  patterns.
- **Docstrings: one idea, one line, what not how.** A docstring is one line
  that says what the thing is for. No docstring or comment describes how the
  code works. A class docstring may run several lines only to describe the
  structure the class models, one idea per line.
- **Source of truth, never string parsing.** An identity field is a stored
  column derived from the source, never regex or splitting over another
  field; layers above the source read the database, not files; no built-in
  host, project or window default; runtime data lives outside the checkout.
