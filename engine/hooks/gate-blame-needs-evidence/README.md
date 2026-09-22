# gate-blame-needs-evidence

Checks whether a reply blames a gate without first grounding that claim in the gate source.

A reply that says a hook, gate, lock, guard, checker, validator, or linter is broken, misfiring, still firing, clearing in a particular way, or should be disabled must rest on either a successful read of that gate's source this session or a file:line citation to the rule being discussed.

## Model-judged path

On Stop, `detect.py` looks at the latest assistant reply and finds the gates it names, the gates named in delete requests, or, when the reply names none, the latest gate that refused the session. It drops any gate whose source was successfully read this session, and any gate that the reply cites with a file:line reference.

Only the remaining unread and uncited gates are sent to the background judge through [`engine/hooks/llm-judge/phrases/gate-blame-needs-evidence.json`](../llm-judge/phrases/gate-blame-needs-evidence.json). The dictionary defines the meaning with `match` and `not_match` examples and supplies the static `on_hit` follow-up text. The queued job appends the remaining gate names and source locations to that text.

The live reply is never held up, and this hook never sends a reply back. A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md) inbox. If the result could not be checked, the inbox says "could not judge" instead of treating the reply as clean. A clean verdict says nothing.

No job is sent when `stop_hook_active` is set, when the reply is empty, when no unread and uncited gate is named or implied, or when transcript state cannot be read. Transcript problems on a reply that names a gate produce today's unchecked stderr message and still leave the reply untouched. All judge and transcript errors fail open.

To grow coverage, add the real text of any miss to the dictionary's `match` phrases, or the real text of any false alarm to `not_match`. Do not add a pattern; the prose meaning belongs in the phrase dictionary.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/gate-blame-needs-evidence/tests -v
```
