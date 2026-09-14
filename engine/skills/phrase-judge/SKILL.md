---
name: phrase-judge
description: >-
  Use when writing, fixing, or working around any checker, gate, or lint, in any
  repo, that decides based on what a text means.
---

# Phrase Judge

Use a phrase dictionary for any checker whose decision depends on the meaning
of prose. A checker declares that meaning in
`engine/hooks/llm-judge/phrases/<checker>.json`, then builds an llm-judge job
from that dictionary instead of owning its own prompt text.

Seed `match` and `not_match` with real pasted texts. When the checker misses a
reworded case, add that text to `match`. When it fires on harmless text, quoted
text, or negated text, add that text to `not_match`. Grow the dictionary from
real misses instead of writing a regex.

Use regex only for parsing fixed machine formats such as JSON fields, command
output labels, or file paths. Do not use a regex to decide whether free-form
prose means the checker's condition.

This holds in every repo, including checkers this repo does not own. When a
word or pattern list decides meaning, replace the decision: never trim, extend,
or reword around the list. Decide from typed inputs when they exist — declared
file lists, JSON fields, exit codes — as in Alexis King,
[Parse, don't validate](https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/)
(2019). Where meaning still needs a judge but none can run, such as CI without
model access, the check reports unchecked and warns; it never passes silently.

The judge answers in the background. A dictionary checker never blocks the
agent's reply, and a hit reaches the agent later through the llm-judge inbox.
