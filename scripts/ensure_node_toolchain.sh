#!/bin/bash
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! cd "$REPO_DIR"; then
  echo "fail    cannot enter repo dir $REPO_DIR" >&2
  exit 1
fi

if [ ! -f package.json ]; then
  echo "ok      no package.json here; no Node toolchain to install"
  exit 0
fi

if [ -d node_modules ]; then
  echo "ok      Node toolchain already installed"
  exit 0
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "fail    npm not found; Node-backed tests (engine/skills/draft-pr) cannot run" >&2
  exit 1
fi

echo "==      installing Node toolchain (npm ci)"
if ! npm ci >&2; then
  echo "fail    npm ci failed; Node-backed tests (engine/skills/draft-pr) cannot run" >&2
  exit 1
fi

echo "ok      Node toolchain installed"
