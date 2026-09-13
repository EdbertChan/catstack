# incidence-needs-repetition

Checks whether a reply claims behaviour **across runs** while showing evidence from **one** run.

## Why this exists, and why the sibling hook could not do it

`hedge-runs-prove-it` fires on the absence of confidence — "probably", "should work", a retired bare `UNVERIFIED:`. All six of its positive fixtures are hedges.

This failure mode is the opposite. On 2026-09-09 a session fixed a flaky test, ran it once green, and wrote:

> Deterministic — 2.44MB measured against a 1MB threshold, no heap involved.

Unhedged, so the sibling never saw it. Both claims in it were wrong. A repro script measuring 12 iterations showed the old instrument varied by 33,279,496 bytes and fell under the ceiling on **8 of 12** runs, and the real byte count was **4,091,671** — the published figure came from a hand-rolled model of the data rather than the code path.

The user's verdict that day was `our /prove-it is not enough`, after asking the same thing in five messages across two sessions.

## Model-judged path

On every Stop, `detect.py` hands the latest assistant reply to the background judge using [`engine/hooks/llm-judge/phrases/incidence-needs-repetition.json`](../llm-judge/phrases/incidence-needs-repetition.json). The dictionary defines the meaning with `match` and `not_match` examples and supplies the static `on_hit` follow-up text.

The live reply is never held up. A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md) inbox. If the result could not be checked, the inbox says "could not judge" instead of treating the reply as clean. A clean verdict says nothing.

No job is sent when `stop_hook_active` is set, when the same Bash command already ran twice in the turn, when the reply is empty, or when transcript state cannot be read. All enqueue errors fail open.

To grow coverage, add the real text of any miss to the dictionary's `match` phrases, or the real text of any false alarm to `not_match`. Do not add a pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/incidence-needs-repetition/tests -v
```
