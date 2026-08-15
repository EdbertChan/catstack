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
[ "${1:-}" = "--force" ] && FORCE=1

# Skills written against one agent's specific mechanics (a tool name, a
# transcript path convention) that would be actively wrong to install
# elsewhere verbatim. Everything not listed here is agent-agnostic prose and
# installs everywhere.
CLAUDE_ONLY_SKILLS=(reflect automate-me)

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

echo "--- codex hooks (\$HOME/.codex/hooks) ---"
mkdir -p "$HOME/.codex/hooks"
link_item "diu-stop" "$REPO_DIR/hooks/diu-stop" "$HOME/.codex/hooks/diu-stop"

# cursor.hooks.json is a dedicated file (unlike settings.json/config.toml,
# which carry other unrelated config), so it can be symlinked directly like
# a skill -- but link_item refuses to clobber a real file without --force,
# so anyone with other Cursor hooks already configured keeps them and gets
# told to merge by hand instead of silently losing them.
echo "--- cursor stop hook (\$HOME/.cursor/hooks.json) ---"
mkdir -p "$HOME/.cursor"
link_item "hooks.json" "$REPO_DIR/hooks/diu-stop/cursor.hooks.json" "$HOME/.cursor/hooks.json"

# settings.json and config.toml carry other unrelated config, so they can't
# be symlinked -- these do an idempotent, marker-based merge instead: safe
# to rerun, replaces only the diu-stop entry, never touches anything else in
# either file. See each script's docstring for exactly what it does.
echo "--- claude Stop hook (\$HOME/.claude/settings.json) ---"
python3 "$REPO_DIR/hooks/diu-stop/install_claude_hook.py"

echo "--- codex notify (\$HOME/.codex/config.toml) ---"
python3 "$REPO_DIR/hooks/diu-stop/install_codex_notify.py"
