# gate-blame-needs-evidence

Checks whether a reply blames a gate without evidence from the gate's source.

## Model-judged path

The hook checks replies that say a hook, gate, lock, guard or checker is broken, still fires, clears in a particular way, or should be disabled, removed or bypassed. The claim must rest on a successful read of the gate's source or a `file:line` citation to the rule that fired.

Only replies that name a gate whose source this session was never read or cited are judged. The hook sends the reply and the candidate gate information to the background judge using [`engine/hooks/llm-judge/phrases/gate-blame-needs-evidence.json`](../llm-judge/phrases/gate-blame-needs-evidence.json). The answer arrives on a later turn through the [`llm-judge`](../llm-judge/README.md) inbox, with the dictionary's `on_hit` text and the gate names and source locations.

The reply is never held up or sent back by this hook. If the answer could not be checked, the inbox says "could not judge" rather than treating the reply as clean. Transcript and judge errors leave the reply untouched.

## Growing the dictionary

When the judge misses a real blame claim, add its real text to the dictionary's `match` phrases. When it raises a false alarm, add the real text to `not_match`. Do not add a pattern to this hook; the meaning belongs in the phrase dictionary.
