# skill-usage-log

Reports one finding each time an agent uses a skill in Claude, Cursor, or
Codex. The shared hook runtime applies the registry mode, renders any response,
and writes one metrics row per finding. Its registry mode is `off`, so it does
not speak to the agent by default.

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
`$CATSTACK_HOOK_METRICS_DIR`), as `catstack.hook_event.v1` rows. Each detected
use carries a stable rule id for its source (`skill-tool`, `read`,
`shell-read`, `slash`, or `mention`) and a hash of the skill name as its
subject.

## Fail direction

Open: runtime or detector errors do not block the tool call or prompt. A skill
folder that exists but cannot be listed raises an explicit hook error; a folder
that does not exist means no skills are installed there.

## Mode override

`CATSTACK_HOOK_MODE_SKILL_USAGE_LOG=warn` makes detected uses visible as
warnings on one machine. The central registry remains the default source of
the hook's mode.

## Tests

```sh
python3 -m unittest discover -s engine/hooks/skill-usage-log/tests
```
