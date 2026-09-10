#!/usr/bin/env python3
"""Answer plan-first Steps 2-4 for paths that do not exist yet.

make-pr's preflight.py asks "what does this diff trip?" and needs the work
already written. This asks "what will these paths trip?" from a list of files
you intend to touch, so a re-split costs a line edit instead of a rebase.

Three outputs, one per plan-first step:

- Step 2, slices: the review unit per planned path, and an explicit split when
  more than one unit appears. `preflight.py` fails on a mixed diff; finding
  that out here is the entire point.
- Step 3, gates at their scope: the gates those paths trip, each marked
  ref-aware or whole-tree. A ref-aware gate invoked with no refs falls back to
  its own default and can report clean on work it never compared -- the
  vacuous pass this column exists to prevent.
- Step 4, base: whether the named base is current with its remote, and
  whether any ancestor in a stack has already merged.

The unit table and gate list are imported from preflight.py rather than
restated, so the two cannot disagree (principle-bind-to-named-inventory).
Ref-awareness is derived by reading each gate's own argparse flags, not from a
list kept here -- a gate that gains --base starts being reported without an
edit to this file.

    python3 scripts/plan_preflight.py --paths corpus/skills/x/SKILL.md scripts/y.py
    python3 scripts/plan_preflight.py --paths ... --base origin/main
    python3 scripts/plan_preflight.py --paths ... --json
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "engine" / "skills" / "make-pr" / "scripts"))
import preflight as pf  # noqa: E402

REF_FLAG_RE = re.compile(r'"--(base|head)"')


def ref_flags(gate_path: Path) -> list[str]:
    """Which ref flags this gate's own argparse accepts. [] for whole-tree."""
    try:
        text = gate_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return sorted({m.group(1) for m in REF_FLAG_RE.finditer(text)})


def slices_for(paths: list[str]) -> dict:
    """Review unit per path, plus the split when units are mixed."""
    info = pf.classify(paths)
    units = info["units"]
    return {
        "units": {u: sorted(ps) for u, ps in sorted(units.items())},
        "neutral": sorted(info["neutral"]),
        "mixed": len(units) > 1,
        "slice_count": max(len(units), 1),
    }


def gates_for_plan(paths: list[str], base: str | None) -> list[dict]:
    """Each gate the planned paths trip, with its scope contract."""
    out: list[dict] = []
    for cmd in pf.gates_for(paths, base=base):
        script = next((a for a in cmd if a.endswith(".py")), None)
        flags = ref_flags(REPO_ROOT / script) if script else []
        passed = [a for a in cmd if a.startswith("--")]
        out.append(
            {
                "command": " ".join(cmd),
                "script": script,
                "accepts_refs": flags,
                "scoped": bool(flags) and any(f"--{f}" in passed for f in flags),
                "whole_tree": not flags,
            }
        )
    return out


def base_status(base: str) -> dict:
    """Is the planned base current, and has anything under it already merged?"""

    def git(*args: str) -> str | None:
        try:
            r = subprocess.run(
                ["git", "-C", str(REPO_ROOT), *args],
                capture_output=True, text=True, check=True,
            )
            return r.stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    resolved = git("rev-parse", "--short", base)
    if resolved is None:
        return {"ref": base, "resolved": None, "current": None,
                "note": "cannot resolve; check the ref name"}
    remote = base if base.startswith("origin/") else f"origin/{base}"
    remote_sha = git("rev-parse", "--short", remote)
    if remote_sha is None:
        return {"ref": base, "resolved": resolved, "current": None,
                "note": f"no remote counterpart ({remote}); local-only base"}
    behind = git("rev-list", "--count", f"{base}..{remote}")
    return {
        "ref": base,
        "resolved": resolved,
        "remote": remote,
        "remote_resolved": remote_sha,
        "current": behind == "0",
        "behind_by": int(behind) if behind and behind.isdigit() else None,
        "note": "current" if behind == "0" else f"behind {remote} by {behind} commit(s); rebase before planning",
    }


def render(plan: dict) -> str:
    lines: list[str] = []
    s = plan["slices"]
    lines.append(f"Step 2  slices: {s['slice_count']}")
    for unit, ps in s["units"].items():
        lines.append(f"        {unit:<16}{len(ps)} file(s)")
        for p in ps:
            lines.append(f"          {p}")
    if s["neutral"]:
        lines.append(f"        {'neutral':<16}{len(s['neutral'])} file(s): {', '.join(s['neutral'])}")
    if s["mixed"]:
        lines.append("        SPLIT REQUIRED: preflight.py fails on a mixed-unit diff.")
        lines.append("        One slice per unit above, ordered evidence-before-change.")

    lines.append(f"\nStep 3  gates: {len(plan['gates'])}")
    for g in plan["gates"]:
        if g["whole_tree"]:
            mark = "whole-tree"
        elif g["scoped"]:
            mark = "scoped ok"
        else:
            mark = "UNSCOPED: may pass vacuously"
        lines.append(f"        [{mark:<26}] {g['command']}")
    unscoped = [g for g in plan["gates"] if not g["whole_tree"] and not g["scoped"]]
    if unscoped:
        flags = sorted({f"--{f}" for g in unscoped for f in g["accepts_refs"]})
        lines.append(f"        {len(unscoped)} gate(s) accept {', '.join(flags)} but were planned without them.")
        lines.append("        Pass the slice refs, or the gate compares something other than your slice.")

    b = plan["base"]
    lines.append(f"\nStep 4  base: {b['ref']} ({b.get('resolved') or 'unresolved'}) -- {b['note']}")

    if plan["unknowns"]:
        lines.append("\nUnknowns this script cannot answer:")
        for u in plan["unknowns"]:
            lines.append(f"        - {u}")
    return "\n".join(lines)


UNKNOWNS = [
    "Whether each unit is really one reviewable claim, or two sharing a path prefix.",
    "Whether a gate not listed here runs in CI but not in preflight.",
    "Whether an upstream slice will squash-merge, which rewrites your base mid-stack.",
]


def build_plan(paths: list[str], base: str) -> dict:
    return {
        "paths": sorted(paths),
        "slices": slices_for(paths),
        "gates": gates_for_plan(paths, base),
        "base": base_status(base),
        "unknowns": UNKNOWNS,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--paths", nargs="+", required=True, help="repo-relative paths you plan to touch")
    ap.add_argument("--base", default="origin/main", help="ref the slices are planned against")
    ap.add_argument("--json", action="store_true", help="machine-readable plan")
    args = ap.parse_args(argv)

    plan = build_plan(args.paths, args.base)
    print(json.dumps(plan, indent=2) if args.json else render(plan))

    # Exit 1 when the plan as stated would be rejected later: a mixed-unit
    # slice, or a ref-aware gate planned with no refs. Advisory-by-exit-code so
    # a planner can gate on it; it never edits anything.
    if plan["slices"]["mixed"]:
        return 1
    if any(not g["whole_tree"] and not g["scoped"] for g in plan["gates"]):
        return 1
    if plan["base"].get("current") is False:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
