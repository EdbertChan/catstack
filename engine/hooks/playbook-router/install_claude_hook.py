#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

SETTINGS_PATH = Path.home() / ".claude/settings.json"
MARKER = "playbook-router/claude_prompt_submit.py"
FRAGMENT_PATH = Path(__file__).parent / "claude.prompt.hook.json"
HOOK_TYPE = "UserPromptSubmit"


def merge_hook(settings: dict, fragment: dict) -> tuple[dict, bool]:
    settings = json.loads(json.dumps(settings))
    entries = settings.setdefault("hooks", {}).setdefault(HOOK_TYPE, [])
    before = json.dumps(entries, sort_keys=True)
    entries[:] = [
        entry for entry in entries
        if not any(MARKER in hook.get("command", "") for hook in entry.get("hooks", []))
    ] + fragment["hooks"][HOOK_TYPE]
    return settings, json.dumps(entries, sort_keys=True) != before


def main() -> None:
    settings = json.loads(SETTINGS_PATH.read_text()) if SETTINGS_PATH.exists() else {}
    settings, changed = merge_hook(settings, json.loads(FRAGMENT_PATH.read_text()))
    if not changed:
        print("ok      claude UserPromptSubmit playbook-router already up to date")
        return
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, indent=2) + "\n")
    print("link    claude UserPromptSubmit playbook-router merged into settings.json")
    print("        (restart Claude Code to pick up the change)")


if __name__ == "__main__":
    main()
