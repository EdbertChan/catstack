---
name: create-skill
description: >-
  Create or install an agent skill for Claude, Cursor, and Codex together.
  Use when authoring a new skill, adding SKILL.md, home-linking a project
  skill, or when the user says create-skill / install a skill. Overrides
  single-harness Cursor-only install advice.
---

# Creating skills (Claude + Cursor + Codex)

## Invariants (assert)

- A new skill MUST be available to **Claude, Cursor, and Codex** — never only
  the harness the agent happens to be running in.
- Prefer putting portable skills under `product/skills/<name>/` (or mined
  lessons under `corpus/skills/<name>/`) and running `./install.sh`. That is
  the only path that keeps all three harness roots in sync automatically.
  See [docs/ecosystem.md](../../docs/ecosystem.md). Engine skills
  (`reflect`, `create-skill`, …) live under `engine/skills/` only.
- Claude-only skills MUST be listed in `CLAUDE_ONLY_SKILLS` in `install.sh`
  (and nowhere else). Everything not listed MUST install to all three.
- When home-linking a **project** skill (repo `.cursor/skills/<name>` that is
  not in catstack), you MUST symlink the same source into all three personal
  skill roots in one step — never Claude+Cursor only.

## Preferred path (catstack / portable)

1. Create `product/skills/<name>/SKILL.md` (portable) or `corpus/skills/<name>/SKILL.md` (mined lesson).
2. Run `./install.sh` from the catstack repo root.
3. Verify:

```bash
python3 scripts/check_skills_three_harnesses.py
ls -la ~/.claude/skills/<name> ~/.cursor/skills/<name> ~/.codex/skills/<name>
```

## Project-skill home link (all three)

If the skill must live in a project (e.g. `.cursor/skills/wipe-bad-pr`):

```bash
bash scripts/link_skill_three_harnesses.sh /absolute/path/to/skill-dir
```

Or manually, same source for each:

```bash
src=/absolute/path/to/skill-dir
name=$(basename "$src")
ln -sfn "$src" "$HOME/.claude/skills/$name"
ln -sfn "$src" "$HOME/.cursor/skills/$name"
ln -sfn "$src" "$HOME/.codex/skills/$name"
```

Then run:

```bash
python3 /path/to/catstack/scripts/check_skills_three_harnesses.py --home
```

## Do not

- Follow Cursor built-in create-skill text that only mentions `~/.cursor/skills/`.
- `ln -s` into one or two harness roots and call it done.
- Invent a one-off install path that bypasses `install.sh` / the link script.
