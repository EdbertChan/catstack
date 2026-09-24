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
    python3 engine/skills/make-pr/scripts/preflight.py --body-file pr.md

A real run (not --paths, not --dry-run) needs --body-file: claims about the
repo's past are banned from PR descriptions, and a description nobody read is
unchecked, not clean.

Exit 0: one review unit, every gate passed. Exit 1: mixed units or a gate
failed. Exit 2: usage / no diff. Exit 3: the review-unit rules could not be read.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# engine/skills/make-pr/scripts/preflight.py -> five levels up is the repo root.
# (First real run resolved one level short, to engine/, and untracked paths
# lost their prefix; test_repo_root_contains_install_sh pins this.)
_HERE = os.path.abspath(__file__)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(_HERE), "..", "..", "..", ".."))

DEFAULT_CONFIG = os.path.join(REPO_ROOT, "drafter.config.json")
UNCHECKED_EXIT = 3
RULE_SCOPE_CHECK = "engine/skills/make-pr/scripts/rule_scope_check.py"
VALIDATOR = "engine/skills/draft-pr/scripts/validate-pr-body.mjs"
VALIDATOR_NAME = os.path.basename(VALIDATOR)
VALIDATOR_TIMEOUT = 120


class UnitRulesUnreadable(Exception):
    pass


def expand_braces(pattern: str) -> list[str]:
    match = re.search(r"\{([^{}]*)\}", pattern)
    if not match:
        return [pattern]
    head, tail = pattern[: match.start()], pattern[match.end():]
    return [p for option in match.group(1).split(",") for p in expand_braces(head + option + tail)]


def segment_regex(segment: str) -> str:
    body = "".join(
        "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch) for ch in segment
    )
    return body if segment.startswith(".") else "(?!\\.)" + body


def glob_regex(pattern: str) -> re.Pattern:
    parts = pattern.split("/")
    out = ""
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        if part == "**":
            out += "(?:(?!\\.)[^/]*(?:/(?!\\.)[^/]*)*)?" if last else "(?:(?!\\.)[^/]*/)*"
        else:
            out += segment_regex(part) + ("" if last else "/")
    return re.compile(out + "\\Z")


def read_config_text(config_path: str | None) -> tuple[str, str]:
    if config_path is None and os.path.isfile(DEFAULT_CONFIG):
        config_path = DEFAULT_CONFIG
    if config_path is not None:
        try:
            with open(config_path, encoding="utf-8") as handle:
                return config_path, handle.read()
        except OSError as exc:
            raise UnitRulesUnreadable(f"{config_path}: {exc}") from exc
    label = "origin/main:drafter.config.json"
    res = subprocess.run(["git", "show", label], capture_output=True, text=True)
    if res.returncode != 0:
        raise UnitRulesUnreadable(f"no drafter.config.json beside preflight and git show {label} failed: {res.stderr.strip()}")
    return label, res.stdout


def load_unit_rules(config_path: str | None) -> dict:
    config_path, text = read_config_text(config_path)
    try:
        config = json.loads(text)
        units = config["taxonomy"]["units"]
        path_rules = config["classification"]["pathRules"]
    except (ValueError, KeyError, TypeError) as exc:
        raise UnitRulesUnreadable(f"{config_path}: {exc}") from exc
    compiled = []
    for rule in path_rules:
        if "pathGlob" in rule:
            regexes = [glob_regex(p) for p in expand_braces(rule["pathGlob"])]
            compiled.append((lambda path, basename, rx=regexes: any(r.match(path) for r in rx), rule["unit"]))
        elif "basenamePattern" in rule:
            rx = re.compile(rule["basenamePattern"])
            compiled.append((lambda path, basename, rx=rx: bool(rx.search(basename)), rule["unit"]))
        else:
            raise UnitRulesUnreadable(f"{config_path}: path rule {rule.get('id')} has no pathGlob or basenamePattern")
    return {
        "rules": compiled,
        "productUnits": {u["id"] for u in units if u.get("isProductUnit")},
        "coLocatingUnits": {u["id"] for u in units if u.get("coLocatesWithProductUnits")},
    }


def review_units_for(path: str, rules: dict) -> list[str]:
    path = path.replace("\\", "/")
    basename = path.rsplit("/", 1)[-1]
    for matches, unit in rules["rules"]:
        if matches(path, basename):
            return list(unit)
    return []


def classify(paths: list[str], config_path: str | None = None) -> dict:
    rules = load_unit_rules(config_path)
    per_path = {p: review_units_for(p, rules) for p in paths}
    present = {u for found in per_path.values() for u in found}
    has_product_unit = bool(present & rules["productUnits"])
    ride_along = rules["coLocatingUnits"] if has_product_unit else set()
    units: dict[str, list[str]] = {}
    neutral: list[str] = []
    for p in paths:
        found = [u for u in per_path[p] if u not in ride_along]
        if not found:
            neutral.append(p)
        for u in found:
            units.setdefault(u, []).append(p)
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
    that need actual git history.

    check_skill_test_coverage.py is diff-aware: without the slice refs it
    defaults to origin/main and can report ok for a slice it never compared,
    which is a vacuous pass. So it gets --base/--head whenever `base` is real.

    check_codify_has_code.py is diff-aware the same way: with no refs it falls
    back to origin/main, so on a stacked slice a sibling's code can satisfy
    this slice's prose. Found by scripts/pr/plan_preflight.py on its first run.

    rule_scope_check.py reads the added rule lines themselves, so it needs a
    real ref and runs beside check_no_dated_provenance.py: that one catches the
    shapes of incident history, this one catches a rule whose lead sentence is
    one incident in general-looking prose.
    """
    cmds: list[list[str]] = []
    if touches_rule_prose(paths):
        # thrash-reflect-automate: a codified invariant needs code enforcing it.
        # Pass --allow-prose-only by hand (and say so in the PR) for a docs-only change.
        cmds.append(
            ["python3", "scripts/ci/check_codify_has_code.py"]
            + (["--base", base] if base is not None else [])
        )
        if base is not None:
            cmds.append(["python3", "scripts/ci/check_no_dated_provenance.py", "--base", base])
            cmds.append(["python3", RULE_SCOPE_CHECK, "--base", base])
    for hook in touched_hooks(paths):
        cmds.append(["python3", "scripts/ci/check_hook_test_coverage.py", f"engine/hooks/{hook}"])
    if touches_skills(paths):
        cmds += [
            ["python3", "scripts/ci/check_skills_three_harnesses.py"],
            ["python3", "scripts/ci/check_ecosystem_boundaries.py"],
            ["python3", "scripts/ci/check_skill_file_refs.py"],
            ["python3", "scripts/ci/check_skill_test_coverage.py"]
            + (["--base", base, "--head", "HEAD"] if base is not None else []),
            ["python3", "scripts/ci/check_skill_trigger_mechanism.py"],
            ["python3", "scripts/ci/check_skill_trigger_policy.py"],
            ["python3", "scripts/ci/check_subagent_scope_contract.py"],
            ["python3", "scripts/test/run_skill_scenarios.py"],
        ]
    python_files = [p for p in paths if p.endswith(".py") and os.path.isfile(os.path.join(REPO_ROOT, p))]
    if python_files:
        cmds.append(["ruff", "check", "--select", "E9,F"] + python_files)
    return cmds


def resolve_tool(cmd: list[str], which=None) -> list[str] | None:
    which = which if which is not None else shutil.which
    if which(cmd[0]):
        return cmd
    if cmd[0] == "ruff" and which("uvx"):
        return ["uvx"] + cmd
    return None


def changed_paths(base: str, repo: str = REPO_ROOT) -> list[str]:
    mb = subprocess.run(["git", "-C", repo, "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise SystemExit(f"cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    out = subprocess.run(["git", "-C", repo, "diff", "--name-only", mb.stdout.strip()],
                         capture_output=True, text=True, check=True).stdout
    untracked = subprocess.run(["git", "-C", repo, "ls-files", "--others", "--exclude-standard"],
                               capture_output=True, text=True, check=True).stdout
    return sorted({p for p in (out + untracked).splitlines() if p.strip()})


def validate_body(body_file: str, run=None, which=None, changed_paths: list[str] | None = None) -> tuple[int, list[str]]:
    """Run the PR-body schema validator that the required PR Body check runs.

    description_check only reads the prose for history claims, so a body whose
    Test Plan is not inside a <details> block passed preflight and then failed
    the required check after publication (PRs #780-#789, #793, #795). Exit 1
    from the validator is a real rejection; anything else -- no node, a
    timeout, an unexpected exit code -- is unchecked, which also fails.
    """
    run = run if run is not None else subprocess.run
    which = which if which is not None else shutil.which
    if not which("node"):
        return 1, [f"description unchecked: node is not on PATH, so {VALIDATOR_NAME} did not run"]
    if not os.path.isfile(os.path.join(REPO_ROOT, VALIDATOR)):
        return 1, [f"description unchecked: no {VALIDATOR} under {REPO_ROOT}"]
    with tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        files_file = os.path.join(tmp, "changed-files.txt")
        with open(files_file, "w", encoding="utf-8") as handle:
            handle.writelines(p + "\n" for p in changed_paths or [])
        cmd = ["node", VALIDATOR, "--body-file", os.path.abspath(body_file), "--changed-files-file", files_file]
        try:
            res = run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=VALIDATOR_TIMEOUT)
        except subprocess.TimeoutExpired:
            return 1, [f"description unchecked: {VALIDATOR_NAME} did not finish in {VALIDATOR_TIMEOUT}s"]
        except OSError as exc:
            return 1, [f"description unchecked: cannot run {VALIDATOR_NAME}: {exc}"]
    lines = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode in (0, 1):
        return res.returncode, lines
    return 1, lines + [f"description unchecked: {VALIDATOR_NAME} exited {res.returncode}"]


def describe(body_file: str | None, changed_paths: list[str]) -> int:
    if not body_file:
        print("fail    description unchecked: pass --body-file with the PR description")
        return 1
    try:
        with open(body_file, encoding="utf-8") as handle:
            body = handle.read()
    except OSError as exc:
        print(f"fail    description unchecked: cannot read {body_file}: {exc}")
        return 1
    import description_check

    print("gate    description_check " + body_file)
    outcome, lines = description_check.check(body)
    for line in lines:
        print("        " + line)
    print(f"        description {outcome}")
    status = 0 if outcome == "clean" else 1

    print(f"gate    node {VALIDATOR} --body-file {body_file} --changed-files-file <{len(changed_paths)} changed path(s)>")
    schema_status, schema_lines = validate_body(body_file, changed_paths=changed_paths)
    for line in schema_lines:
        print("        " + line)
    return status or schema_status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--paths", nargs="*", help="classify these paths instead of reading git")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, do not run gates")
    ap.add_argument("--body-file", help="the PR description to check for claims about the repo's past")
    ap.add_argument(
        "--config", default=None,
        help="drafter.config.json holding the review-unit rules (default: beside this script, else origin/main's copy)",
    )
    args = ap.parse_args(argv)

    paths = args.paths if args.paths is not None else changed_paths(args.base)
    if not paths:
        print("no changed files vs " + args.base, file=sys.stderr)
        return 2
    try:
        info = classify(paths, args.config)
    except UnitRulesUnreadable as exc:
        print(f"fail    unchecked review units: {exc}")
        print("fail    preflight: fix the above before gh pr create")
        return UNCHECKED_EXIT
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
        print("fail    more than one review unit in one PR; validate-pr-body.mjs rejects every declared unit. One PR per unit:")
        status = 1
    if len(units) > 1:
        for unit, files in sorted(units.items()):
            print(f"split     {unit}: " + ", ".join(files))
    elif len(units) == 1:
        print("declare Review Unit: " + next(iter(units)))

    cmds = gates_for(paths, base=None if args.paths is not None else args.base)
    if not cmds:
        print("gates   none required for these paths")
    for cmd in cmds:
        print("gate    " + " ".join(cmd))
        if args.dry_run:
            continue
        runnable = resolve_tool(cmd)
        if runnable is None:
            print(f"fail    {cmd[0]} unchecked: neither {cmd[0]} nor uvx is on PATH, so this gate did not run")
            status = 1
            continue
        res = subprocess.run(runnable, cwd=REPO_ROOT, capture_output=True, text=True)
        tail = (res.stdout + res.stderr).strip().splitlines()
        for line in tail[-6:]:
            print("        " + line)
        if res.returncode != 0:
            status = 1
    if args.paths is None and not args.dry_run:
        if describe(args.body_file, paths) != 0:
            status = 1
    print("ok      preflight passed" if status == 0 else "fail    preflight: fix the above before gh pr create")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
