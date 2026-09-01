# narrow-the-scope (hook)

PostToolUse (Edit|Write|MultiEdit|NotebookEdit|StrReplace|Bash): count edits
per file in session state; a verification-shaped Bash command (pytest,
unittest, npm test, jest, vitest, tsc, eslint, ruff, mypy, `check_*.py`,
`run_all_tests`, cargo/go test, ...) resets every count. When a file reaches
three edits with no reset, inject the `narrow-the-scope` reminder once for
that streak episode. Inject-only, never blocks, fail-open.

Mechanical half of `product/skills/narrow-the-scope`, whose trigger text is
"three or more edits to the same file without a passing test/build/lint run
in between". Before this hook the skill asked the model to notice that and
hand-run `token_audit.py`.

Fixture: `tests/fixtures/real_edit_streak_2026-09-01.json` is the verbatim
tool sequence of a real Invoker session (six edits to `slack-surface.ts`,
no check between). The hook fires at the third edit and stays silent when
the same sequence is interleaved with a test run.

Tests: `python3 -m unittest discover -s engine/hooks/narrow-the-scope/tests -v`
