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

- Skill markdown MUST NOT reference files that do not exist in this repo or
  in that skill package (except allowlisted consumer/runtime contract paths
  such as `.cursor/judge-swarm-bindings.json`). Enforced by
  `scripts/check_skill_file_refs.py`.
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
- A new skill MUST ship a `tests/` dir before it's added. Code skills (a
  `scripts/` dir or any `.py`/`.mjs`/`.js`/`.ts`/`.sh` file) need at least
  two real test functions. Prose-only skills need a positive fixture and a
  negative fixture (e.g. `tests/fires_*.md` / `tests/stays_silent_*.md`)
  showing a prompt that should, and one that should not, invoke the skill.
  Enforced by `scripts/check_skill_test_coverage.py`. A skill predating this
  rule is grandfathered in `scripts/skill_test_debt_allowlist.txt`, which is
  shrink-only (`scripts/check_skill_test_debt_no_growth.py`) — never add a
  new skill to it instead of writing its tests.

## Preferred path (catstack / portable)

1. Create `product/skills/<name>/SKILL.md` (portable) or `corpus/skills/<name>/SKILL.md` (mined lesson).
2. Write its `tests/` dir (positive + negative — see the test-coverage invariant above).
3. Run `./install.sh` from the catstack repo root.
4. Verify:

```bash
python3 scripts/check_skill_test_coverage.py
python3 scripts/check_skills_three_harnesses.py
ls -la ~/.claude/skills/<name> ~/.cursor/skills/<name> ~/.codex/skills/<name>
```

## Domain sections (optional, product skills)

Portable product skills MAY add task-type files under `domains/` next to
`SKILL.md`. Install already symlinks the whole skill directory, so those
files travel for free. There is no separate top-level domains package
under `product/` (domains live inside each skill directory).

```text
product/skills/<name>/
  SKILL.md              # generic invariants + domain selector
  domains/
    coding.md           # optional: software / PR / CI bindings
    equities.md         # optional: holdings / claim-research bindings
```

Types start as `coding` and `equities`. Add a new type only when a real
skill needs it.

### Selector (MUST paste into every domain-aware `SKILL.md`)

After reading `SKILL.md`, read **at most one** sibling `domains/<type>.md`:

1. User named the type (`coding`, `equities`, holdings, claim research).
2. Else cwd has `.cursor/judge-swarm-bindings.json`, or equities trigger
   words (holdings, Sheets, research report) → `equities`; Invoker /
   catstack / `package.json` without those → `coding`.
3. Else none. Do not read both in one turn.

### Invariants (assert)

- Generic `SKILL.md` MUST NOT name consumer CLIs, absolute paths, or
  scripts that are not in this catstack skill tree.
- Domain files MUST NOT restate the generic sequence — only triggers,
  consumer binding lookup rules, and do-nots.
- Domain bindings are loaded from a **consumer** file under cwd (for
  equities: `.cursor/judge-swarm-bindings.json`). If missing, fail closed.
- Named paths in skill markdown MUST exist in catstack (or the skill
  package), except allowlisted consumer contracts — see
  `scripts/check_skill_file_refs.py`.
- Project CLIs that only exist in one repo stay project skills (home-link
  with `scripts/link_skill_three_harnesses.sh`), not catstack domains.

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
