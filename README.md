# catstack

A personal collection of Claude Code skills, consolidated from various project repos so they have one canonical home.

## Layout

Each skill lives under `skills/<name>/` as a standard `SKILL.md` package.

## Skills

- `i-have-adhd` — pulled in via `git subtree` from [EdbertChan/i-have-adhd](https://github.com/EdbertChan/i-have-adhd) (a fork of [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)). To pull upstream updates:
  ```
  git subtree pull --prefix=skills/i-have-adhd https://github.com/EdbertChan/i-have-adhd main --squash
  ```
- `draft-pr`, `split-scope` — generic PR-drafting and diff-splitting skills, copied from [DrafterSkill](https://github.com/EdbertChan/DrafterSkill) (`packages/skill/skills/`). The `invoker-make-pr` and `invoker-review-compression` skills used in the Invoker repo are project-specific forks of these two.
