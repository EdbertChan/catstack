#!/usr/bin/env python3
"""Remove ~/.claude/settings.json hook entries whose script no longer exists.

Deleted worktrees leave behind hook commands such as
``python3 $HOME/.claude/hooks/<name>/<file>.py`` whose target file is gone;
Claude Code then prints an error on every tool call. This does a targeted
removal in the same spirit as the marker-based merge installers: it touches
only hook entries whose command names a path under ``$HOME/.claude/hooks/``
that does not exist, drops matcher groups left empty, and rewrites the file
only when something changed. Every other key, matcher, and command is kept.

Usage:
    python3 scripts/prune_dead_hook_entries.py
"""
from __future__ import annotations

import json
import os
import sys

SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
HOOKS_PREFIX_LITERAL = "$HOME/.claude/hooks/"


def _hook_paths(command: str, home: str) -> list[str]:
    """Return every whitespace token of ``command`` that lives under the
    Claude hooks directory, with ``$HOME`` expanded."""
    expanded_prefix = os.path.join(home, ".claude", "hooks") + os.sep
    found = []
    for token in str(command).split():
        token = token.strip("\"'")
        if token.startswith(HOOKS_PREFIX_LITERAL):
            found.append(expanded_prefix + token[len(HOOKS_PREFIX_LITERAL):])
        elif token.startswith(expanded_prefix):
            found.append(token)
    return found


def prune(settings: dict, exists, home: str | None = None) -> tuple[dict, list[str]]:
    """Pure: returns (new_settings, removed_descriptions).

    ``exists`` is a predicate on an absolute path so tests can fake the
    filesystem. Only entries whose command references a missing path under
    ``$HOME/.claude/hooks/`` are dropped."""
    home = home or os.path.expanduser("~")
    settings = json.loads(json.dumps(settings))  # deep copy, no external dep
    removed: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return settings, removed
    for event, groups in list(hooks.items()):
        if not isinstance(groups, list):
            continue
        kept_groups = []
        for group in groups:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(entries, list):
                kept_groups.append(group)
                continue
            kept_entries = []
            for entry in entries:
                command = entry.get("command") if isinstance(entry, dict) else None
                paths = _hook_paths(command, home) if command else []
                dead = [p for p in paths if not exists(p)]
                if dead:
                    removed.append(f"{event}: {command} (missing {dead[0]})")
                    continue
                kept_entries.append(entry)
            if kept_entries:
                group["hooks"] = kept_entries
                kept_groups.append(group)
            elif not entries:
                kept_groups.append(group)  # was already empty; not ours to judge
        hooks[event] = kept_groups
    return settings, removed


def main() -> int:
    if not os.path.exists(SETTINGS_PATH):
        print("ok      no settings.json; nothing to prune")
        return 0
    with open(SETTINGS_PATH) as f:
        settings = json.load(f)
    new_settings, removed = prune(settings, os.path.exists)
    if not removed:
        print("ok      no dead hook entries")
        return 0
    with open(SETTINGS_PATH, "w") as f:
        json.dump(new_settings, f, indent=2)
        f.write("\n")
    for line in removed:
        print(f"prune   dead hook entry {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
