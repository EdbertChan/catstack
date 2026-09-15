# handback-needs-attempt

When the assistant hands the user a command or actionable step that the agent
could have attempted, flag the reply if the current turn contains no attempt
of that step.

The hook does not decide this from local wording rules. On every Claude `Stop`
it sends the current exchange to the background judge using
[`engine/hooks/llm-judge/phrases/handback-needs-attempt.json`](../llm-judge/phrases/handback-needs-attempt.json).
The dictionary defines the meaning with match and not-match examples and
supplies the static follow-up text. The live reply is never held up.

A hand-back is not flagged when it follows a permission denial, sandbox or
classifier refusal, or when the step is human-only, such as entering a
password, completing OAuth consent, or connecting and trusting hardware. A
step the agent already attempted is also not flagged. Quoted documentation or
example instructions are not treated as a hand-back.

## Next-turn delivery

The judge runs in the background. A hit is delivered through the shared
`llm-judge` inbox at the start of the next turn:

> handback-needs-attempt: this reply hands back a step the agent could have attempted without trying it. Attempt the command or step first and report the result; if it truly requires the human, name the password, OAuth consent, hardware, or preceding permission/sandbox/classifier refusal that makes it human-only.

The current reply is not delayed, and the hook prompts at most once per
transcript. A clean verdict is silent.

## Unchecked outcome

If no judge runner answers, the judge or job fails, or the result cannot be
checked, the outcome is `unchecked`, never clean. On the next turn the inbox
reports that `llm-judge: handback-needs-attempt could not judge the last reply`
and includes the runner failure reason when available. Finish the live reply
correction first; do not treat an unchecked result as permission to hand work
back.

## Files

- `detect.py` - exchange extraction, judge enqueue, and once-per-transcript state
- `claude_stop_check.py` - Claude `Stop` entrypoint
- `claude.hook.json` - Claude hook configuration
- `install_claude_hook.py` - merges the hook into Claude settings

## Install

`./install.sh` links the hook into `~/.claude/hooks/` and merges its Claude
`Stop` entry. Restart Claude after installation.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
```
