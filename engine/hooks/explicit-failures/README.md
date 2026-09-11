# explicit-failures

PreToolUse hook (Edit|Write|MultiEdit|Bash heredocs): scan the code an agent
is about to write for silent-failure shapes and hand back one advisory line
per hit. Never blocks: exit 0, findings go to the agent as
`additionalContext` and to stderr. This is the mechanical catch for
`corpus/skills/principle-explicit-errors`; a prose principle is only as
effective as the check that fires when it is broken.

Always on. There is no switch to turn it off; it only ever adds advisory lines.

## Shapes

Python (`.py`):

- `except ...:` whose body ends in `pass`, `continue`, `break`, or a bare /
  `None` / `[]` / `{}` return, with nothing in the block that says the
  failure happened.
- `if not x:` / `if x is None:` / `if x == None:` / `if len(x) == 0:` whose
  last statement is `continue`, `break`, or such a return, same condition.

JS/TS (`.js .jsx .ts .tsx .mjs .cjs .vue .svelte`):

- `catch {}` / `catch (e) {}` with an empty or comment-only body, or a body
  that only `continue`s / `break`s / returns bare.
- `.catch(() => {})`, `.catch(e => null)`, `.catch(function () {})`.
- `if (!x)` / `if (x == null)` / `if (x === undefined)` / `if (x.length === 0)`
  whose only statement is `continue`, `break`, or a bare / `null` / `[]` return.

Bash: every heredoc body in the command is scanned; the redirect target
(`cat > build.py <<'EOF'`) picks the grammar, a heredoc with no target
(`python3 - <<EOF`) runs both.

A hit is suppressed when the block contains any of `log`, `raise`, `throw`,
`warn`, `print(`, `status`, or `reason` (so a status row or a log line with
context already satisfies it), or when the substring `explicit-failures`
appears on the header line, the line before it, or inside the block:
`# explicit-failures: allow`, `# pragma: explicit-failures: allow`,
`// eslint-disable-next-line explicit-failures`.

Output, one line per hit:

```text
build.py:4: `if not lots[t]:` guard that only continues — explicit-failures: raise, log with context, or emit a status row (principle-explicit-errors)
```

Line numbers count from the top of the content being written: the file for
Write and heredocs, the replacement fragment for Edit / MultiEdit.

## Tests

`tests/fixtures/` holds one `<shape>_fires.*` / `<shape>_silent.*` pair per
shape, plus `hidden_stock_build_lots_{fires,silent}.py`: the vendored
`build_lots_and_realized` body whose bare `continue` dropped every sell with
no cost lot, and the fixed body that ships the row with
`cost_basis_status=unknown` and a reason. The test suite runs the hook on
every fixture and asserts fires vs silence, plus the off-by-default, marker,
advisory-exit-0, and fail-open paths.

```sh
python3 -m unittest discover -s engine/hooks/explicit-failures/tests -v
python3 scripts/check_hook_test_coverage.py engine/hooks/explicit-failures
```

Claude-only for now (`claude.hook.json`, merged by
`install_claude_hook.py`); Cursor and Codex have no equivalent PreToolUse
content payload wired in this repo.
