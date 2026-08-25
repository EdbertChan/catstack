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
WITH_SESSION_MINE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --with-session-mine) WITH_SESSION_MINE=1 ;;
    -h|--help)
      echo "Usage: ./install.sh [--force] [--with-session-mine]"
      echo "  --force               back up real files before replacing with symlinks"
      echo "  --with-session-mine   install hourly launchd agent (macOS) for session mining"
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

install_into() {
  local agent="$1" skills_dir="$2"
  mkdir -p "$skills_dir"
  echo "--- $agent ($skills_dir) ---"

  for skill_path in "$REPO_DIR"/skills/*/; do
    name="$(basename "$skill_path")"

    if [ "$agent" != "claude" ] && is_claude_only "$name"; then
      echo "skip    $name (Claude-specific, not installed for $agent)"
      continue
    fi

    link_item "$name" "$REPO_DIR/skills/$name" "$skills_dir/$name"
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
link_item "diu-stop" "$REPO_DIR/hooks/diu-stop" "$HOME/.claude/hooks/diu-stop"
link_item "bug-complaint-leak" "$REPO_DIR/hooks/bug-complaint-leak" "$HOME/.claude/hooks/bug-complaint-leak"
link_item "demo-freeze" "$REPO_DIR/hooks/demo-freeze" "$HOME/.claude/hooks/demo-freeze"
link_item "frustration-watchdog" "$REPO_DIR/hooks/frustration-watchdog" "$HOME/.claude/hooks/frustration-watchdog"
link_item "reflect-on-thrash" "$REPO_DIR/hooks/reflect-on-thrash" "$HOME/.claude/hooks/reflect-on-thrash"
link_item "restart-risk-check" "$REPO_DIR/hooks/restart-risk-check" "$HOME/.claude/hooks/restart-risk-check"
link_item "auto-pr" "$REPO_DIR/hooks/auto-pr" "$HOME/.claude/hooks/auto-pr"

echo "--- cursor hooks dir (\$HOME/.cursor/hooks) ---"
mkdir -p "$HOME/.cursor/hooks"
link_item "bug-complaint-leak" "$REPO_DIR/hooks/bug-complaint-leak" "$HOME/.cursor/hooks/bug-complaint-leak"
link_item "reflect-on-thrash" "$REPO_DIR/hooks/reflect-on-thrash" "$HOME/.cursor/hooks/reflect-on-thrash"
link_item "auto-pr" "$REPO_DIR/hooks/auto-pr" "$HOME/.cursor/hooks/auto-pr"

echo "--- codex hooks (\$HOME/.codex/hooks) ---"
mkdir -p "$HOME/.codex/hooks"
link_item "diu-stop" "$REPO_DIR/hooks/diu-stop" "$HOME/.codex/hooks/diu-stop"

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
  cp "$REPO_DIR/hooks/diu-stop/cursor.hooks.json" "$HOME/.cursor/hooks.json"
  echo "link    seeded hooks.json from diu-stop fragment"
fi

# settings.json and config.toml carry other unrelated config, so they can't
# be symlinked -- these do an idempotent, marker-based merge instead: safe
# to rerun, replaces only the diu-stop entry, never touches anything else in
# either file. See each script's docstring for exactly what it does.
echo "--- claude Stop + UserPromptSubmit hooks (\$HOME/.claude/settings.json) ---"
python3 "$REPO_DIR/hooks/diu-stop/install_claude_hook.py"
python3 "$REPO_DIR/hooks/bug-complaint-leak/install_claude_hook.py"
python3 "$REPO_DIR/hooks/reflect-on-thrash/install_claude_hook.py"
python3 "$REPO_DIR/hooks/restart-risk-check/install_claude_hook.py"
python3 "$REPO_DIR/hooks/auto-pr/install_claude_hook.py"

echo "--- cursor bug-complaint-leak merge (\$HOME/.cursor/hooks.json) ---"
python3 "$REPO_DIR/hooks/bug-complaint-leak/install_cursor_hook.py"
python3 "$REPO_DIR/hooks/reflect-on-thrash/install_cursor_hook.py"
python3 "$REPO_DIR/hooks/auto-pr/install_cursor_hook.py"

echo "--- codex notify (\$HOME/.codex/config.toml) ---"
python3 "$REPO_DIR/hooks/diu-stop/install_codex_notify.py"

# CLAUDE.md is a dedicated file with no other unrelated config mixed into it
# (unlike settings.json/config.toml above), so it symlinks directly like
# cursor.hooks.json -- link_item still refuses to clobber a real file
# without --force, so a machine that already has one keeps it (and gets
# told to rerun with --force once they're ready to hand it over to this
# repo as the source of truth).
echo "--- claude global CLAUDE.md (\$HOME/.claude/CLAUDE.md) ---"
mkdir -p "$HOME/.claude"
link_item "CLAUDE.md" "$REPO_DIR/CLAUDE.md" "$HOME/.claude/CLAUDE.md"

# Description-only skills lose to a competing generic `gh pr create` recipe.
# Cursor needs an alwaysApply rule; Claude uses CLAUDE.md; Codex uses a
# marked block in AGENTS.md. Slash commands land in all three command dirs.
# Same pattern for create-skill: skills MUST land in Claude+Cursor+Codex.
echo "--- always-on PR + create-skill (Cursor rules, commands, Codex AGENTS.md) ---"
mkdir -p "$HOME/.cursor/rules"
link_item "draft-pr-precedence.mdc" \
  "$REPO_DIR/cursor/rules/draft-pr-precedence.mdc" \
  "$HOME/.cursor/rules/draft-pr-precedence.mdc"
link_item "create-skill-three-harnesses.mdc" \
  "$REPO_DIR/cursor/rules/create-skill-three-harnesses.mdc" \
  "$HOME/.cursor/rules/create-skill-three-harnesses.mdc"
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
# scan ~/.claude / ~/.cursor / ~/.codex. See skills/reflect/references/session-mine.md.
if [ "$WITH_SESSION_MINE" = 1 ]; then
  echo "--- session-mine launchd (opt-in) ---"
  if [ "$(uname -s)" != "Darwin" ]; then
    echo "skip    launchd only supported on macOS; run session_mine.py via cron instead"
  else
    PLIST_SRC="$REPO_DIR/skills/reflect/scripts/com.catstack.session-mine.plist.template"
    PLIST_DST="$HOME/Library/LaunchAgents/com.catstack.session-mine.plist"
    mkdir -p "$HOME/Library/LaunchAgents"
    mkdir -p "$HOME/.cache/catstack-session-mine"
    PYTHON3="$(command -v python3)"
    sed \
      -e "s|__PYTHON3__|$PYTHON3|g" \
      -e "s|__SESSION_MINE__|$REPO_DIR/skills/reflect/scripts/session_mine.py|g" \
      -e "s|__HOME__|$HOME|g" \
      "$PLIST_SRC" > "$PLIST_DST"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    launchctl load "$PLIST_DST"
    echo "ok      loaded $PLIST_DST (hourly session_mine.py run --hours 168)"
  fi
else
  echo "--- session-mine (skipped; pass --with-session-mine to enable hourly scan) ---"
fi

