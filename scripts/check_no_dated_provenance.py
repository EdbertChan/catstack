#!/usr/bin/env python3
"""Fail on dated provenance or incident narrative ("Since 2026-..", "Added
2026-..", "Found via /reflect on 2026-..: ...") in rule prose, skills, hooks,
scripts, and tests. Commit messages and git blame carry history; standing
rule text does not -- a rule cites a date, it drifts into an incident log.
Fixture/baseline data is exempt.

Usage: python3 scripts/check_no_dated_provenance.py [ROOT]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROSE_GLOBS = (
    "engine/skills/**/*.md", "corpus/skills/**/*.md", "product/skills/**/*.md",
    "always-on/**/*.md", "cursor/**/*.mdc", "commands/**/*.md",
    "CLAUDE.md", "AGENTS.md", "engine/CLAUDE.core.md", "corpus/CLAUDE.learned.md",
)
CODE_GLOBS = ("engine/hooks/**/*.py", "scripts/*.py", "tests/*.py")
PROSE_DATE_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
CODE_DATED_RE = re.compile(r"\b(Since|Before|Added|Note \()\s*20\d\d-\d\d-\d\d")
FOUND_VIA_RE = re.compile(r"Found via", re.IGNORECASE)
SKIP_DIRS = ("/baselines/", "/fixtures/", "/tests/fixtures/")


def _matching_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pattern in patterns:
        out.extend(p for p in root.glob(pattern) if p.is_file())
    return sorted(set(out))


def scan(root: Path) -> list[str]:
    hits: list[str] = []
    for path in _matching_files(root, PROSE_GLOBS):
        rel = path.relative_to(root).as_posix()
        if any(d in f"/{rel}" for d in SKIP_DIRS):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if FOUND_VIA_RE.search(line) or PROSE_DATE_RE.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    for path in _matching_files(root, CODE_GLOBS):
        rel = path.relative_to(root).as_posix()
        if any(d in f"/{rel}" for d in SKIP_DIRS):
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if CODE_DATED_RE.search(line):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO
    hits = scan(root)
    for hit in hits:
        print(f"fail  {hit}")
    if hits:
        return 1
    print("ok      no dated provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
