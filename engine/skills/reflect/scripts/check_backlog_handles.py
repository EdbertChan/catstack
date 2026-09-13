#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys

OK = 0
FAIL = 1
UNCHECKED = 2

SECTION_ALIASES = {
    "accepted": "accepted",
    "backlog": "backlog",
    "backlogged": "backlog",
    "rejected": "rejected",
    "route to automate me": "route-to-automate-me",
    "route-to-automate-me": "route-to-automate-me",
    "route to automate-me": "route-to-automate-me",
    "route-to-automate me": "route-to-automate-me",
    "routed to automate me": "route-to-automate-me",
    "routed to automate-me": "route-to-automate-me",
}

BULLET_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(?P<item>\S.*)$")
MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(?P<title>.*?)\s*#*\s*$")
BOLD_HEADING_RE = re.compile(r"^\s{0,3}(?:\*\*|__)(?P<title>.*?)(?:\*\*|__):?\s*$")
PLAIN_HEADING_RE = re.compile(r"^\s{0,3}(?P<title>[A-Za-z][A-Za-z` -]+):\s*$")
WORKFLOW_RE = re.compile(r"\bwf-\d+(?:-\d+)+\b", re.IGNORECASE)
TASK_RE = re.compile(
    r"\b(?:task(?:\s+id)?\s*[:#]\s*|task\s+id\s+|task-)[A-Za-z0-9][A-Za-z0-9._/-]*\b",
    re.IGNORECASE,
)
TRACKER_RE = re.compile(
    r"(?:(?<!\w)#\d+\b|\b(?:issue|pr|pull\s+request)\s*#?\d+\b|/(?:issues|pull)/\d+\b)",
    re.IGNORECASE,
)
DECLINED_RE = re.compile(r"\bdeclined by user\b", re.IGNORECASE)


def normalized_heading(title: str) -> str:
    title = title.strip().strip(":").strip()
    title = title.replace("`", "")
    title = re.sub(r"\s+", " ", title)
    return title.lower()


def section_for(line: str) -> str | None:
    for pattern in (MARKDOWN_HEADING_RE, BOLD_HEADING_RE, PLAIN_HEADING_RE):
        match = pattern.match(line)
        if not match:
            continue
        return SECTION_ALIASES.get(normalized_heading(match.group("title")))
    return None


def has_handle(item: str) -> bool:
    return any(
        pattern.search(item)
        for pattern in (WORKFLOW_RE, TASK_RE, TRACKER_RE, DECLINED_RE)
    )


def parse_backlog_items(text: str) -> tuple[str, list[str], str | None]:
    current_section = None
    saw_section = False
    saw_backlog = False
    backlog_text_without_bullets = False
    items: list[list[str]] = []
    for raw in text.splitlines():
        section = section_for(raw)
        if section:
            current_section = section
            saw_section = True
            saw_backlog = saw_backlog or section == "backlog"
            continue
        if current_section != "backlog":
            continue
        stripped = raw.strip()
        if not stripped:
            continue
        bullet = BULLET_RE.match(raw)
        if bullet:
            items.append([bullet.group("item").strip()])
        elif items and raw[:1].isspace():
            items[-1].append(stripped)
        else:
            backlog_text_without_bullets = True
    if not saw_section:
        return "unchecked", [], "no recognized reflect findings section"
    if saw_backlog and backlog_text_without_bullets and not items:
        return "unchecked", [], "Backlog section is not itemized"
    return "ok", [" ".join(parts) for parts in items], None


def read_input(path: str | None) -> str:
    if path:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("summary", nargs="?")
    args = ap.parse_args(argv)
    try:
        text = read_input(args.summary)
    except OSError as exc:
        print(f"unchecked  cannot read summary: {exc}")
        return UNCHECKED
    status, items, reason = parse_backlog_items(text)
    if status == "unchecked":
        print(f"unchecked  cannot parse reflect summary: {reason}")
        return UNCHECKED
    offenders = [item for item in items if not has_handle(item)]
    if offenders:
        print(f"fail     {len(offenders)} Backlog item(s) missing a task, issue, PR, or declined-by-user handle")
        for item in offenders:
            print(f"- {item}")
        return FAIL
    print("ok       every Backlog item has a durable handle")
    return OK


if __name__ == "__main__":
    raise SystemExit(main())
