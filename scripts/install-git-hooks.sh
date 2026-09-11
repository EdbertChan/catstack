#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

marker="# catstack-pre-push-review-unit"
src="scripts/git-hooks/pre-push"
target="$(git rev-parse --git-path hooks)/pre-push"

if [[ -e $target || -L $target ]] && ! grep -qxF "$marker" "$target"; then
  echo "install-git-hooks: $target exists and was not written by catstack; leaving it alone" >&2
  exit 1
fi

mkdir -p "$(dirname "$target")"
cp "$src" "$target"
chmod +x "$target"
echo "install-git-hooks: installed $target"
