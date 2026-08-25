# Contributing

catstack is a personal skill stack. Portable skills and hooks are welcome; project-specific Invoker/NiceSpeak rules belong in those repos.

## Add a skill

1. Put a standard `SKILL.md` under `product/skills/<name>/` or `corpus/skills/<name>/`.
2. Keep it agent-agnostic unless it truly cannot run elsewhere. Claude-only skills go in `CLAUDE_ONLY_SKILLS` in `install.sh`.
3. If it came from another repo, add a sourcing note in [docs/provenance.md](docs/provenance.md).
4. Run `./install.sh` so the skill lands in **Claude, Cursor, and Codex**. Do not hand-link a single harness.

### Invariants (assert)

- Every new skill MUST apply to Claude, Cursor, and Codex unless it is listed in `CLAUDE_ONLY_SKILLS`.
- `./install.sh` MUST remain the install path for portable skills. Manual `ln -s` into only `~/.cursor/skills` or only `~/.claude/skills` is a bug.
- Project-skill home links (outside this repo) MUST use `scripts/link_skill_three_harnesses.sh` (or equivalent links into all three roots).
- Follow `engine/skills/create-skill/SKILL.md` — not Cursor built-in create-skill text that only mentions `~/.cursor/skills/`.

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

Three-harness skill install gate:

```bash
python3 scripts/check_skills_three_harnesses.py
python3 scripts/check_skills_three_harnesses.py --home   # live personal roots
```

`./install.sh` is safe to rerun. It will not clobber a real (non-symlink) file without `--force`.
