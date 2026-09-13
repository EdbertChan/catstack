#!/usr/bin/env python3
"""Refuse a PR description that states facts about the repository's past.

A premise the work depends on is proven in the session. The description is
where an unproven one would be published, so claims about history are banned
there outright. The background judge decides meaning from the
`pr-description-history-claims` phrase dictionary; this file only splits the
description and reports.

Three outcomes per description: clean, hit, unchecked. Unchecked (no runner
answered) fails, the same as a hit: an unread description is not a clean one.

    python3 engine/skills/make-pr/scripts/description_check.py BODY_FILE

Exit 0 clean, 1 hit or unchecked, 2 unreadable file.
"""
from __future__ import annotations

import importlib.util
import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
LLM_JUDGE_DIR = os.path.join(REPO_ROOT, "engine", "hooks", "llm-judge")
CHECKER = "pr-description-history-claims"
CHUNK_LIMIT = 3500


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(LLM_JUDGE_DIR, filename))
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {filename} from {LLM_JUDGE_DIR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sections(body: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for line in body.splitlines():
        if line.startswith("## ") and current:
            parts.append("\n".join(current))
            current = []
        current.append(line)
    if current:
        parts.append("\n".join(current))
    return [part for part in parts if part.strip()]


def chunks(body: str, limit: int = CHUNK_LIMIT) -> list[str]:
    pieces: list[str] = []
    current = ""
    for section in sections(body):
        while len(section) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(section[:limit])
            section = section[limit:]
        candidate = f"{current}\n{section}" if current else section
        if len(candidate) > limit:
            pieces.append(current)
            current = section
        else:
            current = candidate
    if current.strip():
        pieces.append(current)
    return [piece for piece in pieces if piece.strip()]


def check(body: str, ask=None, phrases=None) -> tuple[str, list[str]]:
    """Return (outcome, report lines); outcome is clean, hit, or unchecked."""
    phrases = phrases or _load("llm_judge_phrases", "phrases.py")
    ask = ask or _load("llm_judge", "judge.py").ask
    dictionary = phrases.load(CHECKER)
    lines: list[str] = []
    outcome = "clean"
    for piece in chunks(body):
        result = ask(phrases.prompt(dictionary, piece))
        answer = result.get("answer") if result.get("outcome") == "answered" else None
        if not isinstance(answer, dict):
            tried = "; ".join(f"{a.get('runner')}: {a.get('reason')}" for a in result.get("attempts") or [])
            lines.append(f"unchecked description: no judge runner answered ({tried or 'no runners'})")
            if outcome == "clean":
                outcome = "unchecked"
            continue
        if answer.get("match") is True:
            closest = answer.get("closest") or ""
            first_line = next((line.strip() for line in piece.splitlines() if line.strip()), "")
            lines.append(f"hit     history claim in the section starting {first_line[:80]!r} (closest example: {closest!r})")
            outcome = "hit"
    if outcome == "hit":
        lines.append(dictionary["on_hit"])
    return outcome, lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: description_check.py BODY_FILE", file=sys.stderr)
        return 2
    try:
        with open(args[0], encoding="utf-8") as handle:
            body = handle.read()
    except OSError as exc:
        print(f"unchecked description: cannot read {args[0]}: {exc}", file=sys.stderr)
        return 2
    outcome, lines = check(body)
    for line in lines:
        print(line)
    print(f"description {outcome}")
    return 0 if outcome == "clean" else 1


if __name__ == "__main__":
    raise SystemExit(main())
