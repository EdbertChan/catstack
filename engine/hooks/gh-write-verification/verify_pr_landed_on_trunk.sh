#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: verify_pr_landed_on_trunk.sh <pr-number> [trunk-branch]" >&2
  echo "  asserts the PR's merge commit is an ancestor of origin/<trunk-branch>" >&2
  exit 64
}

[ "$#" -ge 1 ] || usage
PR_NUMBER="$1"
TRUNK="${2:-main}"

if ! SLUG="$(gh repo view --json nameWithOwner --jq .nameWithOwner)"; then
  echo "FAIL: cannot resolve the current repository with gh repo view" >&2
  exit 1
fi

if ! FIELDS="$(gh api "repos/${SLUG}/pulls/${PR_NUMBER}" \
  --jq '[.merged, .base.ref, (.merge_commit_sha // "none")] | @tsv')"; then
  echo "FAIL: cannot read PR #${PR_NUMBER} from ${SLUG}" >&2
  exit 1
fi
read -r MERGED BASE_REF MERGE_SHA <<<"$FIELDS"

echo "pr=#${PR_NUMBER} repo=${SLUG} merged=${MERGED} base=${BASE_REF} merge_commit=${MERGE_SHA}"

if [ "$MERGED" != "true" ]; then
  echo "FAIL: PR #${PR_NUMBER} is not merged" >&2
  exit 1
fi

if [ "$MERGE_SHA" = "none" ] || [ -z "$MERGE_SHA" ]; then
  echo "FAIL: PR #${PR_NUMBER} reports merged with no merge commit sha" >&2
  exit 1
fi

git fetch --quiet origin "$TRUNK"

if ! git cat-file -e "${MERGE_SHA}^{commit}" 2>/dev/null; then
  git fetch --quiet origin "$MERGE_SHA" || true
fi

if ! git cat-file -e "${MERGE_SHA}^{commit}" 2>/dev/null; then
  echo "FAIL: merge commit ${MERGE_SHA} is not fetchable into this clone" >&2
  exit 1
fi

if git merge-base --is-ancestor "$MERGE_SHA" "origin/${TRUNK}"; then
  echo "OK: ${MERGE_SHA} is an ancestor of origin/${TRUNK}"
  exit 0
fi

echo "FAIL: PR #${PR_NUMBER} reports MERGED but ${MERGE_SHA} is not on origin/${TRUNK}" >&2
echo "      it landed on: $(git branch -r --contains "$MERGE_SHA" | tr -d ' ' | paste -sd, -)" >&2
echo "      the PR merged into its own base ref (${BASE_REF}), not the trunk" >&2
exit 1
