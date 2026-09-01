#!/usr/bin/env python3
"""Idempotently prepend auto-pr to Codex's chained notify command."""
from __future__ import annotations

import json
import os
import re

MARKER = "auto-pr/codex_notify.py"
CONFIG_PATH = os.path.expanduser("~/.codex/config.toml")
SCRIPT_PATH = os.path.expanduser("~/.codex/hooks/auto-pr/codex_notify.py")

NOTIFY_RE = re.compile(r"^notify\s*=\s*(\[.*\])\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^\[", re.MULTILINE)


def compute_notify_update(config_text: str, script_path: str):
    """Return ``(updated_text, changed, status_message)`` without writing."""
    match = NOTIFY_RE.search(config_text)
    if match:
        current = json.loads(match.group(1))
        if any(MARKER in str(item) for item in current):
            return config_text, False, "codex notify auto-pr already wired, skipping"
        new_array = ["python3", script_path, *current]
        new_line = "notify = " + json.dumps(new_array)
        updated = config_text[: match.start()] + new_line + config_text[match.end() :]
        return updated, True, f"codex notify auto-pr wired (chaining {len(current)} prior arg(s))"

    new_line = "notify = " + json.dumps(["python3", script_path]) + "\n"
    section = SECTION_RE.search(config_text)
    if section:
        updated = config_text[: section.start()] + new_line + config_text[section.start() :]
    else:
        separator = "\n" if config_text and not config_text.endswith("\n") else ""
        updated = config_text + separator + new_line
    return updated, True, "codex notify auto-pr added (no prior notify command found)"


def main() -> None:
    if not os.path.exists(CONFIG_PATH):
        print(f"skip    {CONFIG_PATH} does not exist, nothing to wire")
        return
    with open(CONFIG_PATH, encoding="utf-8") as handle:
        text = handle.read()
    updated, changed, message = compute_notify_update(text, SCRIPT_PATH)
    print(("link    " if changed else "ok      ") + message)
    if changed:
        with open(CONFIG_PATH, "w", encoding="utf-8") as handle:
            handle.write(updated)


if __name__ == "__main__":
    main()
