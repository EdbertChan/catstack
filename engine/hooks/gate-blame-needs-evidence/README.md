# gate-blame-needs-evidence

Checks whether a reply blames a gate without evidence from the gate's source.

## What it checks

A reply that says a gate is broken, misfiring, clearing incorrectly, or should be disabled or deleted must rest on a successful read of the gate's source and a `file:line` citation to the rule that supports the claim.

Only replies that name a gate whose source was not successfully read or cited in this session are judged. Replies about gates that were read or cited are left alone.

## Model-judged path

At Stop, the hook asks the background judge to evaluate the reply using [`engine/hooks/llm-judge/phrases/gate-blame-needs-evidence.json`](../llm-judge/phrases/gate-blame-needs-evidence.json). The dictionary supplies the meaning and its `on_hit` text; the queued job also includes the names and directories of the unread gates. The answer arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md) inbox.

The hook never sends a reply back or blocks the current reply. If the answer was not checked, the inbox says "could not judge" rather than treating the reply as clean. Transcript and judge errors leave the reply untouched.

To grow coverage, add the real text of any miss to the dictionary's `match` phrases, or the real text of any false alarm to `not_match`. Do not add a pattern to this hook; the prose meaning belongs in the phrase dictionary.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/gate-blame-needs-evidence/tests -v
```
