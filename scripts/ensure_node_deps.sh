#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

if [ ! -f package.json ]; then
  echo "ensure_node_deps: no package.json, nothing to install."
  exit 0
fi

if [ -d node_modules ]; then
  echo "ensure_node_deps: node_modules already present, skipping install."
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "ensure_node_deps: node_modules is missing and npm is not on PATH, so the Node-backed suites cannot run. Install Node and npm, then re-run." >&2
  exit 1
fi

if [ -f package-lock.json ]; then
  echo "ensure_node_deps: node_modules is missing, running 'npm ci'."
  install_cmd=(npm ci)
else
  echo "ensure_node_deps: node_modules is missing and there is no lockfile, running 'npm install'."
  install_cmd=(npm install)
fi

if ! "${install_cmd[@]}"; then
  echo "ensure_node_deps: '${install_cmd[*]}' failed, so the Node-backed suites cannot run. Fix the install and re-run." >&2
  exit 1
fi
