# hedge-runs-prove-it

Stop hook: a hedge about code or repo state is a check the agent has not
run. When the outgoing reply says "I think", "I believe", "probably",
"should work", "presumably", or carries an `UNVERIFIED:` prefix within 200
characters of a code noun (a path, a backticked name, test, CI, build, bug,
fix, script, hook, PR, merge, branch, commit, tree) and the turn ran no
verification tool (Bash, Read, Grep, Glob), the turn is blocked (exit 2)
with "run prove-it now: verify in this turn or state why it cannot be
verified".

Passes when the turn ran a verification tool, when the `UNVERIFIED:`
sentence carries a cannot-verify reason ("cannot verify: no network",
"would need the live token"), when the hedge is quoted, or when the hedge
is about something that is not code or state (a company's motive).

Mechanical half of the evidence rules in `engine/CLAUDE.core.md` ("never
claim ... without evidence in the SAME message"; `UNVERIFIED:` is the
escape hatch, not a free pass). Fail-open on parse or read errors;
`stop_hook_active` skips.

## Files

- `detect.py` -- hedge, code-noun, and reason patterns; turn scan; `decide()`.
- `claude_stop_check.py` -- Claude Stop entrypoint.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/fixtures/hedges_{fires,silent}.json` -- sanitized real replies and
  the rule's own shapes.
- `tests/test_hooks.py`

Tests: `python3 -m unittest discover -s engine/hooks/hedge-runs-prove-it/tests -v`
