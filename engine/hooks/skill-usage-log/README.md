# skill-usage-log

Records one metrics row each time an agent uses a skill, in Claude, Cursor and
Codex. It never speaks to the agent.

## Fires on

| Harness | Event | Counted as |
| --- | --- | --- |
| Claude | `PreToolUse` (`Skill`, `Read`, `Bash`) | `skill_tool` for a Skill call, `read` for a Read of a `SKILL.md`, `shell_read` for `cat`/`sed`/`head`/`tail`/`nl`/`less`/`more`/`bat` on one |
| Claude | `UserPromptSubmit` | `slash` for a prompt that starts with `/<installed skill>` |
| Cursor | `preToolUse` | `read` / `shell_read` as above, including `skills-cursor/` |
| Cursor | `beforeSubmitPrompt` | `slash` |
| Codex | `PreToolUse` | `shell_read`, including a path inside an `exec` code string |
| Codex | `UserPromptSubmit` | `slash`, and `mention` for each `$<installed skill>` |

## Silent on

A `SKILL.md` path that only appears inside a Write, Edit, StrReplace, Task,
Agent, Glob, Grep, search or fetch call; a URL; `rg`, `grep` or `wc` over
skill files; a `/path` or `/word` that is not an installed skill; a skill
named mid-sentence.

## Where rows go

`~/.cache/catstack-hook-metrics/events-<date>.jsonl` (or
`$CATSTACK_HOOK_METRICS_DIR`), as `catstack.hook_event.v1` rows with
`action: skill_used`, `reason: <source>` and `skill: <name>`. Read them with:

```sh
python3 engine/hooks/_runner/report.py --skills --since 7d
```

Every installed skill with no use in the window prints `no record`.

## Fail direction

Open: the hook never blocks or changes a tool call or prompt. Input it cannot
read writes a `skill_usage_unchecked` row and a `catstack-hook-error` line,
so the run counts as `caught_error` and `report.py --skills` exits 2. A skill
folder that exists but cannot be listed marks typed commands unchecked; a
folder that does not exist means no skills are installed there.

## Escape hatch

`CATSTACK_SKILL_USAGE_LOG=0` turns recording off.

## Tests

```sh
python3 engine/hooks/skill-usage-log/tests/test_hooks.py
```
