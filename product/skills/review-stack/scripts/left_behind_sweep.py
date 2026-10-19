"""List finished work that is not in a target branch yet: branches, dirty worktrees and (optionally) Invoker workflows.

Usage: python3 left_behind_sweep.py <repo> <target> [--skip-prefix P ...] [--invoker] [--json]

Branches: every local branch except the target and those under a skipped prefix (default experiment/), with the
commits whose patch is not in the target (git cherry), marker subjects (Invoker task markers, merges) excluded, and
commits whose touched files already hold the same content in the target excluded too, so a review stack's own
slice branches, which regroup patches the target already has, stay quiet while a stale one speaks. Worktrees: every worktree of the repo with changed or untracked tracked-area files. Invoker: with
--invoker and invoker-cli on PATH, every workflow whose featureBranch has such commits. Exit 1 when anything is
listed, so the sweep can gate a new chain or a review page; 0 when clean.
"""
import json
import re
import shutil
import subprocess
import sys

MARKER = re.compile(r"^(invoker: |Merge )")
DEFAULT_SKIP = ("experiment/",)


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True).stdout


def content_already_in(repo, target, sha):
    paths = git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha).splitlines()
    if not paths:
        return True
    return subprocess.run(["git", "-C", repo, "diff", "--quiet", target, sha, "--", *paths], capture_output=True).returncode == 0


def real_patches_not_in(repo, target, branch):
    plus = [l[2:] for l in git(repo, "cherry", target, branch).splitlines() if l.startswith("+ ")]
    out = []
    for h in plus:
        subject = git(repo, "log", "-1", "--format=%s", h).strip()
        if not MARKER.match(subject) and not content_already_in(repo, target, h):
            out.append({"sha": h[:7], "subject": subject})
    return out


def branches(repo, target, skip):
    names = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/").split()
    found = []
    for n in names:
        if n == target or n.startswith(tuple(skip)):
            continue
        patches = real_patches_not_in(repo, target, n)
        if patches:
            found.append({"branch": n, "last_commit": git(repo, "log", "-1", "--format=%cs", n).strip(), "patches": patches})
    return found


def worktrees(repo):
    found = []
    for line in git(repo, "worktree", "list", "--porcelain").splitlines():
        if not line.startswith("worktree "):
            continue
        path = line[len("worktree "):]
        status = [l for l in git(path, "status", "--porcelain").splitlines() if l.strip()]
        if status:
            found.append({"worktree": path, "paths": len(status), "sample": [l[3:] for l in status[:5]]})
    return found


def invoker_workflows(repo, target):
    if not shutil.which("invoker-cli"):
        return None
    r = subprocess.run(["invoker-cli", "query", "workflows", "--output", "json"], capture_output=True, text=True)
    if r.returncode != 0:
        return {"error": r.stderr.strip()[:300]}
    data = json.loads(r.stdout)
    ws = data.get("workflows", data) if isinstance(data, dict) else data
    found = []
    for w in ws:
        fb = w.get("featureBranch")
        if not fb or not git(repo, "rev-parse", "--verify", "--quiet", fb).strip():
            continue
        patches = real_patches_not_in(repo, target, fb)
        if patches:
            found.append({"workflow": w.get("id"), "name": w.get("name"), "status": w.get("status"), "featureBranch": fb, "patches": len(patches)})
    return found


def main(argv):
    if len(argv) < 2:
        raise SystemExit(__doc__)
    repo, target = argv[0], argv[1]
    skip, want_invoker, as_json = list(DEFAULT_SKIP), False, False
    rest = argv[2:]
    while rest:
        a = rest.pop(0)
        if a == "--skip-prefix":
            skip.append(rest.pop(0))
        elif a == "--invoker":
            want_invoker = True
        elif a == "--json":
            as_json = True
        else:
            raise SystemExit(f"unknown argument {a}\n{__doc__}")
    report = {"target": target, "branches": branches(repo, target, skip), "dirty_worktrees": worktrees(repo)}
    if want_invoker:
        report["invoker"] = invoker_workflows(repo, target)
    dirty = bool(report["branches"] or report["dirty_worktrees"] or (isinstance(report.get("invoker"), list) and report["invoker"]))
    if as_json:
        print(json.dumps(report, indent=1))
    else:
        print(f"target {target}")
        print(f"branches with real patches not in {target}: {len(report['branches'])}")
        for b in report["branches"]:
            print(f"  {b['branch']} (last commit {b['last_commit']}): {len(b['patches'])} patches, e.g. {b['patches'][0]['sha']} {b['patches'][0]['subject'][:90]}")
        print(f"dirty worktrees: {len(report['dirty_worktrees'])}")
        for w in report["dirty_worktrees"]:
            print(f"  {w['worktree']}: {w['paths']} paths, e.g. {', '.join(w['sample'][:3])}")
        if want_invoker:
            inv = report["invoker"]
            if inv is None:
                print("invoker: invoker-cli not on PATH (unchecked)")
            elif isinstance(inv, dict):
                print(f"invoker: query failed (unchecked): {inv['error']}")
            else:
                print(f"invoker workflows with real patches not in {target}: {len(inv)}")
                for w in inv:
                    print(f"  {w['workflow']} {w['status']} {w['featureBranch']}: {w['patches']} patches | {w['name'][:80]}")
    return 1 if dirty else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
