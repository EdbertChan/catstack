# handback-needs-attempt

On Claude `Stop`, this background judge flags a reply that hands the user a command or actionable step the agent could have attempted, when the current turn has no attempt before the hand-back. It is the mechanical backstop for cat-mode's rule that a hand-back is an unverified claim.

It stays silent after a permission denial, sandbox or classifier refusal, or a step that only the human can do, such as entering a password, granting OAuth consent, or connecting hardware. Quoted or documented instructions are not hand-backs. The judge sees the latest reply and the current turn's tool calls and results.

The hook is fail-open for malformed or unreadable hook input and never blocks the live reply. A judge hit arrives through `llm-judge` on the next turn. If no judge runner answers, the inbox reports `could not judge`; that unchecked result is not clean.

When prompted, attempt the command or step first and report the result. If it truly requires the human, name the reason. `stop_hook_active` is a one-rewrite escape hatch.

## Files

- `detect.py` builds the exchange job and once-per-transcript state.
- `claude_stop_check.py`, `claude.hook.json`, and `install_claude_hook.py` provide the Claude Stop wiring.
- `tests/` covers positive, negative, refusal, human-only, unreadable, and unchecked outcomes.
- `../llm-judge/phrases/handback-needs-attempt.json` owns the prose meaning and examples.

## Install

Run `./install.sh` from the repository root and restart Claude Code.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/handback-needs-attempt/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/handback-needs-attempt
```
