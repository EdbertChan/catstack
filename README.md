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
- `principle-*` (14 skills) — cherry-picked from the `pstack` plugin in [cursor/plugins](https://github.com/cursor/plugins/tree/63d938c2e4a165a0fec1bd0f61a8e325f0cb751e/pstack) (commit `63d938c`), by Lauren Tan. Each one is a short, narrowly-triggered engineering rule. Selected after backtesting all 21 `pstack` principles against real Invoker/smithers/catalyst/etc. transcript history — these 14 either matched a proven-good habit or a real, verified past failure; the other 7 (`prove-it-works` — redundant with `invoker-prove-it`/`process-guard` — plus 6 more still under review) were left out for now:
  - `outcome-oriented-execution`, `foundational-thinking`, `type-system-discipline` — each tied to a real, verified production bug
  - `laziness-protocol`, `fix-root-causes`, `separate-before-serializing-shared-state`, `sequence-verifiable-units`, `build-the-lever`, `encode-lessons-in-structure`, `never-block-on-the-human`, `experience-first` — already an established habit in practice
  - `subtract-before-you-add`, `minimize-reader-load`, `guard-the-context-window` — mixed evidence, kept as a guardrail

  This was a manual cherry-pick, not a `git subtree` — there's no single upstream prefix that maps to "these 14 skills," so there's nothing to `subtree pull`. To refresh one, re-copy `pstack/skills/<name>/SKILL.md` from the source repo above at whatever commit is current.
- `reflect` — mines a conversation transcript for durable learnings and routes them into skill edits, gated on explicit user approval before anything is touched. Adapted from `pstack`'s `reflect`, rewritten for Claude Code (its own transcript layout, the `Agent` tool for review fan-out, no dependency on Cursor's `create-skill`). Claude-only — `install.sh` skips it for Cursor/Codex.
- `diu` — communication-brevity rule (ELI5 under 40 words unless the user asked for depth), extracted verbatim from `invoker-diu` in the Invoker repo's own skill set. Zero Invoker-specific content, was just filed under the wrong prefix.
- `land-stack` — SHA-verified PR-stack landing (never resolve the PR to merge by branch name). Generalized from `invoker-land-stack`: kept the discipline, stripped the Invoker-specific guard script path since that script doesn't exist outside that repo.

  The rest of the `invoker-*` skills (`invoker-remote-ci-verify`, `invoker-workflow-chain-submit`, `invoker-invoker-ops`, `invoker-invoker-setup`, `invoker-loop-generator`, `invoker-plan-to-invoker`, `invoker-visual-proof`) hard-depend on Invoker's own scripts, CLI, database, or YAML schema — correctly stay project-scoped, not catstack candidates. `invoker-prove-it` is redundant with `process-guard`. `invoker-admin-bypass-sweep` is a separate, real gap: it exists only as a local `~/.claude/skills` copy with no matching file anywhere in the Invoker repo — it needs to be committed into `Invoker/skills/`, not here (catstack is for portable skills; that one is Invoker-specific and dangerous by design).
