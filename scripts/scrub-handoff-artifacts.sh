#!/usr/bin/env bash
# Scrub ephemeral inter-task handoff files from this repository before merge.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

is_handoff_path() {
  local path="$1"
  local base="${path##*/}"

  case "$path" in
    .git/*|*/.git/*|node_modules/*|*/node_modules/*|scripts/*|*/scripts/*|packages/*|*/packages/*)
      return 1
      ;;
    plans/invoker-handoff.md|plans/invoker-handoff.yaml|candidates.json|*/candidates.json)
      return 0
      ;;
  esac

  case "$base" in
    research-*.json|lens-*.json)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

find_handoff_paths() {
  find . \
    -type d \( -name .git -o -name node_modules -o -name scripts -o -name packages \) -prune \
    -o \( -name candidates.json -o -name 'research-*.json' -o -name 'lens-*.json' \) -print0
}

while IFS= read -r -d '' path; do
  rm -f -- "$path"
done < <(find_handoff_paths)

for path in plans/invoker-handoff.md plans/invoker-handoff.yaml; do
  rm -f -- "$path"
done

tracked_deletions=()
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  while IFS= read -r -d '' path; do
    if is_handoff_path "$path"; then
      tracked_deletions+=("$path")
    fi
  done < <(git ls-files --deleted -z)
fi

if ((${#tracked_deletions[@]})); then
  git add -u -- "${tracked_deletions[@]}"
  git -c commit.gpgSign=false commit --quiet --no-verify \
    -m "chore: scrub inter-task handoff artifacts before merge" \
    -- "${tracked_deletions[@]}"
fi

residual_paths=()
while IFS= read -r -d '' path; do
  residual_paths+=("$path")
done < <(find_handoff_paths)
for path in plans/invoker-handoff.md plans/invoker-handoff.yaml; do
  if [[ -e "$path" || -L "$path" ]]; then
    residual_paths+=("$path")
  fi
done

if ((${#residual_paths[@]})); then
  echo "handoff files remain in worktree" >&2
  exit 1
fi

echo "scrub-handoff-artifacts-ok"
