#!/usr/bin/env python3
"""Idempotently wire diu-stop's codex_notify.py into ~/.codex/config.toml's
`notify` line, chaining whatever was already configured there so installing
this doesn't silently drop it (see codex_notify.py's own docstring for how
the chaining works).

Safe to rerun: if `notify` already mentions codex_notify.py anywhere, does
nothing. Only ever touches the single `notify = [...]` line (or adds one,
placed before the first `[section]` table header, per TOML's rule that
top-level keys must precede tables) -- every other line in config.toml is
left byte-for-byte alone. Does nothing if config.toml doesn't exist at all
(never creates Codex config from scratch).
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_runner"))

from wrap_installed import normalize_notify_argv  # noqa: E402

CONFIG_PATH = os.path.expanduser("~/.codex/config.toml")
SCRIPT_PATH = os.path.expanduser("~/.codex/hooks/diu-stop/codex_notify.py")

NOTIFY_RE = re.compile(r"^notify\s*=\s*(\[.*\])\s*$", re.MULTILINE)
SECTION_RE = re.compile(r"^\[", re.MULTILINE)
HOOKS_MARKER = os.path.join(".codex", "hooks") + os.sep


def _home_for_script(script_path):
    index = script_path.find(HOOKS_MARKER)
    if index == -1:
        return os.path.expanduser("~")
    return script_path[:index]


def compute_notify_update(config_text, script_path):
    """Pure: returns (new_text, changed, message)."""
    match = NOTIFY_RE.search(config_text)

    if match:
        current = json.loads(match.group(1))
        home = _home_for_script(script_path)
        normalized, _messages = normalize_notify_argv(current, home)
        if not any(str(item).endswith("diu-stop/codex_notify.py") for item in normalized):
            normalized, _messages = normalize_notify_argv(["python3", script_path] + current, home)
        if normalized == current:
            return config_text, False, "codex notify already wired, skipping"
        new_line = "notify = " + json.dumps(normalized)
        new_text = config_text[: match.start()] + new_line + config_text[match.end() :]
        return new_text, True, f"codex notify wired (chaining {len(current)} prior arg(s))"

    new_array = ["python3", script_path]
    new_line = "notify = " + json.dumps(new_array) + "\n"
    section = SECTION_RE.search(config_text)
    if section:
        new_text = config_text[: section.start()] + new_line + config_text[section.start() :]
    else:
        sep = "\n" if config_text and not config_text.endswith("\n") else ""
        new_text = config_text + sep + new_line
    return new_text, True, "codex notify added (no prior notify command found)"


def main():
    if not os.path.exists(CONFIG_PATH):
        print(f"skip    {CONFIG_PATH} does not exist, nothing to wire")
        return

    with open(CONFIG_PATH) as f:
        text = f.read()

    new_text, changed, message = compute_notify_update(text, SCRIPT_PATH)
    prefix = "link    " if changed else "ok      "
    print(prefix + message)

    if changed:
        with open(CONFIG_PATH, "w") as f:
            f.write(new_text)


if __name__ == "__main__":
    main()
