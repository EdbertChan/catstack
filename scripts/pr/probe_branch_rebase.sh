#!/usr/bin/env bash
set -uo pipefail

EXIT_OK=0
EXIT_FAIL=1
EXIT_UNCHECKED=3
EXIT_USAGE=64

usage() {
  echo "usage: probe_branch_rebase.sh <source-ref> <base-ref>" >&2
  echo "  exit ${EXIT_OK}  OK         <source-ref> rebases cleanly onto <base-ref>" >&2
  echo "  exit ${EXIT_FAIL}  FAIL       rebase ran and found a content conflict" >&2
  echo "  exit ${EXIT_UNCHECKED}  UNCHECKED  the probe could not run; nothing is proven" >&2
  echo "  exit ${EXIT_USAGE} usage error" >&2
  exit "$EXIT_USAGE"
}

unchecked() {
  echo "UNCHECKED: $*" >&2
  exit "$EXIT_UNCHECKED"
}

safe_name() {
  printf '%s' "$1" | LC_ALL=C tr -c 'A-Za-z0-9._-' '_' | cut -c1-40
}

cleanup() {
  if [ -n "${SCRATCH_DIR:-}" ]; then
    git worktree remove --force "$SCRATCH_DIR" >/dev/null 2>&1 || true
  fi
}

[ "$#" -eq 2 ] || usage

SOURCE_REF="$1"
BASE_REF="$2"
SCRATCH_DIR=""

if ! git rev-parse --git-dir >/dev/null; then
  unchecked "$(pwd) is not a git checkout"
fi

if ! SCRATCH_ROOT="$(git rev-parse --git-path rebase-probe-worktrees)"; then
  unchecked "could not resolve scratch worktree root"
fi

case "$SCRATCH_ROOT" in
  /*) ;;
  *)
    if ! REPO_ROOT="$(git rev-parse --show-toplevel)"; then
      unchecked "could not resolve repository root"
    fi
    SCRATCH_ROOT="${REPO_ROOT}/${SCRATCH_ROOT}"
    ;;
esac

if ! mkdir -p "$SCRATCH_ROOT"; then
  unchecked "could not create scratch worktree root: ${SCRATCH_ROOT}"
fi

if ! git rev-parse --verify --quiet "${BASE_REF}^{commit}" >/dev/null; then
  unchecked "base ref is not a commit: ${BASE_REF}"
fi

if ! DIGEST="$(printf '%s\n%s\n' "$SOURCE_REF" "$BASE_REF" | git hash-object --stdin)"; then
  unchecked "could not build scratch worktree name"
fi

SAFE_SOURCE="$(safe_name "$SOURCE_REF")"
SAFE_BASE="$(safe_name "$BASE_REF")"
SCRATCH_DIR="${SCRATCH_ROOT}/probe-${SAFE_SOURCE}-onto-${SAFE_BASE}-${DIGEST:0:12}"

if ! git worktree add --detach "$SCRATCH_DIR" "$SOURCE_REF"; then
  unchecked "could not create scratch worktree: ${SCRATCH_DIR}"
fi

trap cleanup EXIT

if git -C "$SCRATCH_DIR" rebase "$BASE_REF"; then
  exit "$EXIT_OK"
fi

if ! UNMERGED="$(git -C "$SCRATCH_DIR" ls-files -u)"; then
  unchecked "could not inspect rebase failure in scratch worktree: ${SCRATCH_DIR}"
fi

if [ -n "$UNMERGED" ]; then
  exit "$EXIT_FAIL"
fi

unchecked "rebase failed without content conflicts: ${SOURCE_REF} onto ${BASE_REF}"
