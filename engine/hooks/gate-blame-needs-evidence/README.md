# gate-blame-needs-evidence

Checks whether a reply that blames a gate rests on evidence from that gate's source.

## What this protects

A reply may say that a hook, gate, guard, checker, lock, validator, or linter is broken, still fires, clears in a particular way, or should be switched off only after the session has read that gate's source or cites the rule with a `file:line` reference.

Quoting the gate's refusal text is not enough. A blocked or failed read is not enough. The evidence has to come from a successful source read in this session, or from a direct file citation in the reply.

## Model-judged path

On every Stop, `detect.py` looks at the latest assistant reply and finds the gates it names. It also considers delete requests for hook files and, when the reply names no gate, the latest gate that refused the session.

The hook sends a job to the background judge only for gates whose source was never read and whose rule was not cited this session. The job uses [`engine/hooks/llm-judge/phrases/gate-blame-needs-evidence.json`](../llm-judge/phrases/gate-blame-needs-evidence.json), which defines the meaning with `match` and `not_match` examples and supplies the static `on_hit` follow-up text. The queued job appends the unread gate names and their source locations to that follow-up text.

The live reply is never held up, and the hook never sends a reply back. A hit arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md) inbox. If the result could not be checked, the inbox says "could not judge" instead of treating the reply as clean. A clean verdict says nothing.

No job is sent when `stop_hook_active` is set, when the reply does not identify an unread gate, when the reply already cites the gate source, when transcript state cannot be read, or when enqueueing fails. If an unreadable transcript leaves a named gate unchecked, the hook writes the unchecked message to stderr and lets the reply pass.

To grow coverage, add the real text of any miss to the dictionary's `match` phrases, or the real text of any false alarm to `not_match`. Do not add a pattern to this hook; the prose meaning belongs in the phrase dictionary.
