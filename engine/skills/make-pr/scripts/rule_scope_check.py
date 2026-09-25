#!/usr/bin/env python3
"""Refuse a rule whose main sentence is about one incident instead of the lesson.

Skill prose is loaded every turn and has to answer the next case, not the one
that prompted it. A rule whose lead names one tool, label, command or error
message reads as an incident log: the next case of the same kind is worded
differently, so the rule never fires again. The general lesson belongs in the
lead; the name belongs beside it as an example.

Whether a sentence's subject is one incident or a general lesson is a question
of meaning, so the background judge decides it from the `incident-scoped-rule`
phrase dictionary (engine/skills/phrase-judge/SKILL.md). This file only finds
the rule lines a diff adds and reports. scripts/ci/check_no_dated_provenance.py
is the pattern half of the same requirement and is untouched: it catches dates,
"Found via" stories and this repo's own tracker numbers, which are shapes.

Only added lines that carry a rule's own lead are judged. A line whose lead
sits in unchanged context adds no main sentence, and a fragment judged without
its lead would be read as incident-scoped on the example it happens to quote.

Three outcomes per rule: clean, hit, unchecked. Unchecked (no runner answered)
fails, the same as a hit: an unread rule is not a clean one.

    python3 engine/skills/make-pr/scripts/rule_scope_check.py --base origin/main

Exit 0 clean, 1 hit or unchecked, 2 the diff could not be read.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
LLM_JUDGE_DIR = os.path.join(REPO_ROOT, "engine", "hooks", "llm-judge")
CHECKER = "incident-scoped-rule"
RULE_PREFIXES = ("engine/skills/", "corpus/skills/", "product/skills/")
SKIP_DIRS = ("/tests/", "/fixtures/", "/baselines/")
MIN_WORDS = 6
LEAD_LIMIT = 120

BULLET_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
NOT_PROSE_RE = re.compile(r"^(?:#|\||>|```|~~~|<|---|===|!\[|\[\^)")
FRONTMATTER_RE = re.compile(r"^[a-z][a-z0-9-]*:(?:\s|$)")
BOLD_LEAD_RE = re.compile(r"^\*\*(.+?)\*\*")
SENTENCE_END_RE = re.compile(r"(?<=[.?!])\s")
HUNK_START_RE = re.compile(r"\+(\d+)")


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LLM_JUDGE_DIR, filename))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename} from {LLM_JUDGE_DIR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def is_rule_markdown(path: str) -> bool:
    if not path.endswith(".md") or not path.startswith(RULE_PREFIXES):
        return False
    return not any(part in f"/{path}" for part in SKIP_DIRS)


def body(text: str) -> str:
    return BULLET_RE.sub("", text.strip())


def starts_rule(text: str) -> bool:
    stripped = text.strip()
    if not stripped or NOT_PROSE_RE.match(stripped) or FRONTMATTER_RE.match(stripped):
        return False
    if text[:1].isspace() and not BULLET_RE.match(stripped):
        return False
    return len(body(stripped).split()) >= MIN_WORDS


def continues_rule(text: str) -> bool:
    stripped = text.strip()
    return bool(stripped) and not NOT_PROSE_RE.match(stripped) and not BULLET_RE.match(stripped)


def lead(text: str) -> str:
    content = body(text)
    bold = BOLD_LEAD_RE.match(content)
    first = bold.group(1) if bold else SENTENCE_END_RE.split(content, maxsplit=1)[0]
    return first.strip()[:LEAD_LIMIT]


def added_blocks(diff: str) -> list[dict]:
    """Group the diff's added rule lines into one block per added rule.

    Rule prose is hard-wrapped, so a paragraph's later lines sit at the same
    indent as its first. What separates a lead from a continuation is the line
    before it in the new file, not the line's own shape: a bullet always leads,
    and plain prose leads only after a blank line, a heading, or nothing. A
    hunk that does not start at line 1 begins after a line this cannot see, so
    its first plain line is read as a continuation -- a fragment judged without
    its lead would be read as incident-scoped on whatever example it happens to
    quote. Git emits context lines around a change, so that unknown only bites
    a zero-context hunk.
    """
    blocks: list[dict] = []
    open_block: dict | None = None
    path: str | None = None
    lineno = 0
    mid_paragraph = True
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path, lineno, open_block, mid_paragraph = raw[6:], 0, None, True
            continue
        if raw.startswith("+++ ") or raw.startswith("--- "):
            path, open_block, mid_paragraph = None, None, True
            continue
        if raw.startswith("@@"):
            match = HUNK_START_RE.search(raw)
            lineno = int(match.group(1)) - 1 if match else 0
            open_block, mid_paragraph = None, lineno > 0
            continue
        if raw.startswith("-"):
            continue
        if path is None or not is_rule_markdown(path):
            open_block = None
            continue
        added = raw.startswith("+")
        if not added and not raw.startswith(" ") and raw:
            open_block = None
            continue
        text = raw[1:] if raw else ""
        lineno += 1
        if not added:
            open_block = None
        elif starts_rule(text) and not (mid_paragraph and not BULLET_RE.match(text.strip())):
            open_block = {"path": path, "line": lineno, "lines": [text.strip()]}
            blocks.append(open_block)
        elif open_block is not None and mid_paragraph and continues_rule(text):
            open_block["lines"].append(text.strip())
        else:
            open_block = None
        stripped = text.strip()
        mid_paragraph = bool(stripped) and not NOT_PROSE_RE.match(stripped)
    return [{"path": b["path"], "line": b["line"], "text": " ".join(b["lines"])} for b in blocks]


def check(blocks: list[dict], ask=None, phrases=None) -> tuple[str, list[str]]:
    """Return (outcome, report lines); outcome is clean, hit, or unchecked."""
    phrases = phrases or _load("llm_judge_phrases", "phrases.py")
    ask = ask or _load("llm_judge", "judge.py").ask
    dictionary = phrases.load(CHECKER)
    lines: list[str] = []
    outcome = "clean"
    for block in blocks:
        where = f"{block['path']}:{block['line']}"
        result = ask(phrases.prompt(dictionary, block["text"]))
        answer = result.get("answer") if result.get("outcome") == "answered" else None
        if not isinstance(answer, dict):
            tried = "; ".join(f"{a.get('runner')}: {a.get('reason')}" for a in result.get("attempts") or [])
            lines.append(f"unchecked rule scope at {where}: no judge runner answered ({tried or 'no runners'})")
            if outcome == "clean":
                outcome = "unchecked"
            continue
        if answer.get("match") is True:
            closest = answer.get("closest") or ""
            lines.append(f"hit     incident-scoped rule at {where}: {lead(block['text'])!r} (closest example: {closest!r})")
            outcome = "hit"
    if outcome == "hit":
        lines.append(dictionary["on_hit"])
    return outcome, lines


def diff_since(base: str) -> str:
    merge_base = subprocess.run(["git", "-C", REPO_ROOT, "merge-base", base, "HEAD"], capture_output=True, text=True)
    if merge_base.returncode != 0:
        raise LookupError(f"cannot resolve merge-base with {base}: {merge_base.stderr.strip()}")
    diff = subprocess.run(["git", "-C", REPO_ROOT, "diff", merge_base.stdout.strip()], capture_output=True, text=True)
    if diff.returncode != 0:
        raise LookupError(f"cannot read the diff since {base}: {diff.stderr.strip()}")
    return diff.stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", default="origin/main", help="ref whose merge-base with HEAD bounds the added lines")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        diff = diff_since(args.base)
    except LookupError as exc:
        print(f"unchecked rule scope: {exc}", file=sys.stderr)
        return 2
    outcome, lines = check(added_blocks(diff))
    for line in lines:
        print(line)
    if outcome == "clean":
        print("ok      no incident-scoped rules")
        return 0
    print(f"fail    rule scope {outcome}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
