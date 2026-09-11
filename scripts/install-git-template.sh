#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

marker="# catstack-template-pre-push"
src="scripts/git-hooks/template-pre-push"
dir="${XDG_CONFIG_HOME:-$HOME/.config}/catstack/git-template"
target="$dir/hooks/pre-push"

current=$(git config --global --get init.templateDir || true)
if [[ -n $current && $current != "$dir" ]]; then
  echo "install-git-template: init.templateDir is already $current; leaving it alone"
  exit 0
fi

if [[ -e $target || -L $target ]] && ! grep -qxF "$marker" "$target"; then
  echo "install-git-template: $target was not written by catstack; leaving it alone"
  exit 0
fi

mkdir -p "$dir/hooks"
cp "$src" "$target"
chmod +x "$target"
git config --global init.templateDir "$dir"
echo "install-git-template: new clones get $target (init.templateDir=$dir)"
