#!/usr/bin/env python3
"""Every skill MUST ship test coverage before it's added.

Companion to check_hook_test_coverage.py -- reuses the exact same
positive/negative name heuristic so authors do not learn a second
vocabulary (same rationale as check_mine_repro_coverage.py).

Two shapes, depending on whether the skill has executable code:

- Code skills (a `scripts/` dir, or any .py/.mjs/.js/.ts/.sh file outside
  a `tests/` dir): need a `tests/` dir (found anywhere under the skill,
  since e.g. reflect's lives at scripts/tests/) containing at least two
  real test functions. Unlike a hook's detect.py, most skill code is not
  a fire/stay-silent detector, so this does not force the hook-specific
  positive/negative vocabulary onto it -- it just requires non-trivial
  coverage exists. (Verified against this repo's own code skills: forcing
  the hook keyword list here produced false negatives on
  independent-judge-swarm's and reflect's real, already-adequate test
  suites, since their test names describe fixtures/fails-closed cases
  rather than fire/block/detect.)
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
    python3 scripts/check_skill_test_coverage.py --list-missing   # print all
        skills lacking coverage, ignoring the allowlist (used to bootstrap it)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)
import check_hook_test_coverage as hook_coverage  # noqa: E402

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


def _classified_names(names: list[str]) -> set[str | None]:
    return {hook_coverage._classify(n) for n in names}


def _fixture_names(tests_dir: Path) -> list[str]:
    return [p.stem for p in sorted(tests_dir.iterdir()) if p.is_file()]


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

    stale = stale_allowlist_entries()
    if stale:
        print("fail  scripts/skill_test_debt_allowlist.txt has stale entries (skill no longer exists):", file=sys.stderr)
        for rel in stale:
            print(f"  - {rel}", file=sys.stderr)
        return 1

    errors = check()
    if errors:
        for err in errors:
            print(f"fail  {err}", file=sys.stderr)
        return 1
    print("ok      skill test coverage")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
