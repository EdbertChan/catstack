# text-match-decision-warn

PreToolUse hook: when an agent is about to add code that decides behaviour
by matching human-readable text (an error string, tool or agent output, or
plan/task prose), hand back a warning that says to decide from recorded
state or a structured field instead. Never blocks. Every warning is also
written to a log and counted by the hook metrics runner.

This is the mechanical catch for the cat-mode rule "decide from recorded
state, not text" (`corpus/skills/cat-mode/references/named-constraints.md`).

## What it reads

Only lines the tool call **adds** to a code file:

- `Write`: the new content, minus lines already in the file on disk.
- `Edit` / `MultiEdit` / Cursor `StrReplace` / `edit_file`: the new text,
  minus lines already in the replaced text.
- Codex `apply_patch` (bare or wrapped inside an `exec` script): `+` lines of
  each `*** Add File:` / `*** Update File:` section, minus that section's `-`
  lines.

Code files are `.py`, `.js .jsx .ts .tsx .mjs .cjs .mts .cts`, and
`.sh .bash .zsh`. Everything else (Markdown, YAML, JSON, text, extensionless
scripts) is not scanned.

## Fires on

A subject is a variable, attribute, or literal key whose last name part is
one of these words (snake_case and camelCase are split, so `errorText` and
`error_text` both count):

| Scope | Words |
| --- | --- |
| `error-or-log-text` | error, err, exception, exc, stderr, log, traceback, message, msg, failure, reason |
| `tool-or-agent-output` | stdout, output, reply, response, comment, transcript, body, completion, answer (shell also: out, result) |
| `plan-or-task-prose` | description, prompt, title, summary, instructions |

A subject whose name also contains a structured word (code, class, type,
kind, status, id, name, key, phase, state, path, file, url, count, len,
length, level, json, field, exit, number) is never a subject, so
`error_code.startswith("E1")` and `errorType.includes(x)` stay silent.

| Rule | Shape |
| --- | --- |
| `py-membership` | `"some text" in error`, `"x" not in stderr`, `"timeout" in str(exc)`, `any(sig in error for sig in SIGS)` |
| `py-prefix` | `result.stderr.startswith(...)`, `prompt.lower().endswith(...)` |
| `py-regex` | `re.search(p, proc.stdout)` / `PATTERN.search(comment_body)` on an `if`/`elif`/`while`/`return`/`any(`/ternary line |
| `js-substring` | `errorText.includes(...)`, `stderr?.startsWith(...)`, `String(err).endsWith(...)` |
| `js-regex-test` | `/timed out/i.test(output)`, `FAILURE_RE.test(logText)` |
| `js-match` | `stdout.match(...)`, `reply.indexOf(...) !== -1` on an `if`/`return`/`?`/`&&`/`||` line |
| `sh-grep-herestring` | `if grep -q "..." <<< "$output"` |
| `sh-echo-grep` | `if echo "$out" \| grep -q ...`, `printf ... "$stderr" \| grep ... && ...` |
| `sh-glob-match` | `[[ "$output" == *"ready"* ]]`, `[[ $message =~ fail ]]` |

Python membership with a single-word literal (`"error" in response`) or a
bare name on the left (`key in message`) only fires when the subject is
clearly a string: wrapped in `str()`, normalised with `.lower()` and
friends, named with a string word (stderr, stdout, text, output, log,
traceback, str, line), or inside `any(`/`all(`. That keeps dict key
checks silent.

## Silent on

- Test code: any path under `tests/`, `test/`, `__tests__/`, `e2e/`, `spec/`,
  `fixtures/`, `testdata/`, `repro/`, or a file named `test_*.py`,
  `*_test.py`, `conftest.py`, `*.test.ts` / `*.spec.js` (any JS/TS
  extension), or `test-*` / `repro-*` / `*-test` / `*_test` with a shell or
  JS/TS extension. Tests reading messages are fine.
- Assertion lines anywhere: `assert ...`, `assert(...)`, `assert.x(...)`,
  `expect(...)`, `self.assert*(...)`, `t.true(...)` / `t.is(...)`.
- Comment lines and trailing comments; text inside string literals.
- Equality on a field (`status == "failed"`,
  `execution.get("phase") == "launching"`).
- A parse that is not a decision (`m = re.search(r"exit (\d+)", stderr)`).
- `for line in output.splitlines():` and other loop iteration.
- Plural list names (`"boom" in errors`, `errors.includes(id)`).
- Lines that already existed before this edit.
- Tools that add no file content (`Bash`, `Read`).
- Any line carrying `text-match-decision-warn: allow` (the escape hatch for a
  deliberate parse of a fixed machine format).

## Warning text

```text
text-match-decision-warn: new code decides behaviour by matching human-readable text.
- /repo/worker/repair.py:9 [py-membership; error-or-log-text] `if any(signature in error for signature in _STARTUP_INFRA_SIGNATURES):`
Decide from recorded state or a structured field instead: a status or phase field, a launch-completed timestamp, a typed failure class, a gate state file, `--output json`, API fields, an exit code, or typed plan fields. Rule: cat-mode "decide from recorded state, not text" (corpus/skills/cat-mode/references/named-constraints.md). Advisory only; nothing was blocked. If a line parses a fixed machine format on purpose, put `text-match-decision-warn: allow` on that line.
```

At most 8 hits are listed, then `(+N more in this edit)`. Claude and Codex
get it as `hookSpecificOutput.additionalContext`; Codex also gets a copy on
stderr; Cursor gets `{"permission": "allow", "agent_message": ...}`.

## Logging and metrics

- **Metrics:** installed commands run under `engine/hooks/_runner/run.py`.
  A warning prints to stdout, so the runner row records outcome `spoke`; a
  clean edit records `silent`; a caught error records `caught_error`.
  `python3 engine/hooks/_runner/report.py` shows the per-harness counts.
- **Warning log:** one JSONL row per hit in
  `~/.cache/catstack-hook-metrics/text-match-decision-warn-warnings.jsonl`
  (the directory follows `CATSTACK_HOOK_METRICS_DIR`, like `runs.jsonl`).
  Fields: `ts`, `hook`, `harness`, `session_id`, `tool`, `file_path`,
  `line_no`, `line`, `rule`, `scope`, `baseline` (`absent`, `read`,
  `unreadable`, or `replaced-text`).
- A warning-log write failure prints
  `catstack-hook-error text-match-decision-warn: could not write warning log to <path>: <error>`
  on stderr (the runner records `caught_error`) and the warning is still
  delivered.

## Fail direction

- **Payload:** unreadable stdin, a non-object payload, or a scanner
  exception prints a `catstack-hook-error text-match-decision-warn: ...`
  line and warns about nothing (fails open, recorded as `caught_error`).
- **On-disk baseline for `Write`:** a file that cannot be read, is not
  UTF-8, or is over 2 MB is treated as empty, so every added line is scanned
  and the warning row says `baseline: unreadable` (fails loud: more
  warnings, never fewer).
- **Added content over 1 MB:** not scanned; stderr says
  `text-match-decision-warn: unchecked: <path>: added content is N bytes, over the 1000000-byte scan cap; nothing in it was scanned`.

## Harnesses

| Harness | Event / matcher | Entrypoint |
| --- | --- | --- |
| Claude | `PreToolUse`, `Edit\|Write\|MultiEdit` | `claude_pretooluse.py` |
| Cursor | `preToolUse`, `*` | `cursor_pretooluse.py` |
| Codex | `PreToolUse`, `.*` | `codex_pretooluse.py` |

The Cursor and Codex edit payload field names are read through the aliases
listed in `detect.py` (`target_file`, `code_edit`, `apply_patch` text in any
string field). They have not been confirmed against a live Cursor or Codex
firing; smoke-test after install.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/text-match-decision-warn/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/text-match-decision-warn
```

`tests/fixtures/` holds the backtest pair: `repair_outcome_fires.py` and
`failure_classifier_fires.ts` must warn; `launch_state_silent.py`,
`notes_silent.md`, and `error_message_assert_silent.py` (written to a
`tests/` path) must not. The runner tests run the real `_runner/run.py`
from a fake `~/.claude/hooks` and read back `runs.jsonl`, the warning log,
and `report.py` output.
