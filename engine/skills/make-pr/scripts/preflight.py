#!/usr/bin/env python3
"""make-pr preflight: derive the review unit and run the repo gates from the diff.

The make-pr skill's path-to-review-unit table and its "run this checker for
every touched hook / skill" prose were a lookup over `git diff --name-only`.
This script does the lookup and runs the gates, so the agent pastes one
output instead of re-deriving the table.

    python3 engine/skills/make-pr/scripts/preflight.py
    python3 engine/skills/make-pr/scripts/preflight.py --base main
    python3 engine/skills/make-pr/scripts/preflight.py --commit-only
    python3 engine/skills/make-pr/scripts/preflight.py --staged
    python3 engine/skills/make-pr/scripts/preflight.py --include-untracked
    python3 engine/skills/make-pr/scripts/preflight.py --paths a b c
    python3 engine/skills/make-pr/scripts/preflight.py --dry-run
    python3 engine/skills/make-pr/scripts/preflight.py --body-file pr.md
    python3 engine/skills/make-pr/scripts/preflight.py --body-file pr.md --all

Classification defaults to committed paths vs the merge-base so untracked
junk cannot expand the review unit. Pass --staged to add the index, or
--include-untracked for the old merge (fails when untracked count is high
unless --paths is set). A real run (not --paths, not --dry-run) needs
--body-file: claims about the repo's past are banned from PR descriptions,
and a description nobody read is unchecked, not clean.

The default and --commit-only both ignore untracked files. --paths classifies
only the paths passed on the command line. --dry-run prints the plan without
running gates. --all runs the diff gates plus description_check.py,
rule_scope_check.py and the draft-pr body validators against --body-file,
one `gate <name>: pass|fail|unchecked (<reason>)` line per gate; a gate whose
runtime is missing is unchecked, never pass, and any fail or unchecked exits 1.

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
UNTRACKED_LIMIT = 10
RULE_SCOPE_CHECK = "engine/skills/make-pr/scripts/rule_scope_check.py"
DESCRIPTION_CHECK = "engine/skills/make-pr/scripts/description_check.py"
VALIDATOR = "engine/skills/draft-pr/scripts/validate-pr-body.mjs"
VALIDATOR_NAME = os.path.basename(VALIDATOR)
VALIDATOR_TIMEOUT = 120
MEASURED_SECTION = "engine/skills/draft-pr/scripts/measured-section.mjs"
NOT_RUN_BLOCKER = "engine/skills/draft-pr/scripts/not-run-blocker.mjs"
ALL_GATE_TIMEOUT = 600
GATE_STATUSES = ("pass", "fail", "unchecked")

MEASURED_SECTION_RUNNER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [script, bodyFile] = process.argv.slice(1);
const { checkMeasured, measuredError, measuredNote } = await import(pathToFileURL(script).href);
const result = checkMeasured(readFileSync(bodyFile, 'utf-8'));
const note = measuredNote(result);
if (note) console.error(note);
if (result.status === 'hard') { console.error(measuredError(result)); process.exit(1); }
console.log(result.form === 'none' ? 'Measured says none: with a reason.' : 'Measured has a base row and a head row with output.');
"""

NOT_RUN_BLOCKER_RUNNER = """
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const [script, bodyFile] = process.argv.slice(1);
const { checkNotRunRows, notRunError, notRunNote } = await import(pathToFileURL(script).href);
const result = checkNotRunRows(readFileSync(bodyFile, 'utf-8'));
const note = notRunNote(result);
if (note) console.error(note);
if (result.status === 'hard') { console.error(notRunError(result)); process.exit(1); }
if (result.status === 'unchecked') process.exit(2);
console.log(`Test Plan has ${result.rows} Not run row(s), each naming a blocker.`);
"""


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


def list_untracked(repo: str = REPO_ROOT) -> list[str]:
    out = subprocess.run(
        ["git", "-C", repo, "ls-files", "--others", "--exclude-standard"],
        capture_output=True, text=True, check=True,
    ).stdout
    return [p for p in out.splitlines() if p.strip()]


def changed_paths(
    base: str,
    repo: str = REPO_ROOT,
    *,
    include_untracked: bool = False,
    staged: bool = False,
) -> list[str]:
    """Paths that define the review unit.

    Default is commit-scoped: ``git diff --name-only <merge-base>`` only.
    Untracked files are excluded so parking-lot junk cannot mix review units.
    ``staged=True`` also includes the index. ``include_untracked=True`` restores
    the old merge; callers that need that must park or pass ``--paths`` when
    untracked count exceeds ``UNTRACKED_LIMIT``.
    """
    mb = subprocess.run(["git", "-C", repo, "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise SystemExit(f"cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    out = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", mb.stdout.strip()],
        capture_output=True, text=True, check=True,
    ).stdout
    paths = {p for p in out.splitlines() if p.strip()}
    if staged:
        cached = subprocess.run(
            ["git", "-C", repo, "diff", "--cached", "--name-only"],
            capture_output=True, text=True, check=True,
        ).stdout
        paths.update(p for p in cached.splitlines() if p.strip())
    if include_untracked:
        untracked = list_untracked(repo)
        if len(untracked) > UNTRACKED_LIMIT:
            raise SystemExit(
                f"untracked count {len(untracked)} exceeds {UNTRACKED_LIMIT}: "
                "park unrelated files or pass --paths / --commit-only / --staged"
            )
        paths.update(untracked)
    return sorted(paths)


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


def body_gates(body_file: str, base: str, changed_files_file: str) -> list[list[str]]:
    """The commands --all runs against the body, in report order."""
    body = os.path.abspath(body_file)
    return [
        ["python3", DESCRIPTION_CHECK, body],
        ["python3", RULE_SCOPE_CHECK, "--base", base],
        ["node", VALIDATOR, "--body-file", body, "--changed-files-file", changed_files_file],
        ["node", "--input-type=module", "-e", MEASURED_SECTION_RUNNER, MEASURED_SECTION, body],
        ["node", "--input-type=module", "-e", NOT_RUN_BLOCKER_RUNNER, NOT_RUN_BLOCKER, body],
    ]


def all_gate_commands(diff_gates: list[list[str]], body_file: str, base: str, changed_files_file: str) -> list[list[str]]:
    """Diff gates then body gates, with the rule-scope check run once."""
    kept = [cmd for cmd in diff_gates if RULE_SCOPE_CHECK not in cmd]
    return kept + body_gates(body_file, base, changed_files_file)


def gate_script(cmd: list[str]) -> str | None:
    """The repo-relative script an interpreter gate runs; None for a tool such as ruff."""
    if cmd[0] not in ("python3", "node"):
        return None
    return next((part for part in cmd[1:] if part.endswith((".py", ".mjs"))), None)


def gate_name(cmd: list[str]) -> str:
    """The report name of a gate: its script's basename, else its tool."""
    script = gate_script(cmd)
    return os.path.basename(script) if script else cmd[0]


def display(cmd: list[str]) -> str:
    """The command line as printed, with an inline module shown as a placeholder."""
    return " ".join("<inline module>" if "\n" in part else part for part in cmd)


def last_line(stdout: str, stderr: str, returncode: int) -> str:
    """The gate's own last word: the last stdout line, else the last stderr line."""
    for stream in (stdout, stderr):
        lines = stream.strip().splitlines()
        if lines:
            return lines[-1].strip()
    return f"exited {returncode} with no output"


def run_gate(cmd: list[str], run=None, which=None, timeout: int = ALL_GATE_TIMEOUT) -> tuple[str, str, list[str]]:
    """Run one gate and return (status, reason, output tail); status is pass, fail or unchecked."""
    run = run if run is not None else subprocess.run
    runnable = resolve_tool(cmd, which=which)
    if runnable is None:
        return "unchecked", f"{cmd[0]} is not on PATH, so {gate_name(cmd)} did not run", []
    script = gate_script(cmd)
    if script is not None and not os.path.isfile(os.path.join(REPO_ROOT, script)):
        return "unchecked", f"no {script} under {REPO_ROOT}", []
    try:
        res = run(runnable, cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "unchecked", f"{gate_name(cmd)} did not finish in {timeout}s", []
    except OSError as exc:
        return "unchecked", f"cannot run {gate_name(cmd)}: {exc}", []
    tail = (res.stdout + res.stderr).strip().splitlines()
    reason = last_line(res.stdout, res.stderr, res.returncode)
    if res.returncode == 0:
        return "pass", reason, tail
    if res.returncode == 1:
        return "fail", reason, tail
    return "unchecked", f"exited {res.returncode}: {reason}", tail


def report_all(diff_gates: list[list[str]], paths: list[str], body_file: str, base: str, dry_run: bool) -> int:
    """Run every gate and print one line each; 1 when any gate is not a pass."""
    status = 0
    with tempfile.TemporaryDirectory(prefix="preflight-") as tmp:
        files_file = os.path.join(tmp, "changed-files.txt")
        with open(files_file, "w", encoding="utf-8") as handle:
            handle.writelines(p + "\n" for p in paths)
        for cmd in all_gate_commands(diff_gates, body_file, base, files_file):
            if dry_run:
                print("gate    " + display(cmd))
                continue
            outcome, reason, tail = run_gate(cmd)
            print(f"gate {gate_name(cmd)}: {outcome} ({reason})")
            if outcome != "pass":
                status = 1
                for line in tail[-6:]:
                    print("        " + line)
    return status


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
        "--all", action="store_true",
        help="run the diff gates plus description_check.py, rule_scope_check.py and the draft-pr body "
             "validators against --body-file; one `gate <name>: pass|fail|unchecked` line per gate",
    )
    ap.add_argument(
        "--commit-only", action="store_true",
        help="classify committed paths only (default when not using --paths / --staged / --include-untracked)",
    )
    ap.add_argument(
        "--staged", action="store_true",
        help="classify committed paths plus the index (still ignores untracked)",
    )
    ap.add_argument(
        "--include-untracked", action="store_true",
        help="also merge untracked files; fails when untracked count exceeds UNTRACKED_LIMIT",
    )
    ap.add_argument(
        "--config", default=None,
        help="drafter.config.json holding the review-unit rules (default: beside this script, else origin/main's copy)",
    )
    args = ap.parse_args(argv)

    if args.paths is not None and (args.commit_only or args.staged or args.include_untracked):
        print("fail    --paths cannot combine with --commit-only / --staged / --include-untracked", file=sys.stderr)
        return 2
    if args.include_untracked and args.commit_only:
        print("fail    --include-untracked cannot combine with --commit-only", file=sys.stderr)
        return 2
    if args.all and args.paths is not None:
        print("fail    --all reads the real diff, so it cannot combine with --paths", file=sys.stderr)
        return 2
    if args.all and not args.body_file:
        print("fail    --all needs --body-file with the PR description", file=sys.stderr)
        return 2
    if args.all and not os.path.isfile(args.body_file):
        print(f"fail    --all: cannot read {args.body_file}", file=sys.stderr)
        return 2

    if args.paths is not None:
        paths = args.paths
    else:
        try:
            paths = changed_paths(
                args.base,
                include_untracked=args.include_untracked,
                staged=args.staged,
            )
        except SystemExit as exc:
            print(f"fail    {exc}", file=sys.stderr)
            return 2
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
    if args.all:
        if report_all(cmds, paths, args.body_file, args.base, args.dry_run) != 0:
            status = 1
        print("ok      preflight passed" if status == 0 else "fail    preflight: fix the above before gh pr create")
        return status
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
