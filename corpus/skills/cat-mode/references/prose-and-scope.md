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
- Name Invoker's install channel from the user's command (`/opt/homebrew` is a Node prefix; a checkout is not "source"); after a channel-noun correction, drop the rejected term at once.
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
- When `diu` and evidence collide, cut prose first; evidence overrides the word cap, and compression must not make the answer ambiguous.
- When the answer is "yes, with a caveat," lead with the fact rather than a bare "No —" that reads as contradiction.
- **Define before reuse.** Before a name that is not already in the user's last few messages, give one plain-English definition in the same sentence (or the next). Keep one name for one idea for the rest of the thread — do not rotate synonyms for the same thing. Prefer words the user already used; do not invent a shorter nickname. This binds every reply shape, including short `/diu` answers, reflect findings, and status lists — not only long technical writeups.
- **Scene before labels.** When the user is confused or angry about wording, open with the everyday story of their problem (what they asked, what broke, what happens next) before any named buckets, scores, or process lists. A list of findings with no scene is a miss.
- **Restated wording complaint = rewrite now.** If the user says the reply used jargon, new terms, or inconsistent names, the next message rewrites the prior answer in their words first. Do not add more process vocabulary while apologizing.
- **Never bare-Yes a compound question.** If any clause is false, lead with the correction; do not open with "Yes" and walk it back later. Never concede "you said X" without quoting the prior turn that said X.

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
