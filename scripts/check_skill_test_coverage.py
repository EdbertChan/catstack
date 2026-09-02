#!/usr/bin/env python3
"""Every skill MUST ship and update test coverage with each skill change.

Companion to check_hook_test_coverage.py -- reuses the exact same
positive/negative name heuristic so authors do not learn a second
vocabulary (same rationale as check_mine_repro_coverage.py).

Two shapes, depending on whether the skill has executable code:

- Code skills (a `scripts/` dir, or any .py/.mjs/.js/.ts/.sh file outside
  a `tests/` dir): need at least two real test functions, found either in
  a `tests/` dir anywhere under the skill (e.g. reflect's lives at
  scripts/tests/), OR hand-listed in `TOP_LEVEL_TEST_FILES` below for a
  skill whose real tests predate this gate and live in the repo-wide
  `tests/` dir instead of colocated (e.g. `tests/test_cat_mode.py` for
  cat-mode) -- this counts them rather than demanding a duplicate.
  Unlike a hook's detect.py, most skill code is not a fire/stay-silent
  detector, so this does not force the hook-specific positive/negative
  vocabulary onto it -- it just requires non-trivial coverage exists.
  (Verified against this repo's own code skills: forcing the hook
  keyword list here produced false negatives on independent-judge-swarm's
  and reflect's real, already-adequate test suites, since their test
  names describe fixtures/fails-closed cases rather than fire/block/detect.)
- Prose-only skills (everything else): need a `tests/` dir containing at
  least one file matching a positive pattern and one matching a negative
  pattern -- e.g. tests/fires_example.md / tests/stays_silent_example.md,
  each holding a short example prompt/scenario showing the skill should
  (or should not) activate. This DOES reuse the positive/negative
  vocabulary, because "should this activate" genuinely is a fire/stay-
  silent question for a skill. Pick filenames carefully: they're
  classified by the same substring heuristic as hook detector tests
  (check_hook_test_coverage.POSITIVE_RE / NEGATIVE_RE), so e.g.
  "trigger_positive.md" and "trigger_negative.md" would BOTH classify as
  positive (both contain "trigger", a positive keyword, and neither
  matches a negative keyword) -- this only checks the shape exists by
  name, it cannot judge whether the fixture actually reproduces the
  right scenario. That judgment is still the author's.

A skill listed in scripts/skill_test_debt_allowlist.txt is grandfathered
(skipped) -- see check_skill_test_debt_no_growth.py for the gate that
keeps that list shrink-only.

Usage:
    python3 scripts/check_skill_test_coverage.py            # check every skill
    python3 scripts/check_skill_test_coverage.py --base <ref> [--head <ref>]
    python3 scripts/check_skill_test_coverage.py --list-missing   # print all
        skills lacking coverage, ignoring the allowlist (used to bootstrap it)
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
import check_hook_test_coverage as hook_coverage  # noqa: E402
import check_skill_test_debt_no_growth as debt_gate  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_BUCKETS = ("engine/skills", "corpus/skills", "product/skills")
ALLOWLIST_PATH = REPO_ROOT / "scripts" / "skill_test_debt_allowlist.txt"

CODE_SUFFIXES = frozenset({".py", ".mjs", ".js", ".ts", ".sh"})
SKIP_DIR_NAMES = frozenset({"tests", "__pycache__", ".git"})


def _skill_dirs(root: Path) -> list[Path]:
    out: list[Path] = []
    for bucket in SKILL_BUCKETS:
        bucket_path = root / bucket
        if not bucket_path.is_dir():
            continue
        out.extend(sorted(p for p in bucket_path.iterdir() if p.is_dir()))
    return out


def _has_code(skill_dir: Path) -> bool:
    for dirpath, dirnames, filenames in os.walk(skill_dir):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIR_NAMES]
        for fname in filenames:
            if Path(fname).suffix in CODE_SUFFIXES:
                return True
    return False


def _tests_dirs(skill_dir: Path) -> list[Path]:
    return [p for p in skill_dir.rglob("tests") if p.is_dir() and p.name == "tests"]


def _test_functions_in_file(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return []
    return [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
    ]


# Skills whose real tests predate this gate and live in the repo-wide
# tests/ dir instead of colocated under the skill. Hand-verified, not
# auto-detected: string-matching a skill's name against arbitrary test
# source is too easy to false-positive on an unrelated fixture that just
# happens to reuse a real skill's name as an example (e.g.
# tests/test_ecosystem_boundaries.py uses "cat-mode" as a synthetic
# fixture name for an unrelated checker's own tests). Add an entry here
# only after confirming the named file(s) actually exercise that skill's
# own code, not merely mention its name.
TOP_LEVEL_TEST_FILES: dict[str, tuple[str, ...]] = {
    "cat-mode": ("test_cat_mode.py", "test_execution_routing.py"),
    "show-me-your-work": ("test_show_me_your_work.py",),
}


def _top_level_test_names(root: Path, skill_name: str) -> list[str]:
    """Real tests for a skill sometimes live in the repo-wide tests/ dir
    instead of colocated under the skill -- count them via the
    hand-verified TOP_LEVEL_TEST_FILES mapping rather than guessing."""
    tests_dir = root / "tests"
    names: list[str] = []
    for fname in TOP_LEVEL_TEST_FILES.get(skill_name, ()):
        f = tests_dir / fname
        if f.is_file():
            names.extend(_test_functions_in_file(f))
    return names


def _classified_names(names: list[str]) -> set[str | None]:
    return {hook_coverage._classify(n) for n in names}


def _fixture_names(tests_dir: Path) -> list[str]:
    return [p.stem for p in sorted(tests_dir.iterdir()) if p.is_file()]


def _changed_skill(path: str) -> tuple[str, str] | None:
    """Return ``(skill_rel, skill_name)`` for changed non-test skill files."""
    parts = Path(path).parts
    if len(parts) < 4 or "/".join(parts[:2]) not in SKILL_BUCKETS:
        return None
    if "tests" in parts[3:]:
        return None
    return "/".join(parts[:3]), parts[2]


RULE_RE = re.compile(
    r"\b(MUST( NOT)?|never|do(es)? not|don't|cannot|always|only|required|"
    r"fail(s)? closed|gate|invariant|block(s|ed)?|exit 2)\b",
    re.I,
)


def _adds_rule_line(md_paths: list[str], base_ref: str, head_ref: str, cwd: str | Path) -> bool:
    """True if the markdown diff adds a rule-shaped line (or the diff fails: fail closed)."""
    result = subprocess.run(
        ["git", "diff", "-U0", f"{base_ref}...{head_ref}", "--", *md_paths],
        cwd=str(cwd), capture_output=True, text=True,
    )
    if result.returncode != 0:
        return True
    return any(
        line.startswith("+") and not line.startswith("+++") and RULE_RE.search(line)
        for line in result.stdout.splitlines()
    )


def changed_skill_test_errors(
    changed_paths: list[str],
    base_ref: str | None = None,
    head_ref: str = "HEAD",
    cwd: str | Path = REPO_ROOT,
) -> list[str]:
    """Require every changed skill slice to change tests too -- unless the
    change is markdown-only and adds no rule-shaped line (pointer sentences,
    link fixes). Needs ``base_ref`` to diff; without it the exemption is off."""
    changed = {Path(path).as_posix() for path in changed_paths}
    touched: dict[str, str] = {}
    for path in sorted(changed):
        skill = _changed_skill(path)
        if skill:
            touched[skill[0]] = skill[1]

    errors: list[str] = []
    for skill_rel, skill_name in sorted(touched.items()):
        colocated_prefix = f"{skill_rel}/"
        colocated_changed = any(
            path.startswith(colocated_prefix)
            and "tests" in Path(path).parts[3:]
            for path in changed
        )
        mapped = tuple(f"tests/{name}" for name in TOP_LEVEL_TEST_FILES.get(skill_name, ()))
        mapped_changed = any(path in changed for path in mapped)
        if colocated_changed or mapped_changed:
            continue
        files = [p for p in changed if p.startswith(colocated_prefix) and "tests" not in Path(p).parts[3:]]
        if base_ref and all(f.endswith(".md") for f in files) and not _adds_rule_line(files, base_ref, head_ref, cwd):
            continue
        if mapped:
            expected = f"expected one of: {', '.join(mapped)}"
        else:
            expected = f"expected a changed file under {skill_rel}/**/tests/"
        errors.append(
            f"{skill_rel}: changed without a corresponding test change ({expected})"
        )
    return errors


def changed_paths_between(
    base_ref: str,
    head_ref: str = "HEAD",
    cwd: str | Path = REPO_ROOT,
) -> list[str] | None:
    merge_base = subprocess.run(
        ["git", "merge-base", base_ref, head_ref],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        return None
    result = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=AM",
            merge_base.stdout.strip(),
            head_ref,
        ],
        cwd=str(cwd),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def load_allowlist(path: Path | None = None) -> set[str]:
    p = path or ALLOWLIST_PATH
    if not p.is_file():
        return set()
    lines = p.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.strip().startswith("#")}


def check(repo_root: Path | None = None, allowlist: set[str] | None = None) -> list[str]:
    """Return a list of problem strings, one per uncovered non-allowlisted skill."""
    root = repo_root or REPO_ROOT
    debt = load_allowlist() if allowlist is None else allowlist
    errors: list[str] = []
    for skill_dir in _skill_dirs(root):
        rel = skill_dir.relative_to(root).as_posix()
        if rel in debt:
            continue
        tests_dirs = _tests_dirs(skill_dir)
        if _has_code(skill_dir):
            names: list[str] = []
            for td in tests_dirs:
                names.extend(hook_coverage._test_names(str(td)))
            names.extend(_top_level_test_names(root, skill_dir.name))
            if len(names) < 2:
                errors.append(
                    f"{rel}: has code but fewer than 2 real tests/ test "
                    f"functions found ({len(names)})"
                )
        else:
            names = []
            for td in tests_dirs:
                names.extend(_fixture_names(td))
            classified = _classified_names(names)
            if "positive" not in classified or "negative" not in classified:
                errors.append(
                    f"{rel}: prose skill has no tests/ with a positive + negative "
                    "trigger fixture (e.g. tests/fires_example.md, "
                    f"tests/stays_silent_example.md) (found: {sorted(n for n in classified if n)})"
                )
    return errors


def stale_allowlist_entries(repo_root: Path | None = None, allowlist: set[str] | None = None) -> list[str]:
    root = repo_root or REPO_ROOT
    debt = load_allowlist() if allowlist is None else allowlist
    return sorted(entry for entry in debt if not (root / entry).is_dir())


def list_missing(repo_root: Path | None = None) -> list[str]:
    """All skills lacking coverage, ignoring the allowlist -- used to bootstrap it."""
    errors = check(repo_root=repo_root, allowlist=set())
    return sorted(err.split(":", 1)[0] for err in errors)


def main() -> int:
    if "--list-missing" in sys.argv[1:]:
        for rel in list_missing():
            print(rel)
        return 0

    args = sys.argv[1:]
    explicit_base = None
    head_ref = "HEAD"
    if "--base" in args:
        index = args.index("--base")
        if index + 1 >= len(args):
            print("fail  --base requires a git ref", file=sys.stderr)
            return 1
        explicit_base = args[index + 1]
    if "--head" in args:
        index = args.index("--head")
        if index + 1 >= len(args):
            print("fail  --head requires a git ref", file=sys.stderr)
            return 1
        head_ref = args[index + 1]

    stale = stale_allowlist_entries()
    if stale:
        print("fail  scripts/skill_test_debt_allowlist.txt has stale entries (skill no longer exists):", file=sys.stderr)
        for rel in stale:
            print(f"  - {rel}", file=sys.stderr)
        return 1

    errors = check()
    base_ref = debt_gate.resolve_base(explicit_base, cwd=str(REPO_ROOT))
    if base_ref is None:
        errors.append("skill diff coverage: no base ref resolvable")
    else:
        changed_paths = changed_paths_between(base_ref, head_ref)
        if changed_paths is None:
            errors.append(f"skill diff coverage: could not diff {base_ref}..{head_ref}")
        else:
            errors.extend(changed_skill_test_errors(changed_paths, base_ref, head_ref))
    if errors:
        for err in errors:
            print(f"fail  {err}", file=sys.stderr)
        return 1
    print("ok      skill test coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
