#!/usr/bin/env python3
"""make-pr preflight: derive the review unit and run the repo gates from the diff.

The make-pr skill's path-to-review-unit table and its "run this checker for
every touched hook / skill" prose were a lookup over `git diff --name-only`.
This script does the lookup and runs the gates, so the agent pastes one
output instead of re-deriving the table.

    python3 engine/skills/make-pr/scripts/preflight.py                 # diff vs origin/main
    python3 engine/skills/make-pr/scripts/preflight.py --base main
    python3 engine/skills/make-pr/scripts/preflight.py --paths a b c   # classify only, no git
    python3 engine/skills/make-pr/scripts/preflight.py --dry-run       # print the plan, run nothing

Exit 0: one review unit, every gate passed. Exit 1: mixed units or a gate
failed. Exit 2: usage / no diff.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

# engine/skills/make-pr/scripts/preflight.py -> five levels up is the repo root.
# (First real run resolved one level short, to engine/, and untracked paths
# lost their prefix; test_repo_root_contains_install_sh pins this.)
_HERE = os.path.abspath(__file__)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(_HERE), "..", "..", "..", ".."))

# Mirrors drafter.config.json classification.pathRules (first match wins):
# corpus/skills -> corpus-lesson, product/skills -> product-skill,
# engine|scripts|.github + install.sh/drafter.config.json -> engine-runtime.
# Repo-root tests/ and docs/ are proof/docs units that co-locate, so they are
# neutral here.
UNIT_RULES = (
    ("corpus/skills/", "corpus-lesson"),
    ("product/skills/", "product-skill"),
    ("engine/", "engine-runtime"),
    ("scripts/", "engine-runtime"),
    (".github/", "engine-runtime"),
)
ROOT_ENGINE_FILES = {"install.sh", "drafter.config.json"}


def review_unit_for(path: str) -> str | None:
    if path in ROOT_ENGINE_FILES:
        return "engine-runtime"
    if path == "scripts/skill_test_debt_allowlist.txt":
        return None
    for prefix, unit in UNIT_RULES:
        if path.startswith(prefix):
            return unit
    return None


def classify(paths: list[str]) -> dict:
    units: dict[str, list[str]] = {}
    neutral: list[str] = []
    for p in paths:
        u = review_unit_for(p)
        (units.setdefault(u, []) if u else neutral).append(p)
    return {"units": units, "neutral": neutral}


def touched_hooks(paths: list[str]) -> list[str]:
    hooks = set()
    for p in paths:
        parts = p.split("/")
        if len(parts) >= 3 and parts[0] == "engine" and parts[1] == "hooks":
            hooks.add(parts[2])
    return sorted(hooks)


def touches_skills(paths: list[str]) -> bool:
    return any(p.startswith(("engine/skills/", "corpus/skills/", "product/skills/")) for p in paths)


PROSE_RULE_PREFIXES = ("engine/skills/", "corpus/skills/", "product/skills/", "always-on/", "cursor/", "commands/")


def touches_rule_prose(paths: list[str]) -> bool:
    return any(p.endswith(".md") and (p.startswith(PROSE_RULE_PREFIXES) or p == "CLAUDE.md") for p in paths)


def gates_for(paths: list[str], base: str | None = None) -> list[list[str]]:
    """Commands to run, in order. Paths are repo-relative. `base` is the real
    git ref being diffed against; omit it (e.g. under --paths) to skip gates
    that need actual git history."""
    cmds: list[list[str]] = []
    if touches_rule_prose(paths):
        # thrash-reflect-automate: a codified invariant needs code enforcing it.
        # Pass --allow-prose-only by hand (and say so in the PR) for a docs-only change.
        cmds.append(["python3", "scripts/check_codify_has_code.py"])
        if base is not None:
            cmds.append(["python3", "scripts/check_no_dated_provenance.py", "--base", base])
    for hook in touched_hooks(paths):
        cmds.append(["python3", "scripts/check_hook_test_coverage.py", f"engine/hooks/{hook}"])
    if touches_skills(paths):
        cmds += [
            ["python3", "scripts/check_skills_three_harnesses.py"],
            ["python3", "scripts/check_ecosystem_boundaries.py"],
            ["python3", "scripts/check_skill_file_refs.py"],
            ["python3", "scripts/check_skill_test_coverage.py"],
            ["python3", "scripts/check_skill_trigger_mechanism.py"],
        ]
    return cmds


def changed_paths(base: str, repo: str = REPO_ROOT) -> list[str]:
    mb = subprocess.run(["git", "-C", repo, "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise SystemExit(f"cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    out = subprocess.run(["git", "-C", repo, "diff", "--name-only", mb.stdout.strip()],
                         capture_output=True, text=True, check=True).stdout
    untracked = subprocess.run(["git", "-C", repo, "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True, check=True).stdout
    return sorted({p for p in (out + untracked).splitlines() if p.strip()})


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--paths", nargs="*", help="classify these paths instead of reading git")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, do not run gates")
    args = ap.parse_args(argv)

    paths = args.paths if args.paths is not None else changed_paths(args.base)
    if not paths:
        print("no changed files vs " + args.base, file=sys.stderr)
        return 2
    info = classify(paths)
    units = info["units"]
    for unit, files in sorted(units.items()):
        print(f"unit    {unit}: {len(files)} file(s)")
    if info["neutral"]:
        print(f"neutral {len(info['neutral'])} file(s): " + ", ".join(info["neutral"][:6]) + (" ..." if len(info["neutral"]) > 6 else ""))
    status = 0
    if "engine-runtime" in units and "corpus-lesson" in units:
        print("fail    engine-runtime and corpus-lesson mixed in one PR (docs/ecosystem.md): split the slice")
        status = 1
    elif len(units) > 1:
        print("warn    more than one review unit; declare the dominant one and justify the other in Slice Rationale")
    elif len(units) == 1:
        print("declare Review Unit: " + next(iter(units)))

    cmds = gates_for(paths, base=None if args.paths is not None else args.base)
    if not cmds:
        print("gates   none required for these paths")
    for cmd in cmds:
        print("gate    " + " ".join(cmd))
        if args.dry_run:
            continue
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
        tail = (res.stdout + res.stderr).strip().splitlines()
        for line in tail[-6:]:
            print("        " + line)
        if res.returncode != 0:
            status = 1
    print("ok      preflight passed" if status == 0 else "fail    preflight: fix the above before gh pr create")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
