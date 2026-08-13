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
CLAUDE_ONLY_SKILLS=(reflect)

is_claude_only() {
  local name="$1"
  for s in "${CLAUDE_ONLY_SKILLS[@]}"; do
    [ "$s" = "$name" ] && return 0
  done
  return 1
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

    target="$skills_dir/$name"
    src="$REPO_DIR/skills/$name"

    if [ -L "$target" ]; then
      if [ "$(readlink "$target")" = "$src" ]; then
        echo "ok      $name (already linked)"
        continue
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
  done
}

install_into claude "$HOME/.claude/skills"
install_into cursor "$HOME/.cursor/skills"
install_into codex  "$HOME/.codex/skills"
