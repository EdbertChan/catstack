# bound-tool-result

PreToolUse rewrite for native shell tools: every recognized shell command
runs through
`corpus/skills/principle-guard-the-context-window/scripts/capture_tool_result.py`
so the parent harness never receives more than **16KiB** of combined
stdout/stderr body. Full bytes stay on disk. Relevance is chosen by a
fresh subagent, never by this hook or the helper.

Owned by `principle-guard-the-context-window`. This is the tool-boundary
half of that skill's file-then-parse rule.

## Fires on

| Harness | Event | Matcher | Entrypoint |
| --- | --- | --- | --- |
| Claude | `PreToolUse` | `Bash` | `claude_pre_tool_use.py` |
| Cursor | `preToolUse` | `*` (detect filters shell) | `cursor_pre_tool_use.py` |
| Codex | `PreToolUse` | `Bash` | `codex_pre_tool_use.py` |

Outcomes:

- **rewrite** — wrap the command; Claude returns `updatedInput`, Cursor
  `updated_input`, and Codex returns `hookSpecificOutput.permissionDecision:
  allow` plus nested `updatedInput`.
- **already_wrapped** — leave alone (marker in the command string).
- **deny** — helper missing; refuse the raw command (fail closed).
- **unrelated / unchecked** — non-shell tool, or shell tool with no
  readable command string.

## Silent on

- Edit / Write / Read / MCP / screenshot / hosted tools (named V1 gaps).
- Commands already wrapped through `capture_tool_result.py`.
- Under-cap shell output: the helper still runs, but the stub includes
  the body so `ls` and friends keep working.

## Fail direction

| Read | Direction |
| --- | --- |
| Capture helper path resolution | **closed** — missing helper denies the shell call |
| Non-shell tool classification | **open** — unrelated tools continue unchanged |
| Empty / unreadable shell command on a shell tool | **open** for continue, labeled unchecked (no rewrite) |
| Permission denials from other hooks | unchanged — this hook does not soften them |

## Named coverage gaps (V1)

- MCP tool results
- File `Read` / full-file dumps
- Screenshots and other image/binary tool results
- Hosted / remote tools outside native shell
- Disabled or untrusted hooks (no rewrite runs)
- Interactive stdin / TTY programs that break under `sh -c` wrapping

## Escape hatch

Set `CATSTACK_CAPTURE_HELPER` to an absolute path of
`capture_tool_result.py`. Set `CATSTACK_TOOL_CAPTURE_ROOT` to choose the
artifact directory (default: `$TMPDIR/catstack-tool-captures`). To
disable, remove the hook entry from the harness settings (there is no
"run raw" bypass while the hook is installed — that is intentional).

## Live intercept proof

```sh
python3 engine/hooks/bound-tool-result/tests/live_intercept_proof.py
```

Asserts each adapter rewrites a deterministic large producer, the
parent-visible capture stub is ≤16KiB, and the stub contains no payload
body. Adapter unit tests alone are not this proof.
