# Fix the tool, not just the instance

cat-mode's SKILL.md carries the rule and when it fires. These are the rest
of the ways it applies.

- Before adding a new skill, check whether an existing one already covers
  it and consolidate instead of layering a near-duplicate on top (why
  `i-have-adhd`'s rules now live inside `diu`).
- Skills and hooks must work the same across every harness (Claude Code,
  Codex, Cursor) and machine — one-place-only is unfinished, not shippable.
- When a repeated task settles into "check status, wait, repeat" for 3+
  cycles, flag it as an automation candidate before being asked — the user
  wants both the task automated and the habit of noticing that automation
  opportunity to become the default, not just the one instance fixed
  ("how can we automate this? and automate the automation?").
- When a shared instruction file (CLAUDE.md, a skill) is getting bloated —
  one bullet ballooning into a wall of text from repeated appends — point
  it out and default to restructuring it properly (split rule from
  precedent/examples) rather than appending one more line to the mess or
  leaving it alone because the immediate task didn't ask for it.
- **Apply the strongest fix first, not the fastest to write.** When a review
  or reflect pass produces a findings list, land the categorical and
  lint/test items in the same turn; prose is the cheapest to write and the
  least likely to hold. Before opening a new investigation into a class an
  earlier pass already named, check what actually landed from that pass — an
  unapplied finding is not a finding, and a second list is worth less than
  one applied item from the first.
