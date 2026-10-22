"""Cut the difference between a base branch and an end branch into a stack of review branches, one claim each.

Usage: python3 build_review_stack.py <repo> <base> <end> <branch-prefix> <slices.json>

slices.json is a list, in dependency order, of {"slug", "title", "body", "globs": [...], "removals": [...]}.
Each slice takes the paths matching its globs from the end tree (a path goes to the first slice that matches it),
removes paths the end tree no longer has that match its removals, and commits on top of the previous slice as
<branch-prefix>/<n>-<slug>. The last slice's tree must be identical to the end tree and every changed path must be
claimed by some slice; otherwise the script exits 1. A slice's own tests (tests/test_*.py among its paths) are run
with unittest on that slice and the result is printed next to it.
"""
import fnmatch
import json
import subprocess
import sys
import tempfile


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True).stdout


def load_slices(path):
    slices = json.load(open(path))
    for s in slices:
        for key in ("slug", "title", "globs"):
            if key not in s:
                raise SystemExit(f"slice without {key!r}: {s}")
        s.setdefault("body", "")
        s.setdefault("removals", [])
    return slices


def run_tests(cwd, tests):
    r = subprocess.run([sys.executable, "-m", "unittest", *[t[:-3].replace("/", ".") for t in tests]], cwd=cwd,
                       capture_output=True, text=True)
    tail = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("Ran ", "OK", "FAILED"))]
    return " | ".join(tail) + f" | rc={r.returncode}", r.returncode


def main(repo, base, end, prefix, slices_path):
    slices = load_slices(slices_path)
    changed = [l.split("\t") for l in git(repo, "diff", "--name-status", "--no-renames", f"{base}..{end}").splitlines()]
    end_paths = set(git(repo, "ls-tree", "-r", "--name-only", end).splitlines())
    touched = {parts[1]: parts[0][0] for parts in changed}
    claimed = {}
    tmp = tempfile.mkdtemp(prefix="review-stack-")
    git(repo, "worktree", "add", "-q", "--detach", tmp, base)
    failed_tests = 0
    try:
        prev = base
        for i, s in enumerate(slices, 1):
            adds = [p for p in end_paths if any(fnmatch.fnmatch(p, g) for g in s["globs"]) and p in touched and p not in claimed]
            current = set(git(tmp, "ls-files").splitlines())
            gone = [p for p in current if p not in end_paths and any(fnmatch.fnmatch(p, r) for r in s["removals"]) and p not in claimed]
            for p in adds:
                git(tmp, "checkout", end, "--", p)
                claimed[p] = s["slug"]
            for p in gone:
                git(tmp, "rm", "-q", p)
                claimed[p] = s["slug"]
            if not adds and not gone:
                raise SystemExit(f"slice {s['slug']} claims nothing")
            stat = git(tmp, "diff", "--cached", "--shortstat").strip()
            tests = sorted(p for p in adds if p.startswith("tests/test_") and p.endswith(".py"))
            msg = f"{i}/{len(slices)} {s['title']}\n\n{s['body']}\n\nReview claim: {s['title']}.\nFiles: {len(adds)} added or changed, {len(gone)} removed ({stat}).\n"
            if tests:
                msg += "Test plan: python3 -m unittest " + " ".join(t[:-3].replace("/", ".") for t in tests) + "\n"
            subprocess.run(["git", "-C", tmp, "commit", "-q", "-m", msg], check=True)
            branch = f"{prefix}/{i}-{s['slug']}"
            git(repo, "branch", "-f", branch, git(tmp, "rev-parse", "HEAD").strip())
            result = ""
            if tests:
                result, rc = run_tests(tmp, tests)
                failed_tests += rc != 0
            print(f"{branch:<40} {stat:<60} {result}")
            prev = branch
        leftovers = sorted(p for p in touched if p not in claimed)
        diff = git(repo, "diff", "--stat", prev, end).strip()
        print("unclaimed changed paths:", leftovers or "none")
        print("tree difference between last slice and end:", diff or "none (identical)")
        print("slices whose own tests failed:", failed_tests)
        if leftovers or diff or failed_tests:
            return 1
        return 0
    finally:
        git(repo, "worktree", "remove", "--force", tmp)


if __name__ == "__main__":
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:6]))
