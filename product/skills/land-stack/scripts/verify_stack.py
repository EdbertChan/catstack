#!/usr/bin/env python3
"""Guard for landing a PR stack: only SHA-verified PR numbers, in order.

The land-stack skill (step 2) lists four checks that must all pass before any
merge write, and told the agent to "write a small script for this check".
This is that script. Pure functions take the `gh pr list --json` payload so
tests can replay a real fixture; the CLI shells out to `gh` and `git`.

    verify_stack.py --repo owner/name 7006 7007 7010          # verify these, bottom-up
    verify_stack.py --repo owner/name --discover               # suggest a stack
    verify_stack.py --prs-json prs.json --git-dir ~/src/x 7006 7007

Exit 0: every check passed. Exit 1: a check failed (do not land). Exit 3:
discovery found duplicate head branches and needs a human to confirm.

After a queue write, `--queue-state` reads each PR's Mergify Merge Queue check
run and says merged, queued, not-queued, or unchecked. A queue label alone is
not a queued state: Mergify reports "Merge queue is ready" until something
actually queues the PR.

    verify_stack.py --repo owner/name --queue-state 7006 7007
    verify_stack.py --queue-json runs.json --queue-state 7006

Queue-state exit 0: every PR merged or queued. Exit 1: a PR is not queued.
Exit 2: a PR's queue state could not be read.
Never uses `gh pr list --head <branch>` -- discovering by branch name is the
unsafe path the skill exists to prevent.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Callable

GH_FIELDS = "number,baseRefName,headRefName,headRefOid,title,state"


def fetch_open_prs(repo: str | None, limit: int = 100) -> list[dict]:
    cmd = ["gh", "pr", "list", "--state", "open", "--json", GH_FIELDS, "--limit", str(limit)]
    if repo:
        cmd += ["-R", repo]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def sha_exists_locally(sha: str, git_dir: str = ".") -> bool:
    res = subprocess.run(["git", "-C", git_dir, "cat-file", "-e", f"{sha}^{{commit}}"],
                         capture_output=True, text=True)
    return res.returncode == 0


def verify(prs: list[dict], numbers: list[int], *, trunk: str, branch_prefix: str,
           sha_exists: Callable[[str], bool]) -> list[str]:
    """Return a list of failures (empty == safe to land bottom-up)."""
    by_number = {p["number"]: p for p in prs}
    failures: list[str] = []
    prev_head: str | None = None
    for i, n in enumerate(numbers):
        pr = by_number.get(n)
        if pr is None:
            failures.append(f"#{n}: not in the open PR list (closed, merged, or wrong repo)")
            prev_head = None
            continue
        if pr.get("state", "OPEN") != "OPEN":
            failures.append(f"#{n}: state is {pr.get('state')}, not OPEN")
        head = pr["headRefName"]
        if not head.startswith(branch_prefix):
            failures.append(f"#{n}: head branch `{head}` does not match stack convention `{branch_prefix}*`")
        if not sha_exists(pr["headRefOid"]):
            failures.append(f"#{n}: head sha {pr['headRefOid'][:10]} is not in the local clone -- you have not reviewed this code")
        expected_base = trunk if i == 0 else prev_head
        if expected_base is not None and pr["baseRefName"] != expected_base:
            failures.append(f"#{n}: base is `{pr['baseRefName']}`, expected `{expected_base}`"
                            + (" (trunk)" if i == 0 else " (previous PR's head)"))
        prev_head = head
    return failures


def discover(prs: list[dict], *, trunk: str, branch_prefix: str,
             sha_exists: Callable[[str], bool]) -> dict:
    """Suggest bottom-up stacks from open PRs. Returns {stacks, duplicates}."""
    cands = [p for p in prs if p["headRefName"].startswith(branch_prefix)
             and p.get("state", "OPEN") == "OPEN" and sha_exists(p["headRefOid"])]
    heads: dict[str, list[int]] = {}
    for p in cands:
        heads.setdefault(p["headRefName"], []).append(p["number"])
    duplicates = {h: ns for h, ns in heads.items() if len(ns) > 1}
    by_base: dict[str, list[dict]] = {}
    for p in cands:
        by_base.setdefault(p["baseRefName"], []).append(p)
    stacks: list[list[int]] = []
    for bottom in sorted(by_base.get(trunk, []), key=lambda p: p["number"]):
        chain = [bottom["number"]]
        cur = bottom["headRefName"]
        seen = {cur}
        while True:
            nxt = by_base.get(cur, [])
            if len(nxt) != 1 or nxt[0]["headRefName"] in seen:
                break
            chain.append(nxt[0]["number"])
            cur = nxt[0]["headRefName"]
            seen.add(cur)
        stacks.append(chain)
    return {"stacks": stacks, "duplicates": duplicates}


QUEUE_CHECK = "Mergify Merge Queue"


def queue_state(pr: dict, check_runs: list[dict]) -> tuple[str, str]:
    if pr.get("merged"):
        return "merged", "merged"
    runs = [c for c in check_runs if c.get("name") == QUEUE_CHECK]
    if not runs:
        return "unchecked", f"no {QUEUE_CHECK} check run"
    run = runs[-1]
    output = run.get("output") or {}
    title = output.get("title") or ""
    summary = output.get("summary") or ""
    if run.get("status") in ("queued", "in_progress") or "queued" in title.lower():
        return "queued", title or run.get("status", "")
    if "can be added to the merge queue" in summary or title == "Merge queue is ready":
        return "not-queued", title
    return "unchecked", f"unrecognised {QUEUE_CHECK} state: {run.get('status')}/{run.get('conclusion')} {title}"


def fetch_queue_entry(repo: str | None, number: int) -> dict:
    prefix = f"repos/{repo}" if repo else "repos/{owner}/{repo}"
    pr = json.loads(subprocess.run(["gh", "api", f"{prefix}/pulls/{number}"],
                                   capture_output=True, text=True, check=True).stdout)
    runs = json.loads(subprocess.run(["gh", "api", f"{prefix}/commits/{pr['head']['sha']}/check-runs"],
                                     capture_output=True, text=True, check=True).stdout)["check_runs"]
    return {"pr": {"number": number, "state": pr["state"], "merged": pr["merged"]}, "check_runs": runs}


def report_queue_state(keys: list[str], entries: dict) -> int:
    states = []
    for key in keys:
        entry = entries.get(key)
        if entry is None:
            state, why = "unchecked", "no payload for this PR"
        else:
            state, why = queue_state(entry["pr"], entry["check_runs"])
        states.append(state)
        print(f"{state:<11} #{key} {why}")
    if "not-queued" in states:
        return 1
    if "unchecked" in states:
        return 2
    return 0

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("numbers", nargs="*", help="PR numbers, bottom of stack first")
    ap.add_argument("--repo", help="owner/name for gh; default = current repo")
    ap.add_argument("--trunk", default="master")
    ap.add_argument("--branch-prefix", default="stack/")
    ap.add_argument("--git-dir", default=".", help="local clone used for the head-sha check")
    ap.add_argument("--prs-json", help="replay a saved `gh pr list --json` payload instead of calling gh")
    ap.add_argument("--discover", action="store_true", help="suggest stacks instead of verifying")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--queue-state", action="store_true", help="after a queue write: is each PR merged or queued?")
    ap.add_argument("--queue-json", help="replay saved pull + check-run payloads keyed by PR for --queue-state")
    args = ap.parse_args(argv)

    if args.queue_state:
        keys = args.numbers
        if not keys:
            ap.error("give PR numbers for --queue-state")
        if args.queue_json:
            with open(args.queue_json, encoding="utf-8") as fh:
                entries = json.load(fh)
        else:
            entries = {}
            for key in keys:
                try:
                    entries[key] = fetch_queue_entry(args.repo, int(key))
                except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
                    print(f"unchecked   #{key} could not read queue state: {exc}", file=sys.stderr)
        return report_queue_state(keys, entries)

    if args.prs_json:
        with open(args.prs_json, encoding="utf-8") as fh:
            prs = json.load(fh)
    else:
        prs = fetch_open_prs(args.repo)

    def sha_exists(sha: str) -> bool:
        return sha_exists_locally(sha, args.git_dir)

    if args.discover:
        result = discover(prs, trunk=args.trunk, branch_prefix=args.branch_prefix, sha_exists=sha_exists)
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for chain in result["stacks"]:
                print("stack   " + " -> ".join(f"#{n}" for n in chain))
            for head, ns in result["duplicates"].items():
                print(f"dup     {head}: {ns}")
        if result["duplicates"]:
            print("needs-confirmation: two or more open PRs share a head branch", file=sys.stderr)
            return 3
        return 0

    if not args.numbers:
        ap.error("give PR numbers bottom-up, or --discover")
    try:
        args.numbers = [int(n) for n in args.numbers]
    except ValueError as exc:
        ap.error(f"PR numbers must be integers: {exc}")
    failures = verify(prs, args.numbers, trunk=args.trunk, branch_prefix=args.branch_prefix, sha_exists=sha_exists)
    if args.json:
        print(json.dumps({"numbers": args.numbers, "failures": failures}, indent=2))
    else:
        for f in failures:
            print("fail    " + f)
        if not failures:
            print("ok      stack verified: " + " -> ".join(f"#{n}" for n in args.numbers))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
