#!/usr/bin/env python3
"""Fail on dated provenance or incident narrative in rule prose, skills,
hooks, scripts, and tests. Commit messages and git blame carry history;
standing rule text does not -- a rule that cites a date, a "found via" story,
a PR number, a commit SHA, or an incident retelling drifts into an incident
log.

Prose fails on: a calendar date, a "Found via" citation, a "#NNN" PR or issue
reference, a bare commit SHA, and the incident-narrative openers "Incident:",
"recurred" and "Observed on". Code fails on a dated "Since/Before/Added/Note ("
provenance note only.

Exempt, because each is sample data rather than standing rule text:
fixture and baseline directories, a skill's own tests/ directory, text inside
a fenced block, and text inside a quoted title. Each exemption applies to the
PR/SHA/narrative shapes; a date or a "Found via" citation still fails
everywhere outside fixture and baseline data.

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
import sys
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
PROSE_ISSUE_RE = re.compile(r"(?<![\w#])#\d{3,6}(?!\d)")
PROSE_SHA_RE = re.compile(
    r"(?<![0-9A-Za-z_/.-])(?=[0-9a-f]*[a-f])(?=[0-9a-f]*[0-9])[0-9a-f]{7,40}(?![0-9A-Za-z_/-])"
)
PROSE_NARRATIVE_RE = re.compile(r"\bIncident:|\b[Rr]ecurred\b|\b[Oo]bserved on\b")
QUOTE_OPEN_RE = re.compile(r'(?:^|(?<=[\s(\[]))"')
FENCE_RE = re.compile(r"^\s{0,3}(?:```|~~~)")
SKIP_DIRS = ("/baselines/", "/fixtures/", "/tests/fixtures/")
PROSE_SKIP_DIRS = ("/tests/",)


PROSE = "prose"
CODE = "code"

GATE_EXEMPLARS: dict[str, list[tuple[str, str, bool]]] = {
    "catch": [
        (PROSE, "introduced on 2024-03-15 after the outage", False),
        (PROSE, "Found via a session review", False),
        (PROSE, "see #1234 for context", False),
        (PROSE, "fixed in a3b4c5d", False),
        (PROSE, "Incident: the gate missed a file", False),
        (PROSE, "this recurred three times", False),
        (PROSE, "Observed on the nightly run", False),
        (CODE, "Since 2025-01-01 this has been the default", False),
        (CODE, "Before 2024-06-01 it worked differently", False),
        (CODE, "Added 2025-03-22 for the new gate", False),
        (PROSE, "date 2025-12-31 in a fenced block still fails", True),
        (PROSE, "Found via reflect still fails in a fence", True),
    ],
    "allow": [
        (PROSE, "this rule prevents drift", False),
        (PROSE, "commit messages carry history", False),
        (CODE, "pattern = re.compile(r'hello world')", False),
        (CODE, "x = 42", False),
        (PROSE, "see #1234 inside a fence is exempt", True),
        (PROSE, "fixed in a3b4c5d inside a fence is exempt", True),
        (PROSE, "Incident: inside a fence is exempt", True),
        (PROSE, '"a quoted title with #1234 inside" is exempt', False),
    ],
}


def gate_check(exemplar: tuple[str, str, bool]) -> bool:
    kind, line, in_fence = exemplar
    return _kind_violates(kind, line, in_fence)


def _segment_re(segment: str) -> str:
    out = []
    for char in segment:
        if char == "*":
            out.append("[^/]*")
        elif char == "?":
            out.append("[^/]")
        else:
            out.append(re.escape(char))
    return "".join(out)


@lru_cache(maxsize=None)
def _glob_re(pattern: str) -> re.Pattern[str]:
    segments = pattern.split("/")
    out = []
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == "**":
            out.append(".*" if last else "(?:[^/]+/)*")
        else:
            out.append(_segment_re(segment))
            if not last:
                out.append("/")
    return re.compile(f"(?s:{''.join(out)})\\Z")


def _glob_matches(rel: str, pattern: str) -> bool:
    return bool(_glob_re(pattern).match(rel))


def _is_prose(rel: str) -> bool:
    return rel in PROSE_FILES or any(_glob_matches(rel, g) for g in PROSE_GLOBS)


def _is_code(rel: str) -> bool:
    return any(_glob_matches(rel, g) for g in CODE_GLOBS)


def _classify(rel: str) -> str | None:
    if _is_prose(rel):
        return PROSE
    if _is_code(rel):
        return CODE
    return None


def _is_skipped(rel: str, kind: str | None = None) -> bool:
    padded = f"/{rel}"
    if any(d in padded for d in SKIP_DIRS):
        return True
    return kind == PROSE and any(d in padded for d in PROSE_SKIP_DIRS)


def _unquoted(line: str) -> str:
    match = QUOTE_OPEN_RE.search(line)
    return line[: match.start()] if match else line


def _fence_flags(lines: list[str]) -> list[bool]:
    flags: list[bool] = []
    inside = False
    for line in lines:
        fence = bool(FENCE_RE.match(line))
        flags.append(inside or fence)
        if fence:
            inside = not inside
    return flags


def _kind_violates(kind: str | None, line: str, in_fence: bool = False) -> bool:
    if kind == PROSE:
        if FOUND_VIA_RE.search(line) or PROSE_DATE_RE.search(line):
            return True
        if in_fence:
            return False
        outside = _unquoted(line)
        return bool(
            PROSE_ISSUE_RE.search(outside)
            or PROSE_SHA_RE.search(outside)
            or PROSE_NARRATIVE_RE.search(outside)
        )
    if kind == CODE:
        return bool(CODE_DATED_RE.search(line))
    return False


def _line_violates(rel: str, line: str, in_fence: bool = False) -> bool:
    return _kind_violates(_classify(rel), line, in_fence)


def _matching_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pattern in patterns:
        out.extend(p for p in root.glob(pattern) if p.is_file())
    return sorted(set(out))


def _tagged_files(root: Path, patterns: tuple[str, ...], kind: str) -> list[tuple[Path, str]]:
    return [(p, kind) for p in _matching_files(root, patterns)]


def scan_tree(root: Path) -> list[str]:
    targets = (
        _tagged_files(root, PROSE_GLOBS, PROSE)
        + [(root / f, PROSE) for f in PROSE_FILES if (root / f).is_file()]
        + _tagged_files(root, CODE_GLOBS, CODE)
    )
    hits: list[str] = []
    for path, kind in targets:
        rel = path.relative_to(root).as_posix()
        if _is_skipped(rel, kind):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        flags = _fence_flags(lines) if kind == PROSE else [False] * len(lines)
        for lineno, (line, in_fence) in enumerate(zip(lines, flags), 1):
            if _kind_violates(kind, line, in_fence):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    return hits


@lru_cache(maxsize=None)
def _worktree_fence_flags(rel: str) -> tuple[bool, ...]:
    try:
        text = Path(rel).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"warn  fence state unreadable for {rel}: {exc}", file=sys.stderr)
        return ()
    return tuple(_fence_flags(text.splitlines()))


def _worktree_fence(rel: str, lineno: int) -> bool:
    flags = _worktree_fence_flags(rel)
    return flags[lineno - 1] if 0 < lineno <= len(flags) else False


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
            if _is_skipped(current, _classify(current)):
                continue
            line = raw[1:]
            if _line_violates(current, line, _worktree_fence(current, lineno)):
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
