# What the claim check can and cannot see

`claude_stop_check.py` reads one piece of text: the main agent's last
message of a turn. It reads nothing else. When it is silent about text it
never read, that silence means "not checked", not "clean".

An audit replayed a narrower, earlier version of the check over 56 stored
Claude Code transcript files and listed every unproven claim that got
through. There were 337. Where they were written, and how many the current
patterns match as text:

| Surface | Unproven claims | Reaches the check? | Current patterns match | Still missed |
|---|---|---|---|---|
| Main agent, turn-final message | 141 | Yes | 45 | 96 |
| Main agent, mid-turn text | 135 | No | 38 | 135 |
| Subagent (20 turn-final, 41 mid-turn) | 61 | No | 17 | 61 |
| Total | 337 | | 100 | 292 |

196 of the 337 were never in front of the detector. Widening its patterns
cannot reach them: the current patterns match 100 of the 337 as text, but
55 of those sit on surfaces the hook never runs on, so they are still
missed.

The counts come from the audit's `escapes.tsv`, which is not checked in
(column 5 is the agent, column 6 the turn position):

```
$ awk -F'\t' 'NR>1 && $6!="payload"{print $5"/"$6}' escapes.tsv | sort | uniq -c
    141 main/final
    135 main/midturn
     20 sub/final
     41 sub/midturn
```

## 337 is a floor, not a ceiling

For main-agent turn-final messages the stored text is post-hook text. The
block fires, the model rewrites, and the transcript keeps only the rewrite.
So the real miss rate against the original drafts is higher than 337, and
it cannot be computed from stored data.

## Main agent, turn-final message

What reaches the check: the Stop event's `last_assistant_message`. Both the
word cap and the claim check run on it.

What does not:

- The rewrite after a block. Once the hook has blocked a turn,
  `stop_hook_active` is set and the next message goes through unchecked.
- Claims the patterns do not match. The check is a text proxy. It looks for
  claim-shaped phrases (the banned phrases, a "confirmed" or "verified"
  opener, a causal closer, a hedged cause) and for evidence-shaped text in
  the same paragraph (a fence, output-shaped inline code, `UNVERIFIED:`). It
  cannot tell whether the evidence is real. Of the 141 claims on this
  surface, the current patterns match 45 and miss 96.

What to do instead: read silence here as "no claim-shaped phrase without
evidence-shaped text beside it", nothing more. A claim still needs its proof
in the same message.

## Main agent, mid-turn text

What reaches the check: nothing. Text written before another tool call is
never the last message of the turn, and there is no Stop event between tool
calls to hang a check on.

What does not: all 135.

What to do instead: the user reads this text live, so the evidence rules
apply to it the same way. Put a claim in the same message as its proof, or
hold it for the final message, where the check does read it. When reading a
transcript, treat mid-turn claims as unchecked.

## Subagent

What reaches the check: nothing. `main()` returns on `agent_id` before
either check runs. `install.sh` mirrors every Stop hook to `SubagentStop`
(`scripts/mirror_stop_hooks_to_subagent_stop.py`), and `claude.hook.json`
declares no `subagent_stop` opt-out, so the hook is called for a subagent
and then exits without looking.

Why: no reason is written down in the script, the manifest, or the tests.
The word cap is the half that fits. It is a rule for messages to the human,
and a subagent's final message is a report to its parent agent, which often
needs the detail. The claim check shares the same early return, so it is
skipped too. `auto-pr` and `frustration-watchdog` skip subagents through a
manifest opt-out with a reason; this hook does not.

What does not reach it: all 61, turn-final and mid-turn alike.

What to do instead: the parent agent is the check. Treat a subagent's claim
as unverified until the report carries pasted output or a `file:line` the
parent can re-read, and re-run the check before passing the claim to the
user. `hedge-runs-prove-it` has no `agent_id` guard and is mirrored to
`SubagentStop` as well; the audit did not measure what it catches on
subagent text.

## Tool payloads

The audit also found 30 claims written into tool calls rather than chat.
They are not in the 337. This hook never reads tool input. Some other hooks
check payloads where they are used, such as `history-claim-check` on a PR
body that states repo history with no evidence; the audit did not measure
them.
