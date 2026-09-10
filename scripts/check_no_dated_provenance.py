#!/usr/bin/env python3
"""Fail on dated provenance or incident narrative ("Since 2026-..", "Added
2026-..", a "Found via" reflect citation with a date) in rule prose, skills,
hooks, scripts, and tests. Commit messages and git blame carry history;
standing rule text does not -- a rule that cites a date or a "found via"
story drifts into an incident log. Fixture/baseline data is exempt.

Two modes:
  python3 scripts/check_no_dated_provenance.py [ROOT]
      Full scan of every matching file under ROOT (default: repo root).
      Use for an ad hoc audit of the whole tree.
  python3 scripts/check_no_dated_provenance.py --base <ref>
      Diff-aware: only checks lines ADDED since the merge-base with <ref>.
      This is what a PR gate should use -- it can be mandatory without
      breaking on pre-existing violations elsewhere in the tree that this
      change didn't touch.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from functools import lru_cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PROSE_GLOBS = (
    "engine/skills/**/*.md", "corpus/skills/**/*.md", "product/skills/**/*.md",
    "always-on/**/*.md", "cursor/**/*.mdc", "commands/**/*.md",
)
PROSE_FILES = ("CLAUDE.md", "AGENTS.md", "engine/CLAUDE.core.md", "corpus/CLAUDE.learned.md")
CODE_GLOBS = ("engine/hooks/**/*.py", "scripts/*.py", "tests/*.py")
PROSE_DATE_RE = re.compile(r"\b20\d\d-\d\d-\d\d\b")
CODE_DATED_RE = re.compile(r"\b(Since|Before|Added|Note \()\s*20\d\d-\d\d-\d\d")
FOUND_VIA_RE = re.compile(r"Found via", re.IGNORECASE)
SKIP_DIRS = ("/baselines/", "/fixtures/", "/tests/fixtures/")


@lru_cache(maxsize=None)
def _glob_re(pattern: str) -> re.Pattern[str]:
    segments = pattern.split("/")
    out = ""
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            out += "(?:[^/]+/)*[^/]+" if last else "(?:[^/]+/)*"
            continue
        out += "".join(
            "[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch)
            for ch in segment
        )
        if not last:
            out += "/"
    return re.compile(out + r"\Z")


def _matches(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(_glob_re(pattern).match(rel) for pattern in patterns)


def _is_prose(rel: str) -> bool:
    return rel in PROSE_FILES or _matches(rel, PROSE_GLOBS)


def _is_code(rel: str) -> bool:
    return _matches(rel, CODE_GLOBS)


def _is_skipped(rel: str) -> bool:
    return any(d in f"/{rel}" for d in SKIP_DIRS)


def _line_violates(rel: str, line: str) -> bool:
    if _is_prose(rel):
        return bool(FOUND_VIA_RE.search(line) or PROSE_DATE_RE.search(line))
    if _is_code(rel):
        return bool(CODE_DATED_RE.search(line))
    return False


def _matching_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pattern in patterns:
        out.extend(p for p in root.glob(pattern) if p.is_file())
    return sorted(set(out))


def scan_tree(root: Path) -> list[str]:
    candidates: list[tuple[Path, str]] = [(root / f, "prose") for f in PROSE_FILES if (root / f).is_file()]
    candidates += [(p, "prose") for p in _matching_files(root, PROSE_GLOBS)]
    candidates += [(p, "code") for p in _matching_files(root, CODE_GLOBS)]

    hits: list[str] = []
    for path, kind in candidates:
        rel = path.relative_to(root).as_posix()
        if _is_skipped(rel):
            continue
        if not (_is_prose(rel) if kind == "prose" else _is_code(rel)):
            raise SystemExit(f"fail  {rel}: matched a {kind} scan glob but no {kind} rule classifies it; unchecked, not clean")
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if _line_violates(rel, line):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


def scan_diff(base: str) -> list[str]:
    mb = subprocess.run(["git", "merge-base", base, "HEAD"], capture_output=True, text=True)
    if mb.returncode != 0:
        raise SystemExit(f"fail  cannot resolve merge-base with {base}: {mb.stderr.strip()}")
    ref = mb.stdout.strip()
    diff = subprocess.run(["git", "diff", ref], capture_output=True, text=True, check=True).stdout

    hits: list[str] = []
    current: str | None = None
    lineno = 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            current = raw[6:]
            lineno = 0
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            current = None
            continue
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            lineno = int(match.group(1)) - 1 if match else 0
            continue
        if current is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            lineno += 1
            if _is_skipped(current):
                continue
            line = raw[1:]
            if _line_violates(current, line):
                hits.append(f"{current}:{lineno}: {line.strip()}")
        elif not raw.startswith("-"):
            lineno += 1
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=None, help="full-scan root (default: repo root)")
    ap.add_argument("--base", default=None, help="diff-aware mode: only check lines added since merge-base with this ref")
    args = ap.parse_args()

    if args.base:
        hits = scan_diff(args.base)
    else:
        root = Path(args.root).resolve() if args.root else REPO
        hits = scan_tree(root)

    for hit in hits:
        print(f"fail  {hit}")
    if hits:
        return 1
    print("ok      no dated provenance")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
