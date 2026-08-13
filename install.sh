#!/bin/bash
# Symlinks every skill in this repo into ~/.claude/skills, so they stay live —
# edit here, pull on another machine, and every symlink picks it up immediately.
# Safe to rerun: skips a name that's already the correct symlink, and refuses
# to clobber a real (non-symlink) directory or file without --force.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

mkdir -p "$SKILLS_DIR"

for skill_path in "$REPO_DIR"/skills/*/; do
  name="$(basename "$skill_path")"
  target="$SKILLS_DIR/$name"
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
