# gate-blame-needs-evidence

Checks whether a reply blames a gate without evidence from reading the gate's source or citing the rule as `file:line`.

## Model-judged path

Only replies that name a gate whose source this session never successfully read or cited are judged. The hook sends the reply to the background judge using [`engine/hooks/llm-judge/phrases/gate-blame-needs-evidence.json`](../llm-judge/phrases/gate-blame-needs-evidence.json), which defines the meaning with `match` and `not_match` examples.

The answer arrives on a later turn through the shared [`llm-judge`](../llm-judge/README.md) inbox. It includes the dictionary's `on_hit` text plus the names and locations of the gates that still need to be read. An unchecked answer says "could not judge" rather than treating the reply as clean. The hook never sends a reply back or holds up the current reply.

If the transcript cannot be read, the hook keeps today's unchecked message on stderr and queues nothing. Other judge or transcript errors leave the reply untouched.

To grow coverage, add the real text of any miss to the dictionary's `match` phrases, or the real text of any false alarm to `not_match`. Do not add a pattern to this hook; the prose meaning belongs in the phrase dictionary.
