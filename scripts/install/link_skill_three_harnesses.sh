#!/bin/bash
# Symlink one skill directory into Claude, Cursor, and Codex personal skill
# roots. Use for project-local skills that are not installed via catstack
# ./install.sh. Safe to rerun: replaces wrong symlinks; refuses to clobber a
# real (non-symlink) directory without --force.
set -euo pipefail

FORCE=0
if [ "${1:-}" = "--force" ]; then
  FORCE=1
  shift
fi

if [ $# -ne 1 ]; then
  echo "usage: $0 [--force] /absolute/path/to/skill-dir" >&2
  exit 2
fi

src="$(cd "$1" && pwd)"
name="$(basename "$src")"

if [ ! -f "$src/SKILL.md" ]; then
  echo "error: $src has no SKILL.md" >&2
  exit 1
fi

link_one() {
  local target="$1"
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ]; then
    if [ "$(readlink "$target")" = "$src" ]; then
      echo "ok      $target"
      return
    fi
    echo "relink  $target"
    rm "$target"
    ln -s "$src" "$target"
  elif [ -e "$target" ]; then
    if [ "$FORCE" = 1 ]; then
      backup="$target.bak.$(date +%Y%m%d%H%M%S 2>/dev/null || echo backup)"
      echo "backup  $target -> $backup"
      mv "$target" "$backup"
      ln -s "$src" "$target"
    else
      echo "skip    $target (real path exists — rerun with --force)" >&2
      return 1
    fi
  else
    echo "link    $target"
    ln -s "$src" "$target"
  fi
}

status=0
link_one "$HOME/.claude/skills/$name" || status=1
link_one "$HOME/.cursor/skills/$name" || status=1
link_one "$HOME/.codex/skills/$name" || status=1
exit "$status"
