"""Cut the difference between a base branch and an end branch into a stack of review branches, one claim each.

Usage: python3 build_review_stack.py <repo> <base> <end> <branch-prefix> <slices.json>

slices.json is a list, in dependency order, of {"slug", "title", "body", "globs": [...], "removals": [...], "changes": [...]}.
Each slice takes the paths matching its globs from the end tree (a path goes to the first slice that matches it),
removes paths the end tree no longer has that match its removals, and commits on top of the previous slice as
<branch-prefix>/<n>-<slug>. A path the base already has that the slice modifies must match the slice's changes, so a
stack that was meant to be additions only cannot rewrite a base file unnoticed. The last slice's tree must be
identical to the end tree and every changed path must be claimed by some slice; otherwise the script exits 1. A
slice's own tests (tests/test_*.py among its paths) are run with unittest on that slice and the result is printed
next to it. Branches under <branch-prefix>/ that this build did not produce are deleted, so a page can never point
at a branch from an older cut. The build writes meta.json next to slices.json: the branch list, and one entry per
slice with label, base (the previous head) and head set, keeping any prose fields already filled in.
"""
import fnmatch
import json
import os
import subprocess
import sys
import tempfile

PROSE_FIELDS = ("lane", "claim", "safety", "rationale", "effect", "alternatives", "non_goals", "technique")


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
        s.setdefault("changes", [])
    return slices


def matches(path, globs):
    return any(fnmatch.fnmatch(path, glob) for glob in globs)


def run_tests(cwd, tests):
    r = subprocess.run([sys.executable, "-m", "unittest", *[t[:-3].replace("/", ".") for t in tests]], cwd=cwd,
                       capture_output=True, text=True)
    tail = [l for l in (r.stdout + r.stderr).splitlines() if l.startswith(("Ran ", "OK", "FAILED"))]
    return " | ".join(tail) + f" | rc={r.returncode}", r.returncode


def prune_prefix(repo, prefix, built):
    names = git(repo, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{prefix}/").split()
    stale = [name for name in names if name not in built]
    for name in stale:
        try:
            git(repo, "branch", "-D", name)
        except subprocess.CalledProcessError as error:
            raise SystemExit(f"could not delete stale branch {name}: {error.stderr.strip()}")
    return stale


def existing_prose(meta_path):
    try:
        loaded = json.load(open(meta_path))
    except FileNotFoundError:
        print(f"no {meta_path} yet: writing a blank skeleton")
        return {}
    entries = loaded.get("slices", []) if isinstance(loaded, dict) else loaded
    return {entry.get("slug", entry.get("label")): entry for entry in entries}


def write_meta(meta_path, base, end, prefix, built, slices):
    kept = existing_prose(meta_path)
    entries, previous = [], base
    for slice_spec, branch in zip(slices, built):
        entry = dict(kept.get(slice_spec["slug"], {}))
        entry.update({"slug": slice_spec["slug"], "label": slice_spec["title"], "base": previous, "head": branch})
        for field in PROSE_FIELDS:
            entry.setdefault(field, "")
        entries.append(entry)
        previous = branch
    record = {"base": base, "end": end, "prefix": prefix, "branches": built, "slices": entries}
    json.dump(record, open(meta_path, "w"), indent=1)


def main(repo, base, end, prefix, slices_path):
    slices = load_slices(slices_path)
    changed = [l.split("\t") for l in git(repo, "diff", "--name-status", "--no-renames", f"{base}..{end}").splitlines()]
    end_paths = set(git(repo, "ls-tree", "-r", "--name-only", end).splitlines())
    touched = {parts[1]: parts[0][0] for parts in changed}
    claimed = {}
    undeclared = []
    built = []
    tmp = tempfile.mkdtemp(prefix="review-stack-")
    git(repo, "worktree", "add", "-q", "--detach", tmp, base)
    failed_tests = 0
    try:
        prev = base
        for i, s in enumerate(slices, 1):
            adds = [p for p in end_paths if matches(p, s["globs"]) and p in touched and p not in claimed]
            current = set(git(tmp, "ls-files").splitlines())
            gone = [p for p in current if p not in end_paths and matches(p, s["removals"]) and p not in claimed]
            for p in adds:
                git(tmp, "checkout", end, "--", p)
                claimed[p] = s["slug"]
                if touched[p] == "M" and not matches(p, s["changes"]):
                    undeclared.append(f"{s['slug']}: {p}")
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
            built.append(branch)
            result = ""
            if tests:
                result, rc = run_tests(tmp, tests)
                failed_tests += rc != 0
            print(f"{branch:<40} {stat:<60} {result}")
            prev = branch
        leftovers = sorted(p for p in touched if p not in claimed)
        diff = git(repo, "diff", "--stat", prev, end).strip()
        stale = prune_prefix(repo, prefix, built)
        meta_path = os.path.join(os.path.dirname(os.path.abspath(slices_path)), "meta.json")
        write_meta(meta_path, base, end, prefix, built, slices)
        modified = sorted(p for p, status in touched.items() if status == "M")
        deleted = sorted(p for p, status in touched.items() if status == "D")
        print("unclaimed changed paths:", leftovers or "none")
        print("tree difference between last slice and end:", diff or "none (identical)")
        print("slices whose own tests failed:", failed_tests)
        print(f"paths on {base} the stack modifies: {len(modified)}; deletes: {len(deleted)}")
        print("modified base paths no slice declares in its changes:", undeclared or "none")
        print(f"stale {prefix}/ branches deleted:", stale or "none")
        print(f"wrote {meta_path}: {len(built)} slices; fill the prose fields, leave base and head alone")
        if leftovers or diff or failed_tests or undeclared:
            return 1
        return 0
    finally:
        git(repo, "worktree", "remove", "--force", tmp)


if __name__ == "__main__":
    if len(sys.argv) != 6:
        raise SystemExit(__doc__)
    sys.exit(main(*sys.argv[1:6]))
