# Contributing

catstack is a personal skill stack. Portable skills and hooks are welcome; project-specific Invoker/NiceSpeak rules belong in those repos.

## Add a skill

1. Put a standard `SKILL.md` package under `skills/<name>/`.
2. Keep it agent-agnostic unless it truly cannot run elsewhere. Claude-only skills go in `CLAUDE_ONLY_SKILLS` in `install.sh`.
3. If it came from another repo, add a sourcing note in [docs/provenance.md](docs/provenance.md).

## Test

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s skills/reflect/scripts/tests -v
python3 -m unittest discover -s hooks/diu-stop/tests -v
python3 -m unittest discover -s hooks/reflect-on-thrash/tests -v
python3 -m unittest discover -s hooks/restart-risk-check/tests -v
```

`./install.sh` is safe to rerun. It will not clobber a real (non-symlink) file without `--force`.
