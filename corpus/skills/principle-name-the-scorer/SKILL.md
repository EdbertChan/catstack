---
name: principle-name-the-scorer
description: >
  Apply when a product has two (or more) scorers that both emit weights,
  priorities, or rankings — especially hand-authored theme/report priorities
  beside learned historical-case tag weights. Name which scorer produced
  which number; never imply one sets the other unless wiring is explicit.
disable-model-invocation: true
---

# Name the Scorer

When a product keeps **two intentional scorers** — (A) hand-authored
theme/report priorities and (B) learned historical-case tag weights — treat
them as separate provenance. Coexistence is not a feed.

**Must always:**

- Answer "where did this weight come from?" by naming the scorer (file,
  config key, or module), not by blending both into one vague "the model."
- When docs say the systems are intentionally separate, cite that separation
  instead of inventing a causal link.
- If the user asks whether B sets A (or A sets B), say no unless the code
  path that wires them is shown in the same answer.

**Must never:**

- Imply that learned case-frequency / tag weights set hand-authored finding
  or theme priorities (or the reverse) just because both are numbers in
  `[0, 1]` and both affect ranking-ish UX.
- Collapse two scorers into one sentence that makes a reader think one
  number updates the other when it does not.

**Shape to watch:**

| Lane | Typical artifact | What it scores |
| --- | --- | --- |
| A — hand-authored | `finding_priorities`, theme/report priority YAML | What this product *wants* to emphasize |
| B — learned | `learned_flag_weights`, historical-case tag weights | What *showed up* across past cases |

Same product may ship both. Provenance answers name the lane.

**Battle-tested:** A fraud-repo reflect asked whether
`learned_flag_weights` set `finding_priorities`. Docs and wiring kept them
separate; the failure was conversational — answering as if B drove A.
Found via `/reflect` (Accepted: durable skill; wiring B→A stays Backlog).

**Related, not the same:** `principle-bind-to-named-inventory` picks among
named scorers before inventing a new model. This skill is provenance: once
two scorers already exist, name which one produced the number you cite.
