#!/usr/bin/env python3
"""Fail when a commit range would publish a term from the user's private denylist."""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CLEAN, HIT, UNCHECKED = 0, 1, 2
TERMS_ENV = "CATSTACK_PRIVATE_TERMS"
TERMS_FILE_ENV = "CATSTACK_PRIVATE_TERMS_FILE"
CONFIG_DIR = Path("~/.config/catstack")
DEFAULT_TERMS_FILE = CONFIG_DIR / "private-terms"
ALLOWED_EMAILS_FILE = CONFIG_DIR / "allowed-emails"
BUILTIN_ALLOWED_EMAILS = ("*@users.noreply.github.com", "noreply@github.com")
RECORD_SEP = "\x1e"
FIELD_SEP = "\x1f"
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")

HELP_EPILOG = """\
Scans, for the commits in <base>..<head>: every added line and new file path
in `git diff <base>...<head>`, every commit message, and every author and
committer email.

Terms come from the first that is set: $CATSTACK_PRIVATE_TERMS (newline-
separated, for CI secrets), the file at $CATSTACK_PRIVATE_TERMS_FILE, or
~/.config/catstack/private-terms. One term per line, matched as a
case-insensitive substring; blank lines and lines starting with # are ignored.

Allowed emails: *@users.noreply.github.com, noreply@github.com (GitHub's own
merge and web-edit commits), and the glob patterns in
~/.config/catstack/allowed-emails, one per line.

Each hit prints as `<kind> <commit-or-file:line>: matched term #<index>`,
where <index> is the term's 1-based position in the denylist. The term and the
offending email are never printed.

Exit codes:
  0  clean: every scanned line, message, and email was read and passed
  1  hit: at least one finding
  2  unchecked: no denylist, an empty denylist, or a git command failed

--from-root scans the whole history reachable from <head>, for a push whose
remote holds nothing this checkout knows about.
"""

EXEMPLAR_TERMS = ("widgetcorp", "acme-internal.example")
PROMISED_CATCH = (
    "ssh deploy@build.acme-internal.example",
    "Nightly job owned by WidgetCorp platform",
)
PROMISED_ALLOW = (
    "ssh deploy@build.example.com",
    "a widget corp is not a match",
)


class Unchecked(Exception):
    """A scan input could not be read; the caller exits UNCHECKED."""


@dataclass(frozen=True)
class Commit:
    sha: str
    author_email: str
    committer_email: str
    message: str


def flags_exemplar(exemplar: str) -> bool:
    return match_term(exemplar, EXEMPLAR_TERMS) is not None


def parse_lines(text: str) -> list[str]:
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def match_term(text: str, terms: tuple[str, ...]) -> int | None:
    folded = text.casefold()
    for index, term in enumerate(terms, 1):
        if term.casefold() in folded:
            return index
    return None


def load_terms(environ: dict[str, str]) -> tuple[tuple[str, ...], str]:
    inline = environ.get(TERMS_ENV, "")
    if inline.strip():
        source = f"${TERMS_ENV}"
        terms = parse_lines(inline)
    else:
        configured = environ.get(TERMS_FILE_ENV, "")
        path = Path(configured).expanduser() if configured else DEFAULT_TERMS_FILE.expanduser()
        source = str(path)
        if not path.is_file():
            how = f"${TERMS_FILE_ENV} points at it" if configured else "the default location"
            raise Unchecked(
                f"no denylist: ${TERMS_ENV} is empty and {path} ({how}) does not exist"
            )
        try:
            terms = parse_lines(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            raise Unchecked(f"denylist {path} is unreadable: {exc}") from exc
    if not terms:
        raise Unchecked(f"denylist {source} holds no terms (only blank or # lines)")
    return tuple(terms), source


def load_allowed_emails() -> tuple[str, ...]:
    path = ALLOWED_EMAILS_FILE.expanduser()
    if not path.is_file():
        return BUILTIN_ALLOWED_EMAILS
    try:
        extra = parse_lines(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise Unchecked(f"allowed-email list {path} is unreadable: {exc}") from exc
    return BUILTIN_ALLOWED_EMAILS + tuple(extra)


def email_allowed(email: str, patterns: tuple[str, ...]) -> bool:
    folded = email.casefold()
    return any(fnmatch.fnmatchcase(folded, p.casefold()) for p in patterns)


def git(*args: str) -> str:
    res = subprocess.run(["git", *args], capture_output=True, text=True, errors="replace")
    if res.returncode != 0:
        raise Unchecked(f"git {' '.join(args)} exited {res.returncode}: {res.stderr.strip()}")
    return res.stdout


def read_commits(revision_range: list[str]) -> list[Commit]:
    fmt = f"%H{FIELD_SEP}%ae{FIELD_SEP}%ce{FIELD_SEP}%B{RECORD_SEP}"
    records = git("log", f"--format={fmt}", *revision_range, "--").split(RECORD_SEP)
    trailing = records.pop()
    if trailing.strip():
        raise Unchecked("git log output did not end with a record separator; the commit list is incomplete")
    commits = []
    for record in records:
        parts = record.lstrip("\n").split(FIELD_SEP, 3)
        if len(parts) != 4:
            raise Unchecked(f"git log printed a record this scanner cannot parse: {len(parts)} fields")
        commits.append(Commit(*parts))
    return commits


def added_lines(diff_args: list[str]):
    out = git("-c", "core.quotePath=false", "diff", "--no-color", "--no-ext-diff", "--text", "-M", "-U0", *diff_args)
    current = None
    lineno = 0
    for raw in out.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:]
            current = target[2:] if target.startswith("b/") else None
            if current is not None:
                yield "path", current, 0, current
            continue
        if raw.startswith("--- "):
            continue
        match = HUNK_RE.match(raw)
        if match:
            lineno = int(match.group(1))
            continue
        if current is not None and raw.startswith("+"):
            yield "added", current, lineno, raw[1:]
            lineno += 1


def empty_tree() -> str:
    return git("hash-object", "-t", "tree", os.devnull).strip()


def scan(base: str | None, head: str, terms: tuple[str, ...], allowed: tuple[str, ...]) -> list[str]:
    git("rev-parse", "--verify", "--quiet", f"{head}^{{commit}}")
    if base is None:
        diff_args = [empty_tree(), head]
        revision_range = [head]
    else:
        git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
        diff_args = [f"{base}...{head}"]
        revision_range = [f"{base}..{head}"]

    hits: list[str] = []
    for kind, path, lineno, text in added_lines(diff_args):
        index = match_term(text, terms)
        if index is not None:
            where = path if kind == "path" else f"{path}:{lineno}"
            hits.append(f"{kind} {where}: matched term #{index}")
    for commit in read_commits(revision_range):
        short = commit.sha[:12]
        index = match_term(commit.message, terms)
        if index is not None:
            hits.append(f"message {short}: matched term #{index}")
        for kind, email in (("author", commit.author_email), ("committer", commit.committer_email)):
            index = match_term(email, terms)
            if index is not None:
                hits.append(f"{kind} {short}: matched term #{index}")
            elif not email_allowed(email, allowed):
                hits.append(f"{kind} {short}: email is not on the allowed list")
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, epilog=HELP_EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    where = ap.add_mutually_exclusive_group(required=True)
    where.add_argument("--base", help="scan commits in <base>..<head> and lines added since their merge-base")
    where.add_argument("--from-root", action="store_true", help="scan the whole history reachable from <head>")
    ap.add_argument("--head", default="HEAD", help="last commit to scan (default: HEAD)")
    args = ap.parse_args(argv)

    try:
        terms, source = load_terms(dict(os.environ))
        allowed = load_allowed_emails()
        hits = scan(None if args.from_root else args.base, args.head, terms, allowed)
    except Unchecked as exc:
        print(f"unchecked  {exc}", file=sys.stderr)
        return UNCHECKED

    span = f"the history of {args.head}" if args.from_root else f"{args.base}..{args.head}"
    for hit in hits:
        print(hit)
    if hits:
        print(f"fail    {len(hits)} private-term finding(s) in {span} (denylist: {source})", file=sys.stderr)
        return HIT
    print(f"ok      no private terms in {span} ({len(terms)} terms from {source})")
    return CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
