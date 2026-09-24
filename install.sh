#!/bin/bash
# Symlinks every skill in this repo into Claude, Cursor, and Codex's personal
# skill directories, so they stay live — edit here, pull on another machine,
# and every symlink picks it up immediately. Same command on every machine.
#
# Safe to rerun: skips a name that's already the correct symlink, and refuses
# to clobber a real (non-symlink) directory or file without --force (which
# backs it up, never deletes).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

resolve_main_checkout() {
  local start="$1" common parent
  common="$(git -C "$start" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)" || return 1
  [ -n "$common" ] || return 1
  parent="$(cd "$(dirname "$common")" 2>/dev/null && pwd -P)" || return 1
  [ -f "$parent/install.sh" ] || return 1
  printf '%s' "$parent"
}

warn_if_installing_from_worktree() {
  local main_checkout
  main_checkout="$(resolve_main_checkout "$REPO_DIR")" || return 0
  [ "$main_checkout" != "$(cd "$REPO_DIR" && pwd -P)" ] || return 0
  echo "install.sh: WARNING — installing from a git worktree, not the main checkout."
  echo "  worktree:       $REPO_DIR"
  echo "  main checkout:  $main_checkout"
  echo "  Every link below points into the worktree and dies when the worktree is removed,"
  echo "  leaving those hooks registered but unrunnable. That is intended while you test a"
  echo "  branch; re-run $main_checkout/install.sh when you are done."
}

warn_if_installing_from_worktree

FORCE=0
ENGINE_ONLY=0
WITH_SESSION_MINE=0
WITH_DORA_SNAPSHOT=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --engine-only) ENGINE_ONLY=1 ;;
    --with-session-mine) WITH_SESSION_MINE=1 ;;
    --with-dora-snapshot) WITH_DORA_SNAPSHOT=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--engine-only] [--force] [--with-session-mine] [--with-dora-snapshot]"
      echo "  --engine-only         install engine skills and core product gates only"
      echo "  --force               back up real files before replacing with symlinks"
      echo "  --with-session-mine   install hourly launchd agent (macOS) for session mining"
      echo "  --with-dora-snapshot  install weekly launchd agent (macOS) for DORA charts/PRs"
      exit 0
      ;;
    *)
      echo "unknown flag: $arg (try --help)" >&2
      exit 1
      ;;
  esac
done

CAT_MODE_DEFAULT="$(python3 "$REPO_DIR/engine/hooks/_flags/flags.py" CATSTACK_CAT_MODE_DEFAULT --value --cwd "$REPO_DIR")"
case "$CAT_MODE_DEFAULT" in
  1|true|yes|on) CAT_MODE_DEFAULT=on ;;
  ""|0|false|no|off) CAT_MODE_DEFAULT=off ;;
  decide) ;;
  *)
    echo "install.sh: WARNING — CATSTACK_CAT_MODE_DEFAULT=$CAT_MODE_DEFAULT is not off, decide, or on; treating it as off."
    CAT_MODE_DEFAULT=off
    ;;
esac
if [ -n "${CAT_MODE_AUTO_INVOKE:-}" ] || { [ -f "$REPO_DIR/.env" ] && grep -q '^CAT_MODE_AUTO_INVOKE=' "$REPO_DIR/.env"; }; then
  echo "install.sh: WARNING — CAT_MODE_AUTO_INVOKE is retired and ignored. Use CATSTACK_CAT_MODE_DEFAULT=decide instead."
fi

# Skills written against one agent's specific mechanics (a tool name, a
# transcript path convention) that would be actively wrong to install
# elsewhere verbatim. Everything not listed here is agent-agnostic prose and
# installs everywhere.
CLAUDE_ONLY_SKILLS=(automate-me narrow-the-scope)
# These are gates the engine prose cites (diu-stop hook, draft-pr, automate-me,
# thrash-reflect-automate).
ENGINE_CORE_PRODUCT_SKILLS=(diu visual-proof split-scope narrow-the-scope)

is_claude_only() {
  local name="$1"
  for s in "${CLAUDE_ONLY_SKILLS[@]}"; do
    [ "$s" = "$name" ] && return 0
  done
  return 1
}

# Symlinks $src -> $target, applying the same safe/backup/skip rules
# everywhere: skip if already the right symlink, relink if pointed elsewhere,
# back up (never delete) a real file/dir only with --force.
SKIPPED_ITEMS=""
INSTALLED_LINKS=$'\n'

link_item() {
  local name="$1" src="$2" target="$3"
  INSTALLED_LINKS="${INSTALLED_LINKS}${target}"$'\n'

  if [ -L "$target" ]; then
    if [ "$(readlink "$target")" = "$src" ]; then
      echo "ok      $name (already linked)"
      return
    fi
    echo "relink  $name (was -> $(readlink "$target"))"
    rm "$target"
    ln -s "$src" "$target"
  elif [ -e "$target" ]; then
    if [ "$FORCE" = 1 ]; then
      backup="$target.bak.$(date +%Y%m%d%H%M%S 2>/dev/null || echo backup)"
      echo "backup  $name -> $(basename "$backup"), then linking"
      mv "$target" "$backup"
      ln -s "$src" "$target"
    else
      echo "SKIP    $name (a real file/directory is shadowing the link — rerun with --force to back it up and replace it)"
      SKIPPED_ITEMS="${SKIPPED_ITEMS}${SKIPPED_ITEMS:+, }${name}"
    fi
  else
    echo "link    $name"
    ln -s "$src" "$target"
  fi
}

RUNNER_FILES=(run.py outcome.py doctor.py probe_hook.py)

install_local_runner() {
  local src="$1" target="$2" backup
  mkdir -p "$(dirname "$target")"

  if [ -L "$target" ]; then
    backup="$target.bak.$(date +%Y%m%d%H%M%S 2>/dev/null || echo backup)"
    echo "backup  $(basename "$target") -> $(basename "$backup"), then installing local runner"
    mv "$target" "$backup"
  elif [ -e "$target" ] && [ ! -d "$target" ]; then
    echo "SKIP    local runner (a real file is shadowing $target)"
    SKIPPED_ITEMS="${SKIPPED_ITEMS}${SKIPPED_ITEMS:+, }local runner"
    return
  fi

  mkdir -p "$target"
  local file
  for file in "${RUNNER_FILES[@]}"; do
    cp "$src/$file" "$target/$file"
  done
  printf '%s\n' "$REPO_DIR" > "$target/catstack-source"
  echo "local   runner $target"
}

link_cat_mode() {
  local skill_root="$1" skills_dir="$2"
  local src="$skill_root/cat-mode" target="$skills_dir/cat-mode"

  if [ "$CAT_MODE_DEFAULT" != "decide" ]; then
    if [ -f "$target/.catstack-generated" ] && [ ! -L "$target" ]; then
      echo "remove  cat-mode (generated decide copy; CATSTACK_CAT_MODE_DEFAULT=$CAT_MODE_DEFAULT)"
      rm -rf "$target"
    fi
    link_item "cat-mode" "$src" "$target"
    return
  fi

  if [ -L "$target" ]; then
    rm "$target"
  elif [ -e "$target" ] && [ ! -f "$target/.catstack-generated" ]; then
    if [ "$FORCE" = 1 ]; then
      backup="$target.bak.$(date +%Y%m%d%H%M%S 2>/dev/null || echo backup)"
      echo "backup  cat-mode -> $(basename "$backup"), then generating"
      mv "$target" "$backup"
    else
      echo "skip    cat-mode (real directory already exists — rerun with --force to back it up and replace)"
      return
    fi
  fi

  mkdir -p "$target"
  touch "$target/.catstack-generated"
  local entry name
  for entry in "$src"/*; do
    name="$(basename "$entry")"
    if [ "$name" = "SKILL.md" ]; then
      sed 's/^disable-model-invocation: true$/disable-model-invocation: false/' "$entry" > "$target/SKILL.md"
    else
      link_item "cat-mode/$name" "$entry" "$target/$name"
    fi
  done
  echo "local   cat-mode (CATSTACK_CAT_MODE_DEFAULT=decide — SKILL.md materialized with disable-model-invocation:false, rest still symlinked)"
}

# Skills live under engine/skills, corpus/skills, and product/skills.
# Install flattens them into ~/.*/skills/<name> for every harness.
SKILL_ROOTS=(
  "$REPO_DIR/engine/skills"
  "$REPO_DIR/corpus/skills"
  "$REPO_DIR/product/skills"
)

install_into() {
  local agent="$1" skills_dir="$2"
  mkdir -p "$skills_dir"
  echo "--- $agent ($skills_dir) ---"

  local skill_root skill_path name
  for skill_root in "${SKILL_ROOTS[@]}"; do
    [ -d "$skill_root" ] || continue
    for skill_path in "$skill_root"/*/; do
      [ -d "$skill_path" ] || continue
      name="$(basename "$skill_path")"

      if [ "$agent" != "claude" ] && is_claude_only "$name"; then
        echo "skip    $name (Claude-specific, not installed for $agent)"
        continue
      fi

      if [ "$ENGINE_ONLY" = 1 ]; then
        case "$skill_root" in
          "$REPO_DIR/corpus/skills")
            echo "omit    $name (engine-only)"
            continue
            ;;
          "$REPO_DIR/product/skills")
            is_engine_core=0
            for core in "${ENGINE_CORE_PRODUCT_SKILLS[@]}"; do
              [ "$core" = "$name" ] && is_engine_core=1 && break
            done
            if [ "$is_engine_core" = 0 ]; then
              echo "omit    $name (engine-only)"
              continue
            fi
            ;;
        esac
      fi

      if [ "$name" = "cat-mode" ]; then
        link_cat_mode "$skill_root" "$skills_dir"
      else
        link_item "$name" "$skill_root/$name" "$skills_dir/$name"
      fi
    done
  done
}

install_into claude "$HOME/.claude/skills"
install_into cursor "$HOME/.cursor/skills"
install_into codex  "$HOME/.codex/skills"

# Hooks aren't per-agent skill folders, so they don't go through install_into
# -- but they get the same fixed, portable symlink location. Hook configs
# (claude.hook.json, codex's config.toml notify line) reference this fixed
# $HOME-relative path rather than $REPO_DIR, so the checked-in config never
# bakes in a machine-specific absolute path or username.
echo "--- claude hooks (\$HOME/.claude/hooks) ---"
mkdir -p "$HOME/.claude/hooks"
link_item "_markers" "$REPO_DIR/engine/hooks/_markers" "$HOME/.claude/hooks/_markers"
install_local_runner "$REPO_DIR/engine/hooks/_runner" "$HOME/.claude/hooks/_runner"
link_item "_flags" "$REPO_DIR/engine/hooks/_flags" "$HOME/.claude/hooks/_flags"
link_item "_sdk" "$REPO_DIR/engine/hooks/_sdk" "$HOME/.claude/hooks/_sdk"
link_item "diu-stop" "$REPO_DIR/engine/hooks/diu-stop" "$HOME/.claude/hooks/diu-stop"
link_item "bug-complaint-leak" "$REPO_DIR/engine/hooks/bug-complaint-leak" "$HOME/.claude/hooks/bug-complaint-leak"
link_item "demo-freeze" "$REPO_DIR/engine/hooks/demo-freeze" "$HOME/.claude/hooks/demo-freeze"
link_item "frustration-watchdog" "$REPO_DIR/engine/hooks/frustration-watchdog" "$HOME/.claude/hooks/frustration-watchdog"
link_item "skill-usage-log" "$REPO_DIR/engine/hooks/skill-usage-log" "$HOME/.claude/hooks/skill-usage-log"
link_item "reflect-on-thrash" "$REPO_DIR/engine/hooks/reflect-on-thrash" "$HOME/.claude/hooks/reflect-on-thrash"
link_item "scope-lock" "$REPO_DIR/engine/hooks/scope-lock" "$HOME/.claude/hooks/scope-lock"
link_item "restart-risk-check" "$REPO_DIR/engine/hooks/restart-risk-check" "$HOME/.claude/hooks/restart-risk-check"
link_item "auto-pr" "$REPO_DIR/engine/hooks/auto-pr" "$HOME/.claude/hooks/auto-pr"
link_item "pr-schema-gate" "$REPO_DIR/engine/hooks/pr-schema-gate" "$HOME/.claude/hooks/pr-schema-gate"
link_item "external-claim-gate" "$REPO_DIR/engine/hooks/external-claim-gate" "$HOME/.claude/hooks/external-claim-gate"
link_item "wrong-check-reflect" "$REPO_DIR/engine/hooks/wrong-check-reflect" "$HOME/.claude/hooks/wrong-check-reflect"
link_item "handback-needs-attempt" "$REPO_DIR/engine/hooks/handback-needs-attempt" "$HOME/.claude/hooks/handback-needs-attempt"
link_item "llm-judge" "$REPO_DIR/engine/hooks/llm-judge" "$HOME/.claude/hooks/llm-judge"
link_item "hook-health" "$REPO_DIR/engine/hooks/hook-health" "$HOME/.claude/hooks/hook-health"
link_item "build-the-lever" "$REPO_DIR/engine/hooks/build-the-lever" "$HOME/.claude/hooks/build-the-lever"
link_item "split-scope" "$REPO_DIR/engine/hooks/split-scope" "$HOME/.claude/hooks/split-scope"
link_item "no-comments" "$REPO_DIR/engine/hooks/no-comments" "$HOME/.claude/hooks/no-comments"
link_item "explicit-failures" "$REPO_DIR/engine/hooks/explicit-failures" "$HOME/.claude/hooks/explicit-failures"
link_item "text-match-decision-warn" "$REPO_DIR/engine/hooks/text-match-decision-warn" "$HOME/.claude/hooks/text-match-decision-warn"
link_item "bound-tool-result" "$REPO_DIR/engine/hooks/bound-tool-result" "$HOME/.claude/hooks/bound-tool-result"
link_item "repeat-error-stop" "$REPO_DIR/engine/hooks/repeat-error-stop" "$HOME/.claude/hooks/repeat-error-stop"
link_item "repeat-deny-stop" "$REPO_DIR/engine/hooks/repeat-deny-stop" "$HOME/.claude/hooks/repeat-deny-stop"
link_item "prove-it-ship-gate" "$REPO_DIR/engine/hooks/prove-it-ship-gate" "$HOME/.claude/hooks/prove-it-ship-gate"
link_item "narrow-the-scope" "$REPO_DIR/engine/hooks/narrow-the-scope" "$HOME/.claude/hooks/narrow-the-scope"
link_item "answer-overrides-menu" "$REPO_DIR/engine/hooks/answer-overrides-menu" "$HOME/.claude/hooks/answer-overrides-menu"
link_item "serial-option-guard" "$REPO_DIR/engine/hooks/serial-option-guard" "$HOME/.claude/hooks/serial-option-guard"
link_item "cat-mode-default" "$REPO_DIR/engine/hooks/cat-mode-default" "$HOME/.claude/hooks/cat-mode-default"
link_item "fanout-routing-guard" "$REPO_DIR/engine/hooks/fanout-routing-guard" "$HOME/.claude/hooks/fanout-routing-guard"
link_item "playbook-router" "$REPO_DIR/engine/hooks/playbook-router" "$HOME/.claude/hooks/playbook-router"
link_item "restated-constraint" "$REPO_DIR/engine/hooks/restated-constraint" "$HOME/.claude/hooks/restated-constraint"
link_item "named-verb-guard" "$REPO_DIR/engine/hooks/named-verb-guard" "$HOME/.claude/hooks/named-verb-guard"
link_item "user-did-it" "$REPO_DIR/engine/hooks/user-did-it" "$HOME/.claude/hooks/user-did-it"
echo "--- claude hooks: wait / hedge / callout stack ---"
link_item "wait-needs-wakeup" "$REPO_DIR/engine/hooks/wait-needs-wakeup" "$HOME/.claude/hooks/wait-needs-wakeup"
link_item "hedge-runs-prove-it" "$REPO_DIR/engine/hooks/hedge-runs-prove-it" "$HOME/.claude/hooks/hedge-runs-prove-it"
link_item "gate-blame-needs-evidence" "$REPO_DIR/engine/hooks/gate-blame-needs-evidence" "$HOME/.claude/hooks/gate-blame-needs-evidence"
link_item "unverified-tag-ledger" "$REPO_DIR/engine/hooks/unverified-tag-ledger" "$HOME/.claude/hooks/unverified-tag-ledger"
link_item "unverified-tag-check" "$REPO_DIR/engine/hooks/unverified-tag-check" "$HOME/.claude/hooks/unverified-tag-check"
link_item "incidence-needs-repetition" "$REPO_DIR/engine/hooks/incidence-needs-repetition" "$HOME/.claude/hooks/incidence-needs-repetition"
link_item "verdict-flip-watch" "$REPO_DIR/engine/hooks/verdict-flip-watch" "$HOME/.claude/hooks/verdict-flip-watch"
link_item "new-file-callout" "$REPO_DIR/engine/hooks/new-file-callout" "$HOME/.claude/hooks/new-file-callout"
link_item "agent-relay-attribution" "$REPO_DIR/engine/hooks/agent-relay-attribution" "$HOME/.claude/hooks/agent-relay-attribution"
link_item "agent-launch-guard" "$REPO_DIR/engine/hooks/agent-launch-guard" "$HOME/.claude/hooks/agent-launch-guard"
link_item "scratchpad-collision" "$REPO_DIR/engine/hooks/scratchpad-collision" "$HOME/.claude/hooks/scratchpad-collision"
link_item "ui-input-guard" "$REPO_DIR/engine/hooks/ui-input-guard" "$HOME/.claude/hooks/ui-input-guard"
link_item "handoff-needs-smoke-test" "$REPO_DIR/engine/hooks/handoff-needs-smoke-test" "$HOME/.claude/hooks/handoff-needs-smoke-test"
link_item "hook-freshness" "$REPO_DIR/engine/hooks/hook-freshness" "$HOME/.claude/hooks/hook-freshness"
link_item "gh-write-verification" "$REPO_DIR/engine/hooks/gh-write-verification" "$HOME/.claude/hooks/gh-write-verification"
link_item "history-before-reversal" "$REPO_DIR/engine/hooks/history-before-reversal" "$HOME/.claude/hooks/history-before-reversal"
link_item "publish-act-guard" "$REPO_DIR/engine/hooks/publish-act-guard" "$HOME/.claude/hooks/publish-act-guard"
link_item "categorical-scope-guard" "$REPO_DIR/engine/hooks/categorical-scope-guard" "$HOME/.claude/hooks/categorical-scope-guard"
link_item "claimed-search-not-run" "$REPO_DIR/engine/hooks/claimed-search-not-run" "$HOME/.claude/hooks/claimed-search-not-run"

echo "--- git pre-push hooks (init.templateDir and this clone) ---"
bash "$REPO_DIR/scripts/install/install-git-template.sh"
(cd "$REPO_DIR" && bash scripts/install/install-git-hooks.sh) || echo "install-git-hooks: left the prior pre-push in place"

echo "--- cursor hooks dir (\$HOME/.cursor/hooks) ---"
mkdir -p "$HOME/.cursor/hooks"
install_local_runner "$REPO_DIR/engine/hooks/_runner" "$HOME/.cursor/hooks/_runner"
link_item "_flags" "$REPO_DIR/engine/hooks/_flags" "$HOME/.cursor/hooks/_flags"
link_item "_sdk" "$REPO_DIR/engine/hooks/_sdk" "$HOME/.cursor/hooks/_sdk"
link_item "_markers" "$REPO_DIR/engine/hooks/_markers" "$HOME/.cursor/hooks/_markers"
link_item "bug-complaint-leak" "$REPO_DIR/engine/hooks/bug-complaint-leak" "$HOME/.cursor/hooks/bug-complaint-leak"
link_item "reflect-on-thrash" "$REPO_DIR/engine/hooks/reflect-on-thrash" "$HOME/.cursor/hooks/reflect-on-thrash"
link_item "scope-lock" "$REPO_DIR/engine/hooks/scope-lock" "$HOME/.cursor/hooks/scope-lock"
link_item "auto-pr" "$REPO_DIR/engine/hooks/auto-pr" "$HOME/.cursor/hooks/auto-pr"
link_item "pr-schema-gate" "$REPO_DIR/engine/hooks/pr-schema-gate" "$HOME/.cursor/hooks/pr-schema-gate"
link_item "wrong-check-reflect" "$REPO_DIR/engine/hooks/wrong-check-reflect" "$HOME/.cursor/hooks/wrong-check-reflect"
link_item "llm-judge" "$REPO_DIR/engine/hooks/llm-judge" "$HOME/.cursor/hooks/llm-judge"
link_item "hook-health" "$REPO_DIR/engine/hooks/hook-health" "$HOME/.cursor/hooks/hook-health"
link_item "skill-usage-log" "$REPO_DIR/engine/hooks/skill-usage-log" "$HOME/.cursor/hooks/skill-usage-log"
link_item "build-the-lever" "$REPO_DIR/engine/hooks/build-the-lever" "$HOME/.cursor/hooks/build-the-lever"
link_item "split-scope" "$REPO_DIR/engine/hooks/split-scope" "$HOME/.cursor/hooks/split-scope"
link_item "repeat-error-stop" "$REPO_DIR/engine/hooks/repeat-error-stop" "$HOME/.cursor/hooks/repeat-error-stop"
link_item "ui-input-guard" "$REPO_DIR/engine/hooks/ui-input-guard" "$HOME/.cursor/hooks/ui-input-guard"
link_item "text-match-decision-warn" "$REPO_DIR/engine/hooks/text-match-decision-warn" "$HOME/.cursor/hooks/text-match-decision-warn"
link_item "bound-tool-result" "$REPO_DIR/engine/hooks/bound-tool-result" "$HOME/.cursor/hooks/bound-tool-result"

echo "--- codex hooks (\$HOME/.codex/hooks) ---"
mkdir -p "$HOME/.codex/hooks"
install_local_runner "$REPO_DIR/engine/hooks/_runner" "$HOME/.codex/hooks/_runner"
link_item "_flags" "$REPO_DIR/engine/hooks/_flags" "$HOME/.codex/hooks/_flags"
link_item "_sdk" "$REPO_DIR/engine/hooks/_sdk" "$HOME/.codex/hooks/_sdk"
link_item "_markers" "$REPO_DIR/engine/hooks/_markers" "$HOME/.codex/hooks/_markers"
link_item "diu-stop" "$REPO_DIR/engine/hooks/diu-stop" "$HOME/.codex/hooks/diu-stop"
link_item "scope-lock" "$REPO_DIR/engine/hooks/scope-lock" "$HOME/.codex/hooks/scope-lock"
link_item "auto-pr" "$REPO_DIR/engine/hooks/auto-pr" "$HOME/.codex/hooks/auto-pr"
link_item "pr-schema-gate" "$REPO_DIR/engine/hooks/pr-schema-gate" "$HOME/.codex/hooks/pr-schema-gate"
link_item "wrong-check-reflect" "$REPO_DIR/engine/hooks/wrong-check-reflect" "$HOME/.codex/hooks/wrong-check-reflect"
link_item "llm-judge" "$REPO_DIR/engine/hooks/llm-judge" "$HOME/.codex/hooks/llm-judge"
link_item "hook-health" "$REPO_DIR/engine/hooks/hook-health" "$HOME/.codex/hooks/hook-health"
link_item "skill-usage-log" "$REPO_DIR/engine/hooks/skill-usage-log" "$HOME/.codex/hooks/skill-usage-log"
link_item "build-the-lever" "$REPO_DIR/engine/hooks/build-the-lever" "$HOME/.codex/hooks/build-the-lever"
link_item "split-scope" "$REPO_DIR/engine/hooks/split-scope" "$HOME/.codex/hooks/split-scope"
link_item "repeat-error-stop" "$REPO_DIR/engine/hooks/repeat-error-stop" "$HOME/.codex/hooks/repeat-error-stop"
link_item "ui-input-guard" "$REPO_DIR/engine/hooks/ui-input-guard" "$HOME/.codex/hooks/ui-input-guard"
link_item "text-match-decision-warn" "$REPO_DIR/engine/hooks/text-match-decision-warn" "$HOME/.codex/hooks/text-match-decision-warn"
link_item "bound-tool-result" "$REPO_DIR/engine/hooks/bound-tool-result" "$HOME/.codex/hooks/bound-tool-result"

# cursor.hooks.json used to be a plain symlink to diu-stop's fragment. That
# breaks when other hooks need to merge into the same file, so install.sh now
# only seeds a real ~/.cursor/hooks.json when missing; bug-complaint-leak's
# installer materializes + merges without rewriting the diu-stop source.
echo "--- cursor hooks.json (\$HOME/.cursor/hooks.json) ---"
mkdir -p "$HOME/.cursor"
if [ -L "$HOME/.cursor/hooks.json" ]; then
  echo "note    hooks.json is a symlink; bug-complaint-leak installer will materialize a real merged file"
elif [ -e "$HOME/.cursor/hooks.json" ]; then
  echo "ok      hooks.json already a real file (merge installers only)"
else
  cp "$REPO_DIR/engine/hooks/diu-stop/cursor.hooks.json" "$HOME/.cursor/hooks.json"
  echo "link    seeded hooks.json from diu-stop fragment"
fi

# settings.json and config.toml carry other unrelated config, so they can't
# be symlinked -- these do an idempotent, marker-based merge instead: safe
# to rerun, replaces only the diu-stop entry, never touches anything else in
# either file. See each script's docstring for exactly what it does.
echo "--- claude Stop + UserPromptSubmit hooks (\$HOME/.claude/settings.json) ---"
python3 "$REPO_DIR/engine/hooks/diu-stop/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/unverified-tag-ledger/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/unverified-tag-check/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/bug-complaint-leak/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/reflect-on-thrash/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/scope-lock/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/restart-risk-check/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/auto-pr/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/pr-schema-gate/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/external-claim-gate/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/wrong-check-reflect/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/handback-needs-attempt/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/llm-judge/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/hook-health/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/build-the-lever/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/split-scope/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/no-comments/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/explicit-failures/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/text-match-decision-warn/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/bound-tool-result/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-error-stop/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-deny-stop/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/frustration-watchdog/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/demo-freeze/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/prove-it-ship-gate/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/narrow-the-scope/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/answer-overrides-menu/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/serial-option-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/skill-usage-log/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/cat-mode-default/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/fanout-routing-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/playbook-router/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/restated-constraint/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/named-verb-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/user-did-it/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/gh-write-verification/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/history-before-reversal/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/publish-act-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/categorical-scope-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/claimed-search-not-run/install_claude_hook.py"

echo "--- subagent-inheritance: every Stop hook above also fires on SubagentStop; a manifest opts out with subagent_stop.inherit=false + reason ---"
python3 "$REPO_DIR/scripts/install/mirror_stop_hooks_to_subagent_stop.py"

echo "--- claude settings: wait / hedge / callout stack ---"
python3 "$REPO_DIR/engine/hooks/wait-needs-wakeup/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/hedge-runs-prove-it/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/gate-blame-needs-evidence/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/incidence-needs-repetition/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/verdict-flip-watch/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/new-file-callout/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/agent-relay-attribution/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/agent-launch-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/scratchpad-collision/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/ui-input-guard/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/handoff-needs-smoke-test/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/hook-freshness/install_claude_hook.py"

echo "--- cursor bug-complaint-leak merge (\$HOME/.cursor/hooks.json) ---"
python3 "$REPO_DIR/engine/hooks/bug-complaint-leak/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/reflect-on-thrash/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/scope-lock/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/auto-pr/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/pr-schema-gate/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/wrong-check-reflect/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/llm-judge/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/hook-health/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/skill-usage-log/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/build-the-lever/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/split-scope/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-error-stop/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/text-match-decision-warn/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/bound-tool-result/install_cursor_hook.py"

echo "--- codex notify (\$HOME/.codex/config.toml) ---"
python3 "$REPO_DIR/engine/hooks/diu-stop/install_codex_notify.py"
python3 "$REPO_DIR/engine/hooks/wrong-check-reflect/install_codex_notify.py"
python3 "$REPO_DIR/engine/hooks/llm-judge/install_codex_notify.py"
python3 "$REPO_DIR/engine/hooks/llm-judge/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/auto-pr/install_codex_notify.py"

echo "--- codex pre_tool_use merge (\$HOME/.codex/hooks.json, UNVERIFIED schema -- smoke-test after install) ---"
python3 "$REPO_DIR/engine/hooks/pr-schema-gate/install_codex_hook.py"

echo "--- codex native scope-lock hooks (\$HOME/.codex/hooks.json) ---"
python3 "$REPO_DIR/engine/hooks/scope-lock/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/hook-health/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/skill-usage-log/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/build-the-lever/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/split-scope/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-error-stop/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/text-match-decision-warn/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/bound-tool-result/install_codex_hook.py"

echo "--- wrap installed hook commands with runner ---"
python3 "$REPO_DIR/engine/hooks/_runner/wrap_installed.py"

# CLAUDE.md is a dedicated file with no other unrelated config mixed into it
# (unlike settings.json/config.toml above), so it symlinks directly like
# cursor.hooks.json -- link_item still refuses to clobber a real file
# without --force, so a machine that already has one keeps it (and gets
# told to rerun with --force once they're ready to hand it over to this
# repo as the source of truth).
echo "--- claude global CLAUDE.md (\$HOME/.claude/CLAUDE.md) ---"
mkdir -p "$HOME/.claude"
CLAUDE_MD_TARGET="$REPO_DIR/CLAUDE.md"
if [ "$ENGINE_ONLY" = 1 ]; then
  CLAUDE_MD_TARGET="$REPO_DIR/engine/CLAUDE.core.md"
fi
link_item "CLAUDE.md" "$CLAUDE_MD_TARGET" "$HOME/.claude/CLAUDE.md"

# Description-only skills lose to a competing generic `gh pr create` recipe.
# Cursor needs an alwaysApply rule; Claude uses CLAUDE.md; Codex uses a
# marked block in AGENTS.md. Slash commands land in all three command dirs.
# Same pattern for create-skill: skills MUST land in Claude+Cursor+Codex.
echo "--- always-on PR + create-skill + named-constraints + evidence-check (Cursor rules, commands, Codex AGENTS.md) ---"
mkdir -p "$HOME/.cursor/rules"
link_item "draft-pr-precedence.mdc" \
  "$REPO_DIR/cursor/rules/draft-pr-precedence.mdc" \
  "$HOME/.cursor/rules/draft-pr-precedence.mdc"
link_item "create-skill-three-harnesses.mdc" \
  "$REPO_DIR/cursor/rules/create-skill-three-harnesses.mdc" \
  "$HOME/.cursor/rules/create-skill-three-harnesses.mdc"
link_item "named-constraints.mdc" \
  "$REPO_DIR/cursor/rules/named-constraints.mdc" \
  "$HOME/.cursor/rules/named-constraints.mdc"
link_item "evidence-check.mdc" \
  "$REPO_DIR/engine/hooks/wrong-check-reflect/evidence-check.mdc" \
  "$HOME/.cursor/rules/evidence-check.mdc"
echo "--- learned session-hygiene rules (\$HOME/.cursor/rules/session-hygiene.mdc, generated from corpus/CLAUDE.learned.md) ---"
if [ "$ENGINE_ONLY" = 1 ]; then
  python3 "$REPO_DIR/scripts/install/install_cursor_session_hygiene.py" --remove
else
  python3 "$REPO_DIR/scripts/install/install_cursor_session_hygiene.py"
fi
for agent_commands in \
  "$HOME/.cursor/commands" \
  "$HOME/.claude/commands" \
  "$HOME/.codex/commands"
do
  mkdir -p "$agent_commands"
  for cmd in pr-skill draft-pr make-pr show-me-your-work; do
    link_item "$cmd.md" \
      "$REPO_DIR/commands/$cmd.md" \
      "$agent_commands/$cmd.md"
  done
done

echo "--- reflect enforcement rules (CATSTACK_REFLECT_ENFORCEMENT, see engine/hooks/_flags/README.md) ---"
REFLECT_ENFORCEMENT_STATE="$(python3 "$REPO_DIR/engine/hooks/_flags/flags.py" CATSTACK_REFLECT_ENFORCEMENT --cwd "$REPO_DIR")"
REFLECT_RULE_LOCAL="${CATSTACK_REFLECT_RULE_FILE:-$REPO_DIR/engine/reflect-enforcement.local.md}"
REFLECT_RULE_SRC="$REPO_DIR/engine/hooks/_flags/rules/reflect-enforcement"
REFLECT_RULE_CURSOR_SRC="$REFLECT_RULE_SRC.mdc"
REFLECT_RULE_CURSOR="$HOME/.cursor/rules/reflect-enforcement.mdc"
if [ "$REFLECT_ENFORCEMENT_STATE" = on ]; then
  cp "$REFLECT_RULE_SRC.md" "$REFLECT_RULE_LOCAL"
  echo "write   engine/reflect-enforcement.local.md (on: automate-me rule for Claude)"
  link_item "reflect-enforcement.mdc" "$REFLECT_RULE_CURSOR_SRC" "$REFLECT_RULE_CURSOR"
  CODEX_AGENTS_ARGS=(--fragment "reflect-enforcement=$REFLECT_RULE_SRC.md")
else
  echo "Reflect enforcement is off on this machine: CATSTACK_REFLECT_ENFORCEMENT is $REFLECT_ENFORCEMENT_STATE." > "$REFLECT_RULE_LOCAL"
  echo "write   engine/reflect-enforcement.local.md ($REFLECT_ENFORCEMENT_STATE: no automate-me rule)"
  if [ -L "$REFLECT_RULE_CURSOR" ] && [ "$(readlink "$REFLECT_RULE_CURSOR")" = "$REFLECT_RULE_CURSOR_SRC" ]; then
    rm "$REFLECT_RULE_CURSOR"
    echo "remove  reflect-enforcement.mdc"
  fi
  CODEX_AGENTS_ARGS=(--without reflect-enforcement)
fi
python3 "$REPO_DIR/scripts/install/install_codex_agents_md.py" "${CODEX_AGENTS_ARGS[@]}"

echo "--- remove catstack links this install no longer creates ---"
CATSTACK_ROOTS="$REPO_DIR"$'\n'"$(cd "$REPO_DIR" && pwd -P)"
if MAIN_CHECKOUT="$(resolve_main_checkout "$REPO_DIR")"; then
  CATSTACK_ROOTS="$CATSTACK_ROOTS"$'\n'"$MAIN_CHECKOUT"
fi
CATSTACK_ROOTS="$CATSTACK_ROOTS"$'\n'"$(git -C "$REPO_DIR" worktree list --porcelain 2>/dev/null | sed -n 's/^worktree //p' || true)"
for sweep_dir in \
  "$HOME/.claude/hooks" "$HOME/.claude/skills" "$HOME/.claude/commands" \
  "$HOME/.cursor/hooks" "$HOME/.cursor/skills" "$HOME/.cursor/commands" "$HOME/.cursor/rules" \
  "$HOME/.codex/hooks" "$HOME/.codex/skills" "$HOME/.codex/commands"
do
  [ -d "$sweep_dir" ] || continue
  for entry in "$sweep_dir"/*; do
    [ -L "$entry" ] || continue
    case "$INSTALLED_LINKS" in
      *$'\n'"$entry"$'\n'*) continue ;;
    esac
    raw_target="$(readlink "$entry")"
    while IFS= read -r root; do
      [ -n "$root" ] || continue
      case "$raw_target" in
        "$root/"*)
          echo "prune   $(basename "$entry") (catstack link this install no longer creates)"
          rm "$entry"
          break
          ;;
      esac
    done <<< "$CATSTACK_ROOTS"
  done
done
python3 "$REPO_DIR/scripts/install/prune_dead_hook_entries.py"

# Opt-in continuous session miner (local launchd). Default install does not
# scan ~/.claude / ~/.cursor / ~/.codex. See engine/skills/reflect/references/session-mine.md.
if [ "$WITH_SESSION_MINE" = 1 ]; then
  echo "--- session-mine launchd (opt-in) ---"
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "skip    launchd only supported on macOS; run session_mine.py via cron instead"
  else
    PLIST_SRC="$REPO_DIR/engine/skills/reflect/scripts/com.catstack.session-mine.plist.template"
    PLIST_DST="$HOME/Library/LaunchAgents/com.catstack.session-mine.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    mkdir -p "$HOME/.cache/catstack-session-mine"
    PYTHON3="$(command -v python3)"
    sed \
      -e "s|__PYTHON3__|$PYTHON3|g" \
      -e "s|__SESSION_MINE__|$REPO_DIR/engine/skills/reflect/scripts/session_mine.py|g" \
      -e "s|__HOME__|$HOME|g" \
      "$PLIST_SRC" > "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "ok      loaded $PLIST_DST (hourly session_mine.py run --hours 168)"
  fi
else
  echo "--- session-mine (skipped; pass --with-session-mine to enable hourly scan) ---"
fi

# Opt-in weekly DORA snapshot (local launchd). Needs local sessions + git.
# Opens a PR; never merges. See engine/skills/reflect/baselines/dora-ai-report.md.
if [ "$WITH_DORA_SNAPSHOT" = 1 ]; then
  echo "--- dora-snapshot launchd (opt-in) ---"
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "skip    launchd only supported on macOS; run publish_dora_snapshot.py via cron instead"
  else
    PLIST_SRC="$REPO_DIR/engine/skills/reflect/scripts/com.catstack.dora-snapshot.plist.template"
    PLIST_DST="$HOME/Library/LaunchAgents/com.catstack.dora-snapshot.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    mkdir -p "$HOME/.cache/catstack-dora-snapshot"
    PYTHON3="$(command -v python3)"
    sed \
      -e "s|__PYTHON3__|$PYTHON3|g" \
      -e "s|__PUBLISH__|$REPO_DIR/engine/skills/reflect/scripts/publish_dora_snapshot.py|g" \
      -e "s|__HOME__|$HOME|g" \
      -e "s|__REPO__|$REPO_DIR|g" \
      "$PLIST_SRC" > "$PLIST_DST"
    if command -v plutil >/dev/null 2>&1; then
      plutil -lint "$PLIST_DST" >/dev/null
    fi
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "ok      loaded $PLIST_DST (weekly Mon 9:00 publish_dora_snapshot.py)"
  fi
else
  echo "--- dora-snapshot (skipped; pass --with-dora-snapshot to enable weekly charts/PRs) ---"
fi

DOCTOR_STATUS=0
if command -v python3 >/dev/null 2>&1 && [ -f "$REPO_DIR/engine/hooks/_runner/doctor.py" ]; then
  echo
  echo "--- hook doctor (rerun any time: python3 \$HOME/.claude/hooks/_runner/doctor.py) ---"
  python3 "$REPO_DIR/engine/hooks/_runner/doctor.py" || DOCTOR_STATUS=5
fi

if [ -n "$SKIPPED_ITEMS" ]; then
  echo
  echo "WARNING: these were NOT installed because a real file already sits at the target:"
  echo "  $SKIPPED_ITEMS"
  echo "They are shadowing what this installer would have linked, so their rules are not"
  echo "in effect. Rerun with --force to back up the existing files and link them."
  if [ "$DOCTOR_STATUS" -eq 0 ]; then
    DOCTOR_STATUS=3
  fi
fi

exit "$DOCTOR_STATUS"
