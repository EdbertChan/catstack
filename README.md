# catstack

A personal collection of Claude Code skills, consolidated from various project repos so they have one canonical home.

## Layout

Each skill lives under `skills/<name>/` as a standard `SKILL.md` package.

## Skills

- `i-have-adhd` — the `skills/i-have-adhd/` subtree of [EdbertChan/i-have-adhd](https://github.com/EdbertChan/i-have-adhd) (a fork of [ayghri/i-have-adhd](https://github.com/ayghri/i-have-adhd)), pulled in via `git subtree`. The upstream repo has extra tooling (hooks, tests, extensions) outside this one skill folder, so a plain `subtree add`/`pull` against its root would drag all of that in too — updates instead go through a two-step split:
  ```sh
  # 1. re-clone the fork and extract just the skill folder's history into a branch
  git clone https://github.com/EdbertChan/i-have-adhd /tmp/i-have-adhd-src
  git -C /tmp/i-have-adhd-src subtree split --prefix=skills/i-have-adhd -b extracted

  # 2. pull that branch into catstack as a subtree update
  git subtree pull --prefix=skills/i-have-adhd /tmp/i-have-adhd-src extracted --squash
  ```
- `draft-pr`, `split-scope` — generic PR-drafting and diff-splitting skills, copied from [DrafterSkill](https://github.com/Neko-Catpital-Labs/DrafterSkill) (`packages/skill/skills/`), current as of commit `d4bb326`. The `invoker-make-pr` and `invoker-review-compression` skills used in the Invoker repo are project-specific forks of these two.
