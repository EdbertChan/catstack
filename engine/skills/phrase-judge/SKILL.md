---
name: phrase-judge
description: >-
  Use when writing or fixing any catstack checker that decides based on what a
  text means.
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

The judge answers in the background. A dictionary checker never blocks the
agent's reply, and a hit reaches the agent later through the llm-judge inbox.
