# Contributing

catstack is a personal skill stack. Portable skills and hooks are welcome; project-specific Invoker/NiceSpeak rules belong in those repos.

## Add a skill

1. Put a standard `SKILL.md` package under `skills/<name>/`.
2. Keep it agent-agnostic unless it truly cannot run elsewhere. Claude-only skills go in `CLAUDE_ONLY_SKILLS` in `install.sh`.
3. If it came from another repo, add a sourcing note in [docs/provenance.md](docs/provenance.md).

## Test

```bash
bash scripts/run_all_tests.sh
```

Discovers and runs every `tests/` dir in the repo -- add a new hook or skill's `tests/` dir and it's picked up automatically, no edit needed here or in CI.

If your hook has a `detect.py` (i.e. it decides whether to catch something), it also needs a positive test (proves the detector fires on the bad case) and a negative test (proves it stays silent on a clean case). Check with:

```bash
python3 scripts/check_hook_test_coverage.py
```

`./install.sh` is safe to rerun. It will not clobber a real (non-symlink) file without `--force`.
