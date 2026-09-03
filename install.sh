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

# Skills written against one agent's specific mechanics (a tool name, a
# transcript path convention) that would be actively wrong to install
# elsewhere verbatim. Everything not listed here is agent-agnostic prose and
# installs everywhere.
CLAUDE_ONLY_SKILLS=(automate-me cat-mode narrow-the-scope)
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
link_item() {
  local name="$1" src="$2" target="$3"

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
      echo "skip    $name (real directory already exists — rerun with --force to back it up and replace with a symlink)"
    fi
  else
    echo "link    $name"
    ln -s "$src" "$target"
  fi
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

      link_item "$name" "$skill_root/$name" "$skills_dir/$name"
    done
  done
}

install_into claude "$HOME/.claude/skills"
install_into cursor "$HOME/.cursor/skills"
install_into codex  "$HOME/.codex/skills"

if [ "$ENGINE_ONLY" = 1 ]; then
  for skills_dir in "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"; do
    [ -d "$skills_dir" ] || continue
    for entry in "$skills_dir"/*; do
      [ -L "$entry" ] || continue
      raw_target="$(readlink "$entry")"
      name="$(basename "$entry")"
      case "$raw_target" in
        "$REPO_DIR/corpus/"*)
          echo "prune   $name (engine-only)"
          rm "$entry"
          ;;
        "$REPO_DIR/product/"*)
          is_engine_core=0
          for core in "${ENGINE_CORE_PRODUCT_SKILLS[@]}"; do
            [ "$core" = "$name" ] && is_engine_core=1 && break
          done
          if [ "$is_engine_core" = 0 ]; then
            echo "prune   $name (engine-only)"
            rm "$entry"
          fi
          ;;
      esac
    done
  done
fi

# Hooks aren't per-agent skill folders, so they don't go through install_into
# -- but they get the same fixed, portable symlink location. Hook configs
# (claude.hook.json, codex's config.toml notify line) reference this fixed
# $HOME-relative path rather than $REPO_DIR, so the checked-in config never
# bakes in a machine-specific absolute path or username.
echo "--- claude hooks (\$HOME/.claude/hooks) ---"
mkdir -p "$HOME/.claude/hooks"
link_item "diu-stop" "$REPO_DIR/engine/hooks/diu-stop" "$HOME/.claude/hooks/diu-stop"
link_item "bug-complaint-leak" "$REPO_DIR/engine/hooks/bug-complaint-leak" "$HOME/.claude/hooks/bug-complaint-leak"
link_item "demo-freeze" "$REPO_DIR/engine/hooks/demo-freeze" "$HOME/.claude/hooks/demo-freeze"
link_item "frustration-watchdog" "$REPO_DIR/engine/hooks/frustration-watchdog" "$HOME/.claude/hooks/frustration-watchdog"
link_item "reflect-on-thrash" "$REPO_DIR/engine/hooks/reflect-on-thrash" "$HOME/.claude/hooks/reflect-on-thrash"
link_item "scope-lock" "$REPO_DIR/engine/hooks/scope-lock" "$HOME/.claude/hooks/scope-lock"
link_item "restart-risk-check" "$REPO_DIR/engine/hooks/restart-risk-check" "$HOME/.claude/hooks/restart-risk-check"
link_item "auto-pr" "$REPO_DIR/engine/hooks/auto-pr" "$HOME/.claude/hooks/auto-pr"
link_item "pr-schema-gate" "$REPO_DIR/engine/hooks/pr-schema-gate" "$HOME/.claude/hooks/pr-schema-gate"
link_item "wrong-check-reflect" "$REPO_DIR/engine/hooks/wrong-check-reflect" "$HOME/.claude/hooks/wrong-check-reflect"
link_item "build-the-lever" "$REPO_DIR/engine/hooks/build-the-lever" "$HOME/.claude/hooks/build-the-lever"
link_item "no-comments" "$REPO_DIR/engine/hooks/no-comments" "$HOME/.claude/hooks/no-comments"
link_item "repeat-error-stop" "$REPO_DIR/engine/hooks/repeat-error-stop" "$HOME/.claude/hooks/repeat-error-stop"

echo "--- cursor hooks dir (\$HOME/.cursor/hooks) ---"
mkdir -p "$HOME/.cursor/hooks"
link_item "bug-complaint-leak" "$REPO_DIR/engine/hooks/bug-complaint-leak" "$HOME/.cursor/hooks/bug-complaint-leak"
link_item "reflect-on-thrash" "$REPO_DIR/engine/hooks/reflect-on-thrash" "$HOME/.cursor/hooks/reflect-on-thrash"
link_item "scope-lock" "$REPO_DIR/engine/hooks/scope-lock" "$HOME/.cursor/hooks/scope-lock"
link_item "auto-pr" "$REPO_DIR/engine/hooks/auto-pr" "$HOME/.cursor/hooks/auto-pr"
link_item "pr-schema-gate" "$REPO_DIR/engine/hooks/pr-schema-gate" "$HOME/.cursor/hooks/pr-schema-gate"
link_item "wrong-check-reflect" "$REPO_DIR/engine/hooks/wrong-check-reflect" "$HOME/.cursor/hooks/wrong-check-reflect"
link_item "build-the-lever" "$REPO_DIR/engine/hooks/build-the-lever" "$HOME/.cursor/hooks/build-the-lever"
link_item "repeat-error-stop" "$REPO_DIR/engine/hooks/repeat-error-stop" "$HOME/.cursor/hooks/repeat-error-stop"

echo "--- codex hooks (\$HOME/.codex/hooks) ---"
mkdir -p "$HOME/.codex/hooks"
link_item "diu-stop" "$REPO_DIR/engine/hooks/diu-stop" "$HOME/.codex/hooks/diu-stop"
link_item "scope-lock" "$REPO_DIR/engine/hooks/scope-lock" "$HOME/.codex/hooks/scope-lock"
link_item "auto-pr" "$REPO_DIR/engine/hooks/auto-pr" "$HOME/.codex/hooks/auto-pr"
link_item "pr-schema-gate" "$REPO_DIR/engine/hooks/pr-schema-gate" "$HOME/.codex/hooks/pr-schema-gate"
link_item "wrong-check-reflect" "$REPO_DIR/engine/hooks/wrong-check-reflect" "$HOME/.codex/hooks/wrong-check-reflect"
link_item "build-the-lever" "$REPO_DIR/engine/hooks/build-the-lever" "$HOME/.codex/hooks/build-the-lever"
link_item "repeat-error-stop" "$REPO_DIR/engine/hooks/repeat-error-stop" "$HOME/.codex/hooks/repeat-error-stop"

# Deleted worktrees leave symlinks behind that point into this repo but at a
# path that no longer exists (e.g. .worktrees/<gone>/engine/hooks/<name>).
# Remove only those: dangling AND raw target under $REPO_DIR. Links into any
# other location are someone else's and are left alone, dangling or not.
echo "--- prune dangling links into this repo ---"
for prune_dir in \
  "$HOME/.claude/hooks" "$HOME/.cursor/hooks" "$HOME/.codex/hooks" \
  "$HOME/.claude/skills" "$HOME/.cursor/skills" "$HOME/.codex/skills"
do
  [ -d "$prune_dir" ] || continue
  for entry in "$prune_dir"/*; do
    [ -L "$entry" ] || continue
    [ -e "$entry" ] && continue
    raw_target="$(readlink "$entry")"
    case "$raw_target" in
      "$REPO_DIR/"*)
        echo "prune   $(basename "$entry") (dangling link into this repo)"
        rm "$entry"
        ;;
    esac
  done
done

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
python3 "$REPO_DIR/engine/hooks/bug-complaint-leak/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/reflect-on-thrash/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/scope-lock/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/restart-risk-check/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/auto-pr/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/pr-schema-gate/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/wrong-check-reflect/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/build-the-lever/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/no-comments/install_claude_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-error-stop/install_claude_hook.py"
python3 "$REPO_DIR/scripts/prune_dead_hook_entries.py"

echo "--- cursor bug-complaint-leak merge (\$HOME/.cursor/hooks.json) ---"
python3 "$REPO_DIR/engine/hooks/bug-complaint-leak/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/reflect-on-thrash/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/scope-lock/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/auto-pr/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/pr-schema-gate/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/wrong-check-reflect/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/build-the-lever/install_cursor_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-error-stop/install_cursor_hook.py"

echo "--- codex notify (\$HOME/.codex/config.toml) ---"
python3 "$REPO_DIR/engine/hooks/diu-stop/install_codex_notify.py"
python3 "$REPO_DIR/engine/hooks/wrong-check-reflect/install_codex_notify.py"
python3 "$REPO_DIR/engine/hooks/auto-pr/install_codex_notify.py"

echo "--- codex pre_tool_use merge (\$HOME/.codex/hooks.json, UNVERIFIED schema -- smoke-test after install) ---"
python3 "$REPO_DIR/engine/hooks/pr-schema-gate/install_codex_hook.py"

echo "--- codex native scope-lock hooks (\$HOME/.codex/hooks.json) ---"
python3 "$REPO_DIR/engine/hooks/scope-lock/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/build-the-lever/install_codex_hook.py"
python3 "$REPO_DIR/engine/hooks/repeat-error-stop/install_codex_hook.py"

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
python3 "$REPO_DIR/install_codex_agents_md.py"

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
