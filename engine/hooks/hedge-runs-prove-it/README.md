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

## The unhedged half

A hedge announces its own missing check. A confident diagnosis does not, so
it is the more dangerous shape and it used to pass this gate untouched. The
hook also blocks a reply that asserts live system state -- "it's a zombie",
"that's the bug", "the root cause is X", "the worker is hung", "this is why
it's slow" -- within 200 characters of a runtime noun (process, pid, worker,
task, pool, queue, slot, workflow, socket, lock, CPU, disk) and carries no
instrument-level proof in the same message.

Running a tool in the turn does not clear this one; a projection that omits
a field is not proof the state is absent. Only same-message proof clears it:
a fenced block of real output, a `file:line`, a pid, an exit code, a
`/proc/<pid>` path, or an explicit `UNVERIFIED:` prefix.

Stays silent on a diagnosis inside a fence, a double-quoted span, a backtick
span, a markdown blockquote, a hypothetical ("if it's a zombie, ..."), and
past-tense narration of an old incident ("the task was a zombie").

Mechanical half of `corpus/skills/cat-mode/SKILL.md`'s Verify rule:
"Unhedged root-cause or fix claims about live system behavior need
instrument-level proof in the same message, or `UNVERIFIED:`." Four
independent conditions must hold before it blocks, because a Stop hook's
effective false-positive rate is what decides whether anyone keeps it on
(Sadowski et al., "Lessons from Building Static Analysis Tools at Google,"
CACM 61(4), 2018).

`diu-stop` has a narrower causal closer of its own ("the cause is",
"because"). It stays silent on the copula shape, and its paragraph check
skips any paragraph containing an inline backtick, so it is not the lever
for this class.

No `agent_id` guard: `auto-pr` and `frustration-watchdog` carry one because
they act on the whole session's behalf, which a subagent must not do. This
hook only blocks the offending reply and tells that same agent to go get
evidence -- as correct inside a subagent as outside it.

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
- `tests/fixtures/diagnosis_{fires,silent}.json` -- unhedged diagnosis
  claims, including the same claim shipped with its process table.
- `tests/test_hooks.py`

Tests: `python3 -m unittest discover -s engine/hooks/hedge-runs-prove-it/tests -v`
