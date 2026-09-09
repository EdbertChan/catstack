# incidence-needs-repetition

Blocks a reply that claims behaviour **across runs** while showing evidence from **one** run.

## Why this exists, and why the sibling hook could not do it

`hedge-runs-prove-it` fires on the absence of confidence — "probably", "should work", `UNVERIFIED:`. All six of its positive fixtures are hedges.

This failure mode is the opposite. On 2026-09-09 a session fixed a flaky test, ran it once green, and wrote:

> Deterministic — 2.44MB measured against a 1MB threshold, no heap involved.

Unhedged, so the sibling never saw it. Both claims in it were wrong. A repro script measuring 12 iterations showed the old instrument varied by 33,279,496 bytes and fell under the ceiling on **8 of 12** runs, and the real byte count was **4,091,671** — the published figure came from a hand-rolled model of the data rather than the code path.

The user's verdict that day was `our /prove-it is not enough`, after asking the same thing in five messages across two sessions.

## The rule

"Deterministic", "flaky", "every run", "consistently" are claims about a *distribution*, not about what code says. One execution cannot support one — and neither can a `file:line`, which is why the sibling's evidence bar (it accepts a bare `file.ts:42`) does not transfer.

## What clears it

- a declared sample size of two or more: `12 iterations`, `8/12 runs`, `spread=…`
- the same Bash command actually invoked twice or more in the turn
- an `UNVERIFIED:` prefix, which stops the claim being asserted

## What does not clear it

- one green run, however clean
- a `file:line`
- a fenced block with no sample size in it

## Out of scope

Incidence words quoted rather than claimed, and any run inside a fence or backticks. Judgment stays with the model; `detect.py` matches shapes and fails open on any read or parse error.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/incidence-needs-repetition/tests -v
```
