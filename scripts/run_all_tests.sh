#!/bin/bash
# Single source of truth for "run every test suite in this repo." Discovers
# every tests/ dir instead of hand-listing them, so a new hook/skill's tests
# run in CI the moment its tests/ dir exists -- no ci.yml edit required.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

status=0
while IFS= read -r dir; do
  echo "=== $dir ==="
  python3 -m unittest discover -s "$dir" -v || status=1
done < <(find . -type d -name tests -not -path "./.worktrees/*" -not -path "*/__pycache__/*" | sort)

exit "$status"
