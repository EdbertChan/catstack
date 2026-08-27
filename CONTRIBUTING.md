# Contributing

catstack is a personal skill stack. Portable skills and hooks are welcome; project-specific Invoker/NiceSpeak rules belong in those repos.

## Add a skill

1. Put a standard `SKILL.md` under `product/skills/<name>/` or `corpus/skills/<name>/`.
2. Keep it agent-agnostic unless it truly cannot run elsewhere. Claude-only skills go in `CLAUDE_ONLY_SKILLS` in `install.sh`.
3. Optional (product only): add task-type files under `domains/` (`coding.md`, `equities.md`). Paste the domain selector from `engine/skills/create-skill/SKILL.md` into `SKILL.md`. Generic prose MUST NOT name repo CLIs; domain files only add triggers and cwd filename lookups.
4. If it came from another repo, add a sourcing note in [docs/provenance.md](docs/provenance.md).
5. Write its `tests/` dir: code skills need at least two real test functions; prose-only skills need a positive fixture and a negative fixture (e.g. `tests/fires_example.md` / `tests/stays_silent_example.md`).
6. Run `./install.sh` so the skill lands in **Claude, Cursor, and Codex**. Do not hand-link a single harness.

### Invariants (assert)

- Every new skill MUST ship a `tests/` dir (positive + negative — see `engine/skills/create-skill/SKILL.md`) before it's added. Checked by `scripts/check_skill_test_coverage.py`; existing untested skills are grandfathered in `scripts/skill_test_debt_allowlist.txt`, which is shrink-only.
- Every new skill MUST apply to Claude, Cursor, and Codex unless it is listed in `CLAUDE_ONLY_SKILLS`.
- `./install.sh` MUST remain the install path for portable skills. Manual `ln -s` into only `~/.cursor/skills` or only `~/.claude/skills` is a bug.
- Project-skill home links (outside this repo) MUST use `scripts/link_skill_three_harnesses.sh` (or equivalent links into all three roots).
- Follow `engine/skills/create-skill/SKILL.md` — not Cursor built-in create-skill text that only mentions `~/.cursor/skills/`.
- Domain-aware product skills MUST include the selector phrase in `SKILL.md` and MUST keep repo CLIs out of the generic file.

## Test

```bash
bash scripts/run_all_tests.sh
```

Discovers and runs every `tests/` dir in the repo -- add a new hook or skill's `tests/` dir and it's picked up automatically, no edit needed here or in CI.

If your hook has a `detect.py` (i.e. it decides whether to catch something), it also needs a positive test (proves the detector fires on the bad case) and a negative test (proves it stays silent on a clean case). Check with:

```bash
python3 scripts/check_hook_test_coverage.py
```

Session-mine / reflect detector scripts need the same positive+negative shape:

```bash
python3 scripts/check_mine_repro_coverage.py
```

Every skill needs its own positive+negative coverage too:

```bash
python3 scripts/check_skill_test_coverage.py
python3 scripts/check_skill_test_debt_no_growth.py   # scripts/skill_test_debt_allowlist.txt is shrink-only
```

Three-harness skill install gate:

```bash
python3 scripts/check_skills_three_harnesses.py
python3 scripts/check_skills_three_harnesses.py --home   # live personal roots
```

`./install.sh` is safe to rerun. It will not clobber a real (non-symlink) file without `--force`.
