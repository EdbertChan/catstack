# Naming the Technique

The two refactor playbooks are both instances of a single Fowler technique,
repeated: `decomposition-extraction.md` is "Move Function"/"Extract Class"
applied file-by-file; `rehome-relocation.md` is "Move File"/"Rename" applied
directory-by-directory. Neither playbook restates the technique's name
because each already gives it a full slice-shape treatment. This reference
covers the rest of the catalog and states the naming rule that applies to
all of them, including the two above.

## Rule: name the technique

Every `refactor`-lane PR title or commit message states which single named
technique it applies, in the form `<Technique>: <what moved/changed>` — for
example `Move Method: git primitives -> repair_body.py`, `Extract Variable:
queue-only guard`, `Replace Conditional with Polymorphism: RepairOutcome
status dispatch`. The PR body's `## Review Claim` restates the same
technique by name. A vague claim like "clean up the module" is not
acceptable in a `refactor`-lane PR; name the technique or split further
until one name covers the whole slice.

This is not decoration: naming the technique is what lets a reviewer bring
the technique's own well-known safety properties to the review ("Extract
Variable never changes behavior by construction; I only need to check the
extracted expression is identical") instead of re-deriving correctness from
scratch for every diff.

## Technique catalog

Grouped by Fowler/refactoring.guru category. Not exhaustive — pick the
closest named technique; if none fits, say so explicitly in `## Review
Claim` rather than picking the nearest wrong name.

- **Composing Methods** — Extract Method, Inline Method, Extract Variable,
  Inline Variable, Replace Temp with Query, Split Loop, Slide Statements.
- **Moving Features Between Objects** — Move Method
  (`decomposition-extraction.md`), Move Field, Move File
  (`rehome-relocation.md`), Extract Class, Inline Class, Hide Delegate,
  Remove Middle Man.
- **Simplifying Conditional Expressions** — Decompose Conditional,
  Consolidate Conditional Expression, Replace Nested Conditional with Guard
  Clauses, Replace Conditional with Polymorphism, Introduce Null Object.
- **Simplifying Method Calls** — Rename Method, Add/Remove Parameter,
  Separate Query from Modifier, Parameterize Method, Replace Parameter with
  Explicit Methods, Preserve Whole Object, Replace Error Code with
  Exception.
- **Organizing Data** — Replace Magic Number with Symbolic Constant,
  Encapsulate Field, Replace Type Code with Class/Subclasses, Replace Array
  with Object, Change Value to Reference (and back).
- **Dealing with Generalization** — Pull Up/Push Down Method or Field,
  Extract Interface, Collapse Hierarchy, Form Template Method, Replace
  Inheritance with Delegation (and back).

## Prohibitions

- Never extract a function or class purely to make it independently
  testable. If the only justification is "now I can unit test this," the
  extraction is not earning its own review claim — either the behavior
  change that actually needs the test coverage justifies the extraction, or
  it doesn't belong in this slice.
- Never bundle a structural change with a behavioral one in the same diff.
  This restates Fowler's "two hats" as a blanket rule across every
  technique in the catalog, not just Move Function/Move File: if you notice
  a real bug while renaming a method, finish the rename, land it, then fix
  the bug as its own `behavior`-lane slice.
- Verify the affected tests stay green after each step before moving to the
  next slice in a decomposition or rehome stack. A stack where slice 3
  breaks slice 1's tests is not a stack of independently-reviewable claims
  anymore — it's one change artificially spread across three PRs.

Grounding: Fowler, *Refactoring, 2nd ed.* (the six-category catalog this
reference condenses); refactoring.guru/refactoring/techniques (the same
catalog with runnable before/after examples per technique).
