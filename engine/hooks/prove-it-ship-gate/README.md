# prove-it-ship-gate

Stop hook: when the outgoing message claims done / shipped / deployed / live
about work with a live side effect (Linear, deploy, production host, webhook,
Slack, external API), the same message must carry evidence a reviewer can
chase (URL, sha, ticket or PR id, fenced output, exit code, PID, timestamp),
or a live command must have run this turn (`ssh`, `curl`, `gh api`,
`gh pr view`, `systemctl`, ...), or the claim must carry the literal prefix
`UNVERIFIED: live path`. Otherwise the turn is blocked (exit 2).

Fixture tests and UI registration do not count. That is the whole point:
Invoker PRs #10553-#10558 shipped cross-repo-research after unit + fixture +
UI only, and the user had to force a live Linear e2e.

Mechanical half of `corpus/skills/prove-it-ship-gate`. Judgment (is this work
really live-side-effect work) stays with the model; the hook only matches
shapes. Fail-open on parse/read errors; `stop_hook_active` skips.

## Files

- `detect.py` -- claim, live-noun, evidence, and live-command patterns; `decide()`.
- `claude_stop_check.py` -- Claude Stop entrypoint.
- `claude.hook.json` / `install_claude_hook.py` -- settings.json merge (idempotent).
- `tests/test_hooks.py` -- fixtures are verbatim messages mined from real
  sessions on 2026-09-01; positive cases fire, negative cases stay silent.

Tests: `python3 -m unittest discover -s engine/hooks/prove-it-ship-gate/tests -v`
