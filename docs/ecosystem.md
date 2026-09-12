# Catstack ecosystem: engine, corpus, product

Catstack is a **self-improving skill stack**: transcripts feed a mine→apply→PR loop; humans land PRs; `./install.sh` refreshes live agent roots.

```mermaid
flowchart TB
  transcripts[Transcripts] --> engine
  subgraph engine [engine]
    hooks[hooks]
    reflect[reflect_session-mine]
    author[create-skill_draft-pr_make-pr]
    automate[automate-me]
    gates[scripts_CI_always-on]
  end
  subgraph corpus [corpus]
    principles[principle_skills]
    personal[cat-mode]
    mined[other_mined_SKILL_edits]
  end
  subgraph product [product]
    portable[diu_land-stack_visual-proof_etc]
  end
  reflect -->|Accepted_skill_prose| corpus
  reflect -->|hook_over_prose| hooks
  automate -->|handle-mode| personal
  install["./install.sh"] --> engine
  install --> corpus
  install --> product
  install --> home["~/.claude_cursor_codex"]
```

## Buckets

| Bucket | Path | Owns |
| --- | --- | --- |
| **engine** | `engine/` | Mine loop, hooks, PR/authoring skills, CI/scripts, always-on rules |
| **corpus** | `corpus/skills/` | Mined lessons and personal mode skills (engine *outputs*) |
| **product** | `product/skills/` | Human-authored portable workflows |
| **external** | outside this repo | Invoker-scoped helpers, other project skills |

Live agents still see flat `~/.claude/skills/<name>` etc. Install flattens the three roots.

## Engine-only mode

`./install.sh --engine-only` installs the engine bucket alone plus the four
product gates the engine prose cites (`diu`, `visual-proof`, `split-scope`,
`narrow-the-scope`, named in `ENGINE_CORE_PRODUCT_SKILLS` in `install.sh`).
It prunes every other corpus and product symlink from the harness skill
folders and links `~/.claude/CLAUDE.md` to `engine/CLAUDE.core.md` instead of
the root file, so `corpus/CLAUDE.learned.md` is not loaded, and it removes
the generated `~/.cursor/rules/session-hygiene.mdc` mirror of that file's
Session hygiene section. Corpus stays in git and keeps receiving `reflect`
and `automate-me` output; a plain `./install.sh` links and generates it all
again.

## Inventory

### engine (`engine/skills/`, `engine/hooks/`, …)

| Name | Kind |
| --- | --- |
| `reflect` | skill — mine transcripts; session-mine; DORA |
| `automate-me` | skill — produce `<handle>-mode` into corpus |
| `create-skill` | skill — author/install; three-harness |
| `draft-pr` | skill — PR schema |
| `make-pr` | skill — catstack PR overlay + gates |
| `thrash-reflect-automate` | skill — FAIL → reflect → automate |
| `auto-pr` | hook |
| `bug-complaint-leak` | hook |
| `publish-act-guard` | hook |
| `categorical-scope-guard` | hook (PreToolUse on `Bash`; blocks a status-narrowed mutation when the live turn said all/every/each) |
| `cat-mode-default` | hook (UserPromptSubmit + PreToolUse on `Agent`; applies `cat-mode` on work turns and subagent prompts when `CATSTACK_CAT_MODE_DEFAULT=1`) |
| `demo-freeze` | hook |
| `explicit-failures` | hook (advisory; always on) |
| `external-claim-gate` | hook (PreToolUse on `Bash`; blocks a gh issue/comment/release/api write whose body claims a cause or fix with no evidence; blocks as UNCHECKED when the body cannot be read) |
| `playbook-router` | hook (UserPromptSubmit; injects the steps of the one playbook a prompt names) |
| `diu-stop` | hook (Stop; blocks a reply over the word limit or with an unproven claim, and asks the background judge whether the reply used wording from its `phrases/` lists, waiting for that answer so a hit blocks the same turn) |
| `frustration-watchdog` | hook |
| `named-verb-guard` | hook |
| `plan-discipline` | hook (not always installed) |
| `pr-schema-gate` | hook (advisory; PreToolUse on shell tools; checks direct PR text writes with the repo's own `scripts/validate-pr-body.mjs` and reminds about the stack follow-up; never blocks) |
| `reflect-on-thrash` | hook |
| `restart-risk-check` | hook |
| `restated-constraint` | hook |
| `repeat-error-stop` | hook (blocks blind repeated failures; nudges when one signature survives edit epochs) |
| `wait-needs-wakeup` | hook |
| `hedge-runs-prove-it` | hook |
| `new-file-callout` | hook |
| `agent-relay-attribution` | hook (advisory) |
| `scratchpad-collision` | hook |
| `ui-input-guard` | hook |
| `handoff-needs-smoke-test` | hook |
| `hook-freshness` | hook (advisory) |
| `llm-judge` | hook (shared background model judge; its inbox delivers finished verdicts on the next turn: Claude `UserPromptSubmit`, Cursor `stop`, Codex `notify`) |
| `engine/CLAUDE.core.md` | global hand-written Claude rules |
| `scripts/`, `always-on/`, `cursor/rules/` (repo root), root `install.sh` | runtime (engine-owned entrypoints at root for CI) |

### corpus (`corpus/skills/`)

Global rules mined by reflect are stored in `corpus/CLAUDE.learned.md`.
Claude loads it through `CLAUDE.md`; Cursor cannot, so `install.sh` runs
`install_cursor_session_hygiene.py` to generate `~/.cursor/rules/session-hygiene.mdc`
(`alwaysApply: true`) from that file's Session hygiene section on every
full install.

| Name | Kind |
| --- | --- |
| `cat-mode` | personal mode (automate-me output) |
| `principle-assert-invariants-not-last-bug` | mined principle |
| `principle-bind-to-named-inventory` | mined principle |
| `principle-build-the-lever` | mined principle |
| `principle-encode-lessons-in-structure` | mined principle |
| `principle-experience-first` | mined principle |
| `principle-fix-root-causes` | mined principle |
| `principle-flag-your-own-corrections` | mined principle |
| `principle-foundational-thinking` | mined principle |
| `principle-generalize-from-rejection` | mined principle |
| `principle-guard-the-context-window` | mined principle |
| `principle-laziness-protocol` | mined principle |
| `principle-manage-idle-resumption` | mined principle |
| `principle-minimize-reader-load` | mined principle |
| `principle-name-the-scorer` | mined principle |
| `principle-never-block-on-the-human` | mined principle |
| `principle-outcome-oriented-execution` | mined principle |
| `principle-scope-the-session` | mined principle |
| `principle-separate-before-serializing-shared-state` | mined principle |
| `principle-sequence-verifiable-units` | mined principle |
| `principle-subtract-before-you-add` | mined principle |
| `principle-type-system-discipline` | mined principle |

### product (`product/skills/`)

| Name | Kind |
| --- | --- |
| `diu` | portable brevity |
| `land-stack` | land stacked PRs |
| `loop-generator` | loop workflows |
| `ship-a-detector` | hook/gate detector authoring playbook |
| `split-scope` | PR slice shaping |
| `visual-proof` | UI proof |
| `show-me-your-work` | decision log |
| `independent-judge-swarm` | independent judges + mechanical precheck (domain-aware) |
| `narrow-the-scope` | Claude-only scoping |
| `i-have-adhd` | imported subtree (structure rules now mostly in `diu`) |

### Domain sections (inside a product skill)

Some product skills keep a **generic** `SKILL.md` and optional task-type
files under `domains/`:

```text
product/skills/<name>/
  SKILL.md
  domains/
    coding.md
    equities.md
```

The agent reads `SKILL.md`, then **at most one** `domains/<type>.md`
(user words → cwd heuristics → none). Generic prose must not name repo
CLIs; domain files only add triggers and cwd filename lookups. Types
start as `coding` and `equities`. Enforced by
`scripts/check_ecosystem_boundaries.py`. See
`engine/skills/create-skill/SKILL.md`.

### external

| Name | Where |
| --- | --- |
| `invoker-*` | Invoker checkout / home skills |
| `wipe-bad-pr` | project skill (three-harness home link) |

## Contracts

1. Reflect Accepted **skill prose** applies in whichever repo already owns the named skill. Catstack-owned skills (engine/corpus/product) and personal mode (`automate-me` output) write only under `corpus/skills/` — that never changes. A skill owned by another checkout applies there instead, in a worktree of that owning checkout.
2. Reflect may add **hooks** under `engine/hooks/` when the fix hierarchy prefers hook/test over prose (catstack-only; hooks are not skill prose).
3. `automate-me` writes `corpus/skills/<handle>-mode/`.
4. `create-skill`: new portable tools → `product/skills/`; mined lessons → `corpus/skills/`.
5. Engine runtime must not import corpus/product packages (hooks → reflect scripts only, engine-internal).
6. `[auto]` / make-pr review unit follows path: `engine-*` | `corpus-lesson` | `product-skill` | external-owning-repo.
7. Never auto-merge; human land + `./install.sh` refresh. External apply is never-merge in the owning checkout only — same gate, different repo. `engine/skills/reflect` itself is never copied into another repo.

## Subagent inheritance

A subagent launched through the Agent tool runs under the same
`~/.claude/settings.json` but on different events. Every hook that wires
`Stop` also fires on `SubagentStop`: `install.sh` runs
[`scripts/mirror_stop_hooks_to_subagent_stop.py`](../scripts/mirror_stop_hooks_to_subagent_stop.py),
which mirrors each `engine/hooks/<name>/claude*.hook.json` `Stop` entry, and a
hook opts out only in its own manifest with
`"subagent_stop": {"inherit": false, "reason": "..."}` (today:
`frustration-watchdog`, which reads the human's last message, `auto-pr`,
whose PR instruction is for the session owner, and `unverified-tag-ledger`,
whose ledger is keyed by session id and whose reminder needs a next user
prompt). Under `SubagentStop`,
`transcript_path` is the parent's transcript and `agent_transcript_path` is
the subagent's own, so transcript-reading hooks prefer the latter.
`UserPromptSubmit` hooks never reach a subagent, because its prompt arrives
as the Agent tool's input, not as a user prompt: anything a subagent must see
rides on that input through a `PreToolUse` hook matched on `Agent`
(`cat-mode-default` does this with `hookSpecificOutput.updatedInput`).

## Enforcement

Bazel is **not** used. Boundaries are enforced by directory layout plus CI:

- [`scripts/check_ecosystem_boundaries.py`](../scripts/check_ecosystem_boundaries.py) — allowlists, no flat `skills/`, no engine→corpus/product imports, domain selector / CLI ownership.
- [`scripts/check_skill_file_refs.py`](../scripts/check_skill_file_refs.py) — skill markdown must not name repo/skill paths that do not exist (consumer contract paths allowlisted).

See those scripts for the mechanical rules.
