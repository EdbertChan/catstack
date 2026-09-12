#!/usr/bin/env python3
"""Stop a rebase or salvage of a branch whose work has already landed on its base.

A branch that sits behind its base still shows per-file differences, and a
file listing reads every difference as content. Direction is the signal: on
a superseded branch the differences are the base's newer work, and carrying
the branch forward reverts it. This gate reads direction and prints the
numbers behind its verdict.

Catches, SUPERSEDED, exit 3:
  - every commit on the branch is already on the base: `git cherry` prints
    no '+' line, which includes a branch the base already contains;
  - the net diff against the base is deletion-dominated, and either every
    file that differs is behind the base (the branch's copy is one the base
    already had since they split), or the branch's own change is already on
    the base: every line it adds is in the base's copy of that file, every
    line it removes is gone from it, and no file it changes is binary or
    mode-only.

Allows, LIVE, exit 0:
  - a branch carrying commits the base does not have, even when it is also
    far behind the base.

Refuses, UNCHECKED, exit 2:
  - the ref or base does not resolve, a pull ref cannot be fetched, the
    clone is shallow, the two share no history, or git errors. UNCHECKED
    never exits 0, so it can never read as LIVE.

    python3 scripts/check_branch_not_superseded.py <branch>
    python3 scripts/check_branch_not_superseded.py '#<number>' --base origin/main
    python3 scripts/check_branch_not_superseded.py <branch> --repo <clone> --json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass

LIVE = "LIVE"
SUPERSEDED = "SUPERSEDED"
UNCHECKED = "UNCHECKED"
EXIT_CODES = {LIVE: 0, UNCHECKED: 2, SUPERSEDED: 3}

PULL_REF_RE = re.compile(r"^(?:#|(?:refs/)?pull/)(\d+)(?:/head)?$")
FETCHED_PULL_NAMESPACE = "refs/check-branch-not-superseded/pull"
ABSENT = "absent"


class GitError(Exception):
    pass


@dataclass
class Evidence:
    ahead: int
    behind: int
    unique_commits: int
    additions: int
    deletions: int
    binary_files: int
    files_differ: int
    files_behind: int
    added_lines_missing_from_base: int
    removed_lines_still_on_base: int
    unreadable_branch_files: int

    @property
    def files_ahead(self) -> int:
        return self.files_differ - self.files_behind


def _evidence(**overrides) -> dict:
    fields = dict(ahead=1, behind=0, unique_commits=1, additions=0, deletions=0, binary_files=0,
                  files_differ=0, files_behind=0, added_lines_missing_from_base=0,
                  removed_lines_still_on_base=0, unreadable_branch_files=0)
    fields.update(overrides)
    return fields


PROMISED_CATCH = (
    "ahead=1 behind=4 unique_commits=0 additions=82 deletions=1257 files_differ=32 files_behind=32",
    "ahead=0 behind=9 unique_commits=0 deletions=400 files_differ=12 files_behind=12",
    "ahead=2 behind=18 unique_commits=2 additions=192 deletions=7207 files_differ=118 files_behind=118",
    "ahead=3 behind=183 unique_commits=2 additions=849 deletions=38370 binary_files=15"
    " files_differ=573 files_behind=573 added_lines_missing_from_base=2",
    "ahead=2 behind=6 unique_commits=2 additions=4 deletions=120 files_differ=9 files_behind=8",
)
PROMISED_ALLOW = (
    "additions=40 deletions=2 files_differ=2 added_lines_missing_from_base=40",
    "behind=30 additions=12 deletions=900 files_differ=25 files_behind=24 added_lines_missing_from_base=12",
    "behind=30 deletions=950 files_differ=26 files_behind=25 removed_lines_still_on_base=60",
    "behind=30 additions=3 deletions=950 files_differ=26 files_behind=25 binary_files=1 unreadable_branch_files=1",
)


def exemplar_evidence(exemplar: str) -> Evidence:
    overrides = {key: int(value) for key, value in (pair.split("=") for pair in exemplar.split())}
    return Evidence(**_evidence(**overrides))


def classify(ev: Evidence) -> tuple[str, str]:
    if ev.unique_commits == 0:
        return SUPERSEDED, "every commit on the branch is already on the base (git cherry shows no '+')"
    if ev.deletions > ev.additions:
        if ev.files_ahead == 0:
            return SUPERSEDED, (
                "the net diff is deletion-dominated and every file that differs is behind the base"
            )
        if (ev.added_lines_missing_from_base == 0 and ev.removed_lines_still_on_base == 0
                and ev.unreadable_branch_files == 0):
            return SUPERSEDED, (
                "the net diff is deletion-dominated and the branch's own change is already on the base"
            )
    return LIVE, f"{ev.unique_commits} commit(s) on the branch are not on the base"


def flags_exemplar(exemplar: str) -> bool:
    return classify(exemplar_evidence(exemplar))[0] == SUPERSEDED


def git(repo: str, *args: str, ok: tuple[int, ...] = (0,)) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    proc = subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        env=env,
    )
    if proc.returncode not in ok:
        detail = proc.stderr.strip() or proc.stdout.strip() or "no output"
        raise GitError(f"git {' '.join(args)} exited {proc.returncode}: {detail}")
    return proc


def resolve_commit(repo: str, rev: str) -> str | None:
    if not rev or rev.startswith("-"):
        return None
    proc = git(repo, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", ok=(0, 1, 128))
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def resolve_branch(repo: str, ref: str, remote: str) -> tuple[str | None, str]:
    match = PULL_REF_RE.match(ref)
    if not match:
        sha = resolve_commit(repo, ref)
        return sha, "" if sha else f"ref {ref!r} does not resolve to a commit"
    number = match.group(1)
    local = f"{FETCHED_PULL_NAMESPACE}/{number}"
    fetched = git(repo, "fetch", "--quiet", "--no-tags", remote,
                  f"+refs/pull/{number}/head:{local}", ok=(0, 1, 128))
    if fetched.returncode != 0:
        detail = fetched.stderr.strip() or "no output"
        return None, f"could not fetch refs/pull/{number}/head from {remote!r}: {detail}"
    sha = resolve_commit(repo, local)
    return sha, "" if sha else f"fetched refs/pull/{number}/head but {local} does not resolve"


def parse_raw_z(output: str) -> list[tuple[str, str, str, str, str]]:
    tokens = output.split("\0")
    records = []
    i = 0
    while i < len(tokens):
        head = tokens[i].lstrip("\n")
        if head.startswith(":") and i + 1 < len(tokens):
            old_mode, new_mode, old_oid, new_oid = head[1:].split()[:4]
            records.append((tokens[i + 1], old_mode, new_mode, old_oid, new_oid))
            i += 2
        else:
            i += 1
    return records


def file_state(mode: str, oid: str) -> str:
    return ABSENT if set(oid) == {"0"} else f"{mode}:{oid}"


def raw_diff(repo: str, old: str, new: str) -> list[tuple[str, str, str, str, str]]:
    return parse_raw_z(git(repo, "diff", "--raw", "-z", "--no-renames", "--no-abbrev", old, new).stdout)


def count_files_behind(repo: str, base: str, merge_base: str, differing: dict[str, str]) -> int:
    history: dict[str, set[str]] = {}
    log = git(repo, "log", "--raw", "-z", "-m", "--no-renames", "--no-abbrev", "--format=", f"{merge_base}..{base}").stdout
    for path, old_mode, new_mode, old, new in parse_raw_z(log):
        history.setdefault(path, set()).update({file_state(old_mode, old), file_state(new_mode, new)})
    return sum(1 for path, state in differing.items() if state in history.get(path, set()))


def changed_lines_by_file(diff_text: str) -> dict[str, tuple[list[str], list[str]]]:
    out: dict[str, tuple[list[str], list[str]]] = {}
    old_path: str | None = None
    current: str | None = None
    for raw in diff_text.splitlines():
        if raw.startswith("diff --git "):
            old_path = current = None
        elif raw.startswith("--- ") and current is None:
            old_path = raw[6:] if raw.startswith("--- a/") else None
        elif raw.startswith("+++ ") and current is None:
            current = raw[6:] if raw.startswith("+++ b/") else old_path
            if current is not None:
                out.setdefault(current, ([], []))
        elif raw.startswith("@@"):
            continue
        elif current is not None and raw.startswith("+"):
            out[current][0].append(raw[1:])
        elif current is not None and raw.startswith("-"):
            out[current][1].append(raw[1:])
    return out


def branch_change_on_base(repo: str, base: str, branch: str, merge_base: str,
                          differing: dict[str, str]) -> tuple[int, int, int]:
    own = {path: (om, nm) for path, om, nm, _oo, _no in raw_diff(repo, merge_base, branch)}
    binary = set()
    for entry in git(repo, "diff", "--numstat", "-z", "--no-renames", merge_base, branch).stdout.split("\0"):
        parts = entry.split("\t", 2)
        if len(parts) == 3 and parts[0] == "-":
            binary.add(parts[2])
    diff = git(repo, "-c", "core.quotePath=false", "diff", "-U0", "--no-color", "--no-ext-diff",
               "--no-renames", "--src-prefix=a/", "--dst-prefix=b/", merge_base, branch).stdout
    lines_by_file = changed_lines_by_file(diff)
    unreadable = sum(1 for path in lines_by_file if path not in own)
    missing = still = 0
    for path, (old_mode, new_mode) in own.items():
        if path not in differing:
            continue
        mode_only = old_mode != new_mode and "000000" not in (old_mode, new_mode)
        if path in binary or mode_only or path not in lines_by_file:
            unreadable += 1
            continue
        shown = git(repo, "cat-file", "blob", f"{base}:{path}", ok=(0, 128))
        present = {line.strip() for line in shown.stdout.splitlines()} if shown.returncode == 0 else set()
        added, removed = lines_by_file[path]
        missing += sum(1 for line in added if line.strip() and line.strip() not in present)
        still += sum(1 for line in removed if line.strip() and line.strip() in present)
    return missing, still, unreadable


def numstat_totals(repo: str, base: str, branch: str) -> tuple[int, int, int]:
    additions = deletions = binary = 0
    for line in git(repo, "diff", "--numstat", "--no-renames", base, branch).stdout.splitlines():
        added, deleted, _path = line.split("\t", 2)
        if added == "-" or deleted == "-":
            binary += 1
            continue
        additions += int(added)
        deletions += int(deleted)
    return additions, deletions, binary


def gather(repo: str, base: str, branch: str) -> tuple[Evidence | None, str]:
    if git(repo, "rev-parse", "--is-shallow-repository").stdout.strip() == "true":
        return None, "the clone is shallow, so commit counts and patch matching cannot see full history"
    merge_base_proc = git(repo, "merge-base", base, branch, ok=(0, 1))
    merge_base = merge_base_proc.stdout.strip()
    if merge_base_proc.returncode != 0 or not merge_base:
        return None, "the branch and the base share no history"
    behind, ahead = (int(n) for n in git(repo, "rev-list", "--left-right", "--count", f"{base}...{branch}").stdout.split())
    unique = sum(1 for line in git(repo, "cherry", base, branch).stdout.splitlines() if line.startswith("+"))
    additions, deletions, binary = numstat_totals(repo, base, branch)
    differing = {path: file_state(nm, new) for path, _om, nm, _old, new in raw_diff(repo, base, branch)}
    missing, still, unreadable = branch_change_on_base(repo, base, branch, merge_base, differing)
    evidence = Evidence(
        ahead=ahead,
        behind=behind,
        unique_commits=unique,
        additions=additions,
        deletions=deletions,
        binary_files=binary,
        files_differ=len(differing),
        files_behind=count_files_behind(repo, base, merge_base, differing),
        added_lines_missing_from_base=missing,
        removed_lines_still_on_base=still,
        unreadable_branch_files=unreadable,
    )
    return evidence, ""


def evaluate(repo: str, ref: str, base: str, remote: str) -> dict:
    result = {"verdict": UNCHECKED, "ref": ref, "base": base, "reason": "", "numbers": None}
    try:
        base_sha = resolve_commit(repo, base)
        if not base_sha:
            result["reason"] = f"base {base!r} does not resolve; fetch it first"
            return result
        branch_sha, why = resolve_branch(repo, ref, remote)
        if not branch_sha:
            result["reason"] = why
            return result
        evidence, why = gather(repo, base_sha, branch_sha)
    except GitError as exc:
        result["reason"] = str(exc)
        return result
    except (OSError, ValueError) as exc:
        result["reason"] = f"{type(exc).__name__}: {exc}"
        return result
    if evidence is None:
        result["reason"] = why
        return result
    verdict, reason = classify(evidence)
    numbers = asdict(evidence)
    numbers["files_ahead"] = evidence.files_ahead
    result.update(verdict=verdict, reason=reason, numbers=numbers)
    return result


def render(result: dict) -> str:
    lines = [f"{result['verdict']}  {result['ref']} against {result['base']}", f"  reason: {result['reason']}"]
    n = result["numbers"]
    if n is None:
        lines.append("  numbers: not computed, so this is not a pass")
        return "\n".join(lines)
    lines += [
        f"  commits ahead: {n['ahead']} ({n['unique_commits']} not on the base)",
        f"  commits behind: {n['behind']}",
        f"  net additions: {n['additions']}",
        f"  net deletions: {n['deletions']}",
        f"  files differ: {n['files_differ']} ({n['files_behind']} behind the base, {n['files_ahead']} ahead of it)",
        f"  binary files differ: {n['binary_files']}",
        f"  lines the branch adds that the base lacks: {n['added_lines_missing_from_base']}",
        f"  lines the branch removes that the base still has: {n['removed_lines_still_on_base']}",
        f"  branch files the line check cannot read: {n['unreadable_branch_files']}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ref", help="branch, commit, or pull ref ('#<number>', 'pull/<number>')")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--remote", default="origin", help="remote to fetch pull refs from")
    ap.add_argument("--repo", default=".", help="path to the git clone")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = evaluate(args.repo, args.ref, args.base, args.remote)
    print(json.dumps(result, indent=2) if args.json else render(result))
    if result["verdict"] == UNCHECKED:
        print(f"UNCHECKED  {result['reason']}", file=sys.stderr)
    return EXIT_CODES[result["verdict"]]


if __name__ == "__main__":
    raise SystemExit(main())
