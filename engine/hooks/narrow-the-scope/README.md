# narrow-the-scope (hook)

PostToolUse (Edit|Write|MultiEdit|NotebookEdit|StrReplace|Bash): count edits
per file in session state; a verification-shaped Bash command (pytest,
unittest, npm test, jest, vitest, tsc, eslint, ruff, mypy, `check_*.py`,
`run_all_tests`, cargo/go test, `bash <name>test.sh`, `docker build`, ...)
resets every count. When a file reaches three edits with no reset, inject the
`narrow-the-scope` reminder once for that streak episode. Inject-only, never
blocks, fail-open.

A Bash command that names the basename of a file in the current streak also
clears that one file's count: running the script you just edited is how shell
and container work gets verified, and `VERIFY_RE` cannot enumerate every
project's entry point. Precision matters more than recall here — a detector
that cries wolf trains the reader to skip it (Kim & Ernst, "Which warnings
should I fix first?", ESEC/FSE 2007,
https://dl.acm.org/doi/10.1145/1287624.1287633). `tests/fixtures/shell_verified_streak_2026-09-11.json`
is the verbatim sequence from a session where this hook fired four times and
was wrong all four.

Mechanical half of `product/skills/narrow-the-scope`, whose trigger text is
"three or more edits to the same file without a passing test/build/lint run
in between". Before this hook the skill asked the model to notice that and
hand-run `token_audit.py`.

Fixture: `tests/fixtures/real_edit_streak_2026-09-01.json` is the verbatim
tool sequence of a real Invoker session (six edits to `slack-surface.ts`,
no check between). The hook fires at the third edit and stays silent when
the same sequence is interleaved with a test run.

Tests: `python3 -m unittest discover -s engine/hooks/narrow-the-scope/tests -v`
