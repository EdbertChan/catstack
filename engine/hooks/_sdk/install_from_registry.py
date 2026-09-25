#!/usr/bin/env python3
"""Install hook harness entries from the central hook registry.

The registry decides which hook directories are live. The hook JSON fragments
decide which harness events they attach to. This installer merges those
fragments into the three harness configs and routes every command through the
metrics runner.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
from pathlib import Path
from typing import Iterable

SDK_DIR = Path(__file__).resolve().parent
HOOKS_DIR = SDK_DIR.parent
REPO_DIR = HOOKS_DIR.parent.parent
RUNNER_DIR = HOOKS_DIR / "_runner"
sys.path.insert(0, str(SDK_DIR))
sys.path.insert(0, str(RUNNER_DIR))

from registry import HookRecord, load_registry
from wrap_installed import _catstack_identity, _pick_install_python, wrap_data

HARNESS_CONFIGS = {
    "claude": Path(".claude/settings.json"),
    "cursor": Path(".cursor/hooks.json"),
    "codex": Path(".codex/hooks.json"),
}


def active_hooks(registry_path: Path | None = None) -> dict[str, HookRecord]:
    hooks, _thresholds = load_registry(registry_path)
    return {name: record for name, record in hooks.items() if record.mode != "off"}


def fragment_paths(harness: str, hook_name: str) -> list[Path]:
    hook_dir = HOOKS_DIR / hook_name
    patterns = {
        "claude": ("claude*.hook.json",),
        "cursor": ("cursor*.hook.json", "cursor*.hooks.json"),
        "codex": ("codex*.hook.json",),
    }[harness]
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(sorted(hook_dir.glob(pattern)))
    return sorted(set(paths))


def hooks_for_harness(harness: str, registry_path: Path | None = None) -> list[str]:
    return sorted(active_hooks(registry_path))


def load_json(path: Path) -> dict:
    if path.is_symlink() and not path.exists():
        path.unlink()
        return {}
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def write_json_if_changed(path: Path, data: dict) -> bool:
    old = None
    if path.exists():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            old = None
    if old == data:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    return True


def catstack_hook_name(command: object) -> str | None:
    if not isinstance(command, str):
        return None
    identity = _catstack_identity(command)
    if identity is None:
        return None
    _harness, hook, _script, _trailing = identity
    return hook


def strip_catstack_entries(data: dict) -> dict:
    result = copy.deepcopy(data)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        result["hooks"] = {}
        return result
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            command = entry.get("command")
            if catstack_hook_name(command) is not None:
                continue
            nested = entry.get("hooks")
            if isinstance(nested, list):
                kept_nested = [
                    hook
                    for hook in nested
                    if not (
                        isinstance(hook, dict)
                        and catstack_hook_name(hook.get("command")) is not None
                    )
                ]
                if kept_nested:
                    copied = copy.deepcopy(entry)
                    copied["hooks"] = kept_nested
                    kept_entries.append(copied)
                elif not nested:
                    kept_entries.append(entry)
                continue
            kept_entries.append(entry)
        if kept_entries:
            hooks[event] = kept_entries
        else:
            del hooks[event]
    return result


def merge_fragment(data: dict, fragment: dict) -> None:
    target_hooks = data.setdefault("hooks", {})
    if not isinstance(target_hooks, dict):
        data["hooks"] = {}
        target_hooks = data["hooks"]
    source_hooks = fragment.get("hooks", {})
    if not isinstance(source_hooks, dict):
        return
    for event, entries in source_hooks.items():
        if not isinstance(event, str) or not isinstance(entries, list):
            continue
        target_hooks.setdefault(event, []).extend(copy.deepcopy(entries))


def load_fragment(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def subagent_stop_status(fragment: dict) -> tuple[bool, str]:
    opt_out = fragment.get("subagent_stop")
    if isinstance(opt_out, dict) and opt_out.get("inherit") is False:
        reason = str(opt_out.get("reason") or "").strip()
        if not reason:
            raise ValueError("subagent_stop.inherit is false but no reason is given")
        return False, reason
    return True, ""


def mirror_subagent_stop(data: dict, claude_fragments: Iterable[tuple[str, dict]]) -> list[str]:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        data["hooks"] = {}
        hooks = data["hooks"]
    source = hooks.get("Stop", [])
    managed_names = {name for name, _fragment in claude_fragments}
    existing = hooks.get("SubagentStop", [])
    kept = []
    if isinstance(existing, list):
        for entry in existing:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            commands = [
                hook.get("command")
                for hook in entry.get("hooks", [])
                if isinstance(hook, dict)
            ]
            names = {catstack_hook_name(command) for command in commands}
            if names.isdisjoint(managed_names):
                kept.append(entry)
    added = []
    messages = []
    fragments_by_name = list(claude_fragments)
    for name, fragment in fragments_by_name:
        stop_entries = fragment.get("hooks", {}).get("Stop", [])
        if not stop_entries:
            continue
        inherit, reason = subagent_stop_status(fragment)
        if not inherit:
            messages.append(f"skip    claude SubagentStop {name} (opt-out: {reason})")
            continue
        messages.append(f"ok      claude SubagentStop {name} (mirrored from Stop)")
        for entry in stop_entries:
            copy_entry = copy.deepcopy(entry)
            copy_entry.pop("matcher", None)
            added.append(copy_entry)
    if kept or added:
        hooks["SubagentStop"] = kept + added
    elif "SubagentStop" in hooks:
        del hooks["SubagentStop"]
    return messages


def install(registry_path: Path | None = None) -> int:
    registry = active_hooks(registry_path)
    home = Path(os.path.expanduser("~"))
    python, warning = _pick_install_python()
    if warning:
        sys.stderr.write(warning)
    status = 0
    for harness, relative in HARNESS_CONFIGS.items():
        path = home / relative
        try:
            data = strip_catstack_entries(load_json(path))
            claude_fragments: list[tuple[str, dict]] = []
            for hook_name in sorted(registry):
                for fragment_path in fragment_paths(harness, hook_name):
                    fragment = load_fragment(fragment_path)
                    merge_fragment(data, fragment)
                    if harness == "claude":
                        claude_fragments.append((hook_name, fragment))
            if harness == "claude":
                for message in mirror_subagent_stop(data, claude_fragments):
                    print(message)
            wrapped, _count, unwrapped = wrap_data(data, python)
            for command in unwrapped:
                print(f"unwrapped: {path}: {command}")
                status = max(status, 2)
            changed = write_json_if_changed(path, wrapped)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            print(f"unchecked: {path}: {exc}")
            status = max(status, 2)
            continue
        verb = "link" if changed else "ok  "
        print(f"{verb}    {harness} hooks from registry ({len(hooks_for_harness(harness, registry_path))} hook dir(s))")
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--print-hooks-for", choices=sorted(HARNESS_CONFIGS))
    args = parser.parse_args(argv)
    if args.print_hooks_for:
        for hook in hooks_for_harness(args.print_hooks_for, args.registry):
            print(hook)
        return 0
    return install(args.registry)


if __name__ == "__main__":
    raise SystemExit(main())
