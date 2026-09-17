#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
before_home="$(mktemp -d)"
after_home="$(mktemp -d)"
before_tree="$(mktemp -d)"

git -C "$repo_dir" archive HEAD | tar -x -C "$before_tree"
HOME="$before_home" bash "$before_tree/install.sh" >/dev/null

installed=0
for agent_dir in .claude .cursor .codex; do
  if [ -e "$before_home/$agent_dir/skills/cat-mode" ]; then
    installed=$((installed + 1))
  fi
done
if [ "$installed" != 3 ]; then
  echo "[FAIL] before change: CATSTACK_CAT_MODE_DEFAULT=decide did not install cat-mode for all three harnesses"
else
  echo "[PASS] before change: baseline installed cat-mode for all three harnesses"
  exit 1
fi

HOME="$after_home" CATSTACK_CAT_MODE_DEFAULT=decide bash "$repo_dir/install.sh" >/dev/null
for agent_dir in .claude .cursor .codex; do
  target="$after_home/$agent_dir/skills/cat-mode"
  test -d "$target"
  test ! -L "$target"
  grep -q '^disable-model-invocation: false$' "$target/SKILL.md"
done
echo "[PASS] after change: CATSTACK_CAT_MODE_DEFAULT=decide installed auto-invoking cat-mode for Claude, Cursor, and Codex"
