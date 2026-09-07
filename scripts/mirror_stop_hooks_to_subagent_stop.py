#!/usr/bin/env python3
"""Every Claude ``Stop`` hook is also a ``SubagentStop`` hook.

A subagent launched through the Agent tool gets its own transcript and its
own Stop moment, but ``~/.claude/settings.json`` only fires ``Stop`` hooks
for the main thread. Instead of hand-registering each hook twice, this
reads every ``engine/hooks/<name>/claude*.hook.json`` manifest that wires
``Stop`` and mirrors the same command under ``SubagentStop``.

A hook opts out in its own manifest, with a reason, never silently::

    "subagent_stop": {"inherit": false, "reason": "..."}

Idempotent and marker-based like the per-hook installers: every existing
``SubagentStop`` entry whose command points into ``$HOME/.claude/hooks/<name>/``
for a manifest-declared hook is replaced (so an opt-out added later removes
the stale mirror), everything else in settings.json is left alone, and the
file is rewritten only when something changed. Run after the per-hook
installers so a fresh manifest is mirrored in the same ``install.sh`` pass.

Usage:
    python3 scripts/mirror_stop_hooks_to_subagent_stop.py
"""
from __future__ import annotations

import glob
import json
import os
import sys
from dataclasses import dataclass, field

REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS_DIR = os.path.join(REPO_DIR, "engine", "hooks")
SETTINGS_PATH = os.path.expanduser("~/.claude/settings.json")
SOURCE_EVENT = "Stop"
TARGET_EVENT = "SubagentStop"
OPT_OUT_KEY = "subagent_stop"
HOOKS_PREFIX_LITERAL = "$HOME/.claude/hooks/"


@dataclass
class StopManifest:
    name: str
    path: str
    entries: list = field(default_factory=list)
    inherit: bool = True
    reason: str = ""

    @property
    def command_prefix(self) -> str:
        return f"{HOOKS_PREFIX_LITERAL}{self.name}/"


def load_manifests(hooks_dir: str = HOOKS_DIR) -> list[StopManifest]:
    """One record per manifest that wires ``Stop``. Raises ValueError for an
    opt-out with no reason, so a silent exclusion cannot be committed."""
    found: list[StopManifest] = []
    for path in sorted(glob.glob(os.path.join(hooks_dir, "*", "claude*.hook.json"))):
        with open(path, encoding="utf-8") as handle:
            manifest = json.load(handle)
        entries = manifest.get("hooks", {}).get(SOURCE_EVENT)
        if not entries:
            continue
        name = os.path.basename(os.path.dirname(path))
        record = StopManifest(name=name, path=path, entries=entries)
        opt_out = manifest.get(OPT_OUT_KEY)
        if isinstance(opt_out, dict) and opt_out.get("inherit") is False:
            reason = str(opt_out.get("reason") or "").strip()
            if not reason:
                raise ValueError(f"{path}: {OPT_OUT_KEY}.inherit is false but no reason is given")
            record.inherit = False
            record.reason = reason
        found.append(record)
    return found


def _mirrored_entry(entry: dict) -> dict:
    """SubagentStop's matcher filters on agent type, not tool name, so the
    Stop entry's ``"*"`` matcher is dropped: no matcher means every agent."""
    copy = json.loads(json.dumps(entry))
    copy.pop("matcher", None)
    return copy


def _entry_is_for(entry: dict, prefixes: list[str]) -> bool:
    for hook in entry.get("hooks", []) if isinstance(entry, dict) else []:
        command = str(hook.get("command", "")) if isinstance(hook, dict) else ""
        if any(prefix in command for prefix in prefixes):
            return True
    return False


def mirror(settings: dict, manifests: list[StopManifest]) -> tuple[dict, bool]:
    """Pure: returns (new_settings, changed)."""
    settings = json.loads(json.dumps(settings))
    entry_list = settings.setdefault("hooks", {}).setdefault(TARGET_EVENT, [])
    before = json.dumps(entry_list, sort_keys=True)
    managed = [m.command_prefix for m in manifests]
    kept = [e for e in entry_list if not _entry_is_for(e, managed)]
    added = [_mirrored_entry(e) for m in manifests if m.inherit for e in m.entries]
    entry_list[:] = kept + added
    if not entry_list:
        del settings["hooks"][TARGET_EVENT]
    return settings, json.dumps(settings["hooks"].get(TARGET_EVENT, []), sort_keys=True) != before


def main() -> int:
    try:
        manifests = load_manifests()
    except ValueError as exc:
        print(f"error   {exc}", file=sys.stderr)
        return 1
    settings: dict = {}
    if os.path.exists(SETTINGS_PATH):
        with open(SETTINGS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    new_settings, changed = mirror(settings, manifests)
    for manifest in manifests:
        if manifest.inherit:
            print(f"ok      claude {TARGET_EVENT} {manifest.name} (mirrored from {SOURCE_EVENT})")
        else:
            print(f"skip    claude {TARGET_EVENT} {manifest.name} (opt-out: {manifest.reason})")
    if not changed:
        print(f"ok      claude {TARGET_EVENT} mirror already up to date")
        return 0
    os.makedirs(os.path.dirname(SETTINGS_PATH), exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as handle:
        json.dump(new_settings, handle, indent=2)
        handle.write("\n")
    print(f"link    claude {TARGET_EVENT} mirror merged into settings.json")
    print("        (restart Claude Code to pick up the change)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
