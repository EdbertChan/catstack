#!/usr/bin/env python3
"""Fail on dated provenance notes ("Since 2026-..", "Added 2026-..") in
skills, hooks, scripts, and tests. Commit messages carry history; prose
does not. "Found via" reflect citations and fixture/baseline data are exempt.

Usage: python3 scripts/check_no_dated_provenance.py [ROOT]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GLOBS = ("engine/skills/**/*.md", "corpus/skills/**/*.md", "product/skills/**/*.md",
         "engine/hooks/**/*.py", "scripts/*.py", "tests/*.py")
DATED_RE = re.compile(r"\b(Since|Before|Added|Note \()\s*20\d\d-\d\d-\d\d")
SKIP_DIRS = ("/baselines/", "/fixtures/", "/tests/fixtures/")


def scan(root: Path) -> list[str]:
    hits: list[str] = []
    for pattern in GLOBS:
        for path in sorted(root.glob(pattern)):
            rel = path.relative_to(root).as_posix()
            if any(d in f"/{rel}" for d in SKIP_DIRS) or not path.is_file():
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if "Found via" not in line and DATED_RE.search(line):
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
