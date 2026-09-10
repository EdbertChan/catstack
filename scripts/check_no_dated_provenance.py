#!/usr/bin/env python3
"""Fail on dated provenance or incident narrative ("Since 2026-..", "Added
2026-..", a "Found via" reflect citation with a date) in rule prose, skills,
hooks, scripts, and tests. Commit messages and git blame carry history;
standing rule text does not -- a rule that cites a date or a "found via"
story drifts into an incident log. Fixture/baseline data is exempt.

A tracker reference to this repository's own issues and pull requests is the
same class of incident history, so prose (markdown only) is also rejected when
it cites one. Two signals have to line up, because published prior art is full
of hashes and digits and a gate that flags Kimball's "Design Tip #164" or
Cook's "#3" gets switched off:

  1. Tracker vocabulary introduces the number -- "PR", "PRs", "pull request",
     "issue" -- or this repo's own name does ("catstack #9"), or the number
     arrives as a github.com URL into this repo. An external citation attaches
     its number to the title of the work instead ("Design Tip #164",
     "Battle-tested #2"), so it never matches.
  2. The reference resolves HERE. GitHub's own convention is that a bare "#12"
     means the current repo and another repo is named explicitly, so a
     "owner/repo#12" slug, a foreign github.com URL, or a proper noun sitting
     in front of the tracker word ("Invoker PRs #10553") is left alone.

Incident narrative in prose (markdown only) is rejected in the shapes it
actually takes: an "Incident:" or "Observed on" opener, "recurred", a bare
commit SHA (7-40 lowercase hex holding both a digit and a letter), and a
hash-number of three to six digits with or without a tracker word. A
hash-number stays legal when a capitalised title or another repo's name sits
directly in front of it, separated by whitespace only ("Design Tip #164",
"Invoker PRs #4821-#4825"), and when it is shorter than three digits
("Cook #3"). Skill trigger examples under tests/ and the inside of a closed
code fence are example data, so these shapes are not checked there; an
unclosed fence exempts nothing.

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

REPO_NAME = "catstack"
REPO_SLUG = "EdbertChan/catstack"
REPO_REF_EXTRA_GLOBS = ("engine/hooks/**/*.md",)
REPO_REF_GLOBS = PROSE_GLOBS + REPO_REF_EXTRA_GLOBS
REPO_REF_SKIP_DIRS = SKIP_DIRS + ("/tests/",)
TRACKER_REF_RE = re.compile(r"(?<![\w/#-])(?:PRs?|pull\s+requests?|issues?)\s*#\d{1,6}\b", re.IGNORECASE)
OWN_NAME_REF_RE = re.compile(rf"(?<![\w/-])(?:{REPO_NAME})\s*#\d{{1,6}}\b", re.IGNORECASE)
OWN_URL_RE = re.compile(rf"github\.com/{REPO_SLUG}/(?:pull|issues)/\d+", re.IGNORECASE)
FOREIGN_SLUG_RE = re.compile(r"(?<![\w/.-])([A-Z][\w.-]*/[\w.-]+)")
GITHUB_URL_SLUG_RE = re.compile(r"github\.com/([\w.-]+/[\w.-]+)", re.IGNORECASE)
QUALIFIER_RE = re.compile(r"([`\w][\w.`/-]*)[^\w`]*$")
TITLE_QUALIFIER_RE = re.compile(r"([`\w][\w.`/-]*)\s+$")
NARRATIVE_RE = re.compile(r"\bIncident:|\bObserved on\b|\b[Rr]ecurred\b")
COMMIT_SHA_RE = re.compile(r"(?<![\w#-])(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}(?![\w-])")
HASH_RUN_RE = re.compile(
    r"(?<![\w/&#-])(?:(?:PRs?|pull\s+requests?|issues?)\s*)?#\d{1,6}\b"
    r"(?:\s*(?:,|and|&|–|—|-)?\s*#\d{1,6}\b)*",
    re.IGNORECASE,
)
LONG_HASH_RE = re.compile(r"#\d{3,6}\b")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
SENTENCE_LEADS = frozenset(
    """a an and as at but by each every for from in inside it its one on onto our per see
    that the their these this those to via when where with
    close closes closed fix fixes fixed resolve resolves resolved""".split()
)

PROMISE_DATE = "2099-01-01"
PROMISED_CATCH = (
    ("dated provenance", ("engine/skills/demo/SKILL.md", f"Since {PROMISE_DATE} this gate is on.")),
    ("in rule prose, skills, hooks, scripts, and tests", ("scripts/check_demo.py", f"Added {PROMISE_DATE} after the gate went quiet.")),
    ('a "Found via" reflect citation with a date', ("corpus/skills/demo/SKILL.md", f"Found via /reflect on a {PROMISE_DATE} session.")),
    ('a "Found via" reflect citation with a date', ("engine/hooks/demo/detect.py", f"Found via /reflect on a {PROMISE_DATE} session.")),
    ('a "Found via" reflect citation with a date', ("scripts/check_demo.py", f"Found via /reflect on a {PROMISE_DATE} session.")),
    ('a "Found via" reflect citation with a date', ("tests/test_demo.py", f"Found via /reflect on a {PROMISE_DATE} session.")),
    ("A tracker reference to this repository's own issues and pull requests", ("corpus/skills/demo/SKILL.md", "Fixed in PR #123.")),
    ('an "Incident:" or "Observed on" opener', ("corpus/skills/demo/SKILL.md", "Incident: the hook went quiet.")),
    ('"recurred"', ("corpus/skills/demo/SKILL.md", "The drift recurred after the fix.")),
    ("a bare commit SHA", ("corpus/skills/demo/SKILL.md", "Reverted in a1b2c3d.")),
    ("a hash-number of three to six digits with or without a tracker word", ("corpus/skills/demo/SKILL.md", "See #4821 for the fallout.")),
)
PROMISED_ALLOW = (
    ("Fixture/baseline data is exempt", ("engine/skills/demo/tests/fixtures/added.md", f"Added {PROMISE_DATE}")),
    ("standing rule text", ("corpus/skills/demo/SKILL.md", "Always check disk before calling a skill unavailable.")),
    ('Kimball\'s "Design Tip #164"', ("corpus/skills/demo/SKILL.md", 'Kimball\'s "Design Tip #164" names the pattern.')),
    ('Cook\'s "#3"', ("corpus/CLAUDE.learned.md", "[Cook #3; Leveson CAST] count the defects first.")),
    ('a "owner/repo#12" slug', ("corpus/skills/demo/SKILL.md", "acme/widgets#4821 is the same one.")),
    ('a proper noun sitting in front of the tracker word ("Invoker PRs #10553")', ("corpus/skills/demo/SKILL.md", "Invoker PRs #10553 published the fix.")),
    ("Incident narrative in prose (markdown only)", ("scripts/check_demo.py", "Incident: the hook went quiet.")),
    ("Skill trigger examples under tests/", ("engine/skills/demo/tests/fires_example.md", "Incident: the hook went quiet.")),
    ("the inside of a closed code fence", ("corpus/skills/demo/SKILL.md", "Reverted in a1b2c3d.", True)),
)


def _glob_to_re(pattern: str) -> re.Pattern:
    segments = pattern.split("/")
    out = []
    for index, segment in enumerate(segments):
        if segment == "**":
            out.append(r"(?:[^/]+/)*")
            continue
        out.append(re.escape(segment).replace(r"\*", r"[^/]*"))
        if index != len(segments) - 1:
            out.append("/")
    return re.compile("^" + "".join(out) + "$")


PROSE_GLOB_RES = tuple(_glob_to_re(g) for g in PROSE_GLOBS)
CODE_GLOB_RES = tuple(_glob_to_re(g) for g in CODE_GLOBS)
REPO_REF_GLOB_RES = tuple(_glob_to_re(g) for g in REPO_REF_GLOBS)


def _is_prose(rel: str) -> bool:
    return rel in PROSE_FILES or any(r.match(rel) for r in PROSE_GLOB_RES)


def _is_code(rel: str) -> bool:
    return any(r.match(rel) for r in CODE_GLOB_RES)


def _is_repo_ref_prose(rel: str) -> bool:
    if any(d in f"/{rel}" for d in REPO_REF_SKIP_DIRS):
        return False
    return rel in PROSE_FILES or any(r.match(rel) for r in REPO_REF_GLOB_RES)


def _is_skipped(rel: str) -> bool:
    return any(d in f"/{rel}" for d in SKIP_DIRS)


def _names_other_repo(prefix: str, qualifier: re.Pattern = QUALIFIER_RE) -> bool:
    match = qualifier.search(prefix)
    if not match:
        return False
    word = match.group(1).strip("`")
    if "/" in word:
        return word.lower() != REPO_SLUG.lower()
    if word.lower() in SENTENCE_LEADS or word.lower() == REPO_NAME:
        return False
    return word[:1].isupper()


def _cites_repo_tracker(line: str) -> bool:
    if OWN_URL_RE.search(line) or OWN_NAME_REF_RE.search(line):
        return True
    named = FOREIGN_SLUG_RE.findall(line) + GITHUB_URL_SLUG_RE.findall(line)
    if any(slug.lower() != REPO_SLUG.lower() for slug in named):
        return False
    return any(not _names_other_repo(line[: m.start()]) for m in TRACKER_REF_RE.finditer(line))


def _cites_hash_number(line: str) -> bool:
    return any(
        LONG_HASH_RE.search(run.group()) and not _names_other_repo(line[: run.start()], TITLE_QUALIFIER_RE)
        for run in HASH_RUN_RE.finditer(line)
    )


def _tells_history(line: str) -> bool:
    return bool(NARRATIVE_RE.search(line) or COMMIT_SHA_RE.search(line)) or _cites_hash_number(line)


def _fenced_lines(text: str) -> set[int]:
    fenced: set[int] = set()
    block: list[int] = []
    marker = None
    for lineno, line in enumerate(text.splitlines(), 1):
        match = FENCE_RE.match(line)
        if marker is None:
            if match:
                marker, block = match.group(1), [lineno]
            continue
        block.append(lineno)
        if match and match.group(1) == marker:
            fenced.update(block)
            marker = None
    return fenced


def _line_violates(rel: str, line: str, fenced: bool = False) -> bool:
    if _is_repo_ref_prose(rel) and _cites_repo_tracker(line):
        return True
    if _is_prose(rel):
        if FOUND_VIA_RE.search(line) or PROSE_DATE_RE.search(line):
            return True
        return not fenced and _is_repo_ref_prose(rel) and _tells_history(line)
    if _is_code(rel):
        return bool(CODE_DATED_RE.search(line) or (FOUND_VIA_RE.search(line) and PROSE_DATE_RE.search(line)))
    return False


def exemplar_flagged(exemplar: tuple) -> bool:
    rel, line, *fenced = exemplar
    return not _is_skipped(rel) and _line_violates(rel, line, *fenced)


def _matching_files(root: Path, patterns: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for pattern in patterns:
        out.extend(p for p in root.glob(pattern) if p.is_file())
    return sorted(set(out))


def scan_tree(root: Path) -> list[str]:
    hits: list[str] = []
    for path in _matching_files(root, PROSE_GLOBS) + [root / f for f in PROSE_FILES if (root / f).is_file()]:
        rel = path.relative_to(root).as_posix()
        if _is_skipped(rel):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        fenced = _fenced_lines(text)
        for lineno, line in enumerate(text.splitlines(), 1):
            if _line_violates(rel, line, lineno in fenced):
                hits.append(f"{rel}:{lineno}: {line.strip()}")
    for path in _matching_files(root, CODE_GLOBS + REPO_REF_EXTRA_GLOBS):
        rel = path.relative_to(root).as_posix()
        if _is_skipped(rel):
            continue
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
    top = Path(subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True).stdout.strip())

    hits: list[str] = []
    fences: dict[str, set[int]] = {}
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
            if not _line_violates(current, line):
                continue
            if current not in fences:
                fences[current] = _fenced_lines((top / current).read_text(encoding="utf-8", errors="replace"))
            if _line_violates(current, line, lineno in fences[current]):
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
