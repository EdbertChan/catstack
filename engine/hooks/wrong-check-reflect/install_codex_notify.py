#!/usr/bin/env python3
"""Idempotently wire wrong-check-reflect's codex_notify.py into ~/.codex/config.toml.

Prepends so it chains to whatever notify was already configured (typically
diu-stop). Safe to rerun: if notify already mentions this script, does nothing.
"""
from __future__ import annotations

import json
import os
import re

MARKER = "wrong-check-reflect/codex_notify.py"
CONFIG_PATH = os.path.expanduser("~/.codex/config.toml")
SCRIPT_PATH = os.path.expanduser("~/.codex/hooks/wrong-check-reflect/codex_notify.py")

NOTIFY_RE = re.compile(r"^notify\s*=\s*(\[.*\])\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^\[", re.MULTILINE)


def compute_notify_update(config_text: str, script_path: str):
    """Pure: returns (new_text, changed, message)."""
    match = NOTIFY_RE.search(config_text)

    if match:
        current = json.loads(match.group(1))
        if any(MARKER in str(item) for item in current):
            return config_text, False, "codex notify wrong-check-reflect already wired, skipping"
        new_array = ["python3", script_path] + current
        new_line = "notify = " + json.dumps(new_array)
        new_text = config_text[: match.start()] + new_line + config_text[match.end() :]
        return new_text, True, f"codex notify wrong-check-reflect wired (chaining {len(current)} prior arg(s))"

    new_array = ["python3", script_path]
    new_line = "notify = " + json.dumps(new_array) + "\n"
    section = SECTION_RE.search(config_text)
    if section:
        new_text = config_text[: section.start()] + new_line + config_text[section.start() :]
    else:
        sep = "\n" if config_text and not config_text.endswith("\n") else ""
        new_text = config_text + sep + new_line
    return new_text, True, "codex notify wrong-check-reflect added (no prior notify command found)"


def main() -> None:
    if not os.path.exists(CONFIG_PATH):
        print(f"skip    {CONFIG_PATH} does not exist, nothing to wire")
        return

    with open(CONFIG_PATH) as handle:
        text = handle.read()

    new_text, changed, message = compute_notify_update(text, SCRIPT_PATH)
    prefix = "link    " if changed else "ok      "
    print(prefix + message)

    if changed:
        with open(CONFIG_PATH, "w") as handle:
            handle.write(new_text)


if __name__ == "__main__":
    main()
