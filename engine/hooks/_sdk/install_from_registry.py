#!/usr/bin/env python3
"""Install harness hook configs from the central hook registry.

The registry decides which hook directories are active. The checked-in
``*.hook.json`` fragments decide which harness event each active hook wires.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parent
HOOKS_DIR = SDK_DIR.parent
RUNNER_DIR = HOOKS_DIR / "_runner"
sys.path.insert(0, str(SDK_DIR))
sys.path.insert(0, str(RUNNER_DIR))

from registry import load_registry
from wrap_installed import _catstack_identity, _pick_install_python, wrap_data


CONFIGS = {
    "claude": (Path(".claude/settings.json"), {}),
    "cursor": (Path(".cursor/hooks.json"), {"version": 1, "hooks": {}}),
    "codex": (Path(".codex/hooks.json"), {}),
}


def _json_key(data: object) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))


def _read_json(path: Path, default: dict) -> tuple[dict, list[str]]:
    messages: list[str] = []
    if not path.exists() and not path.is_symlink():
        return copy.deepcopy(default), messages
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if path.is_symlink():
            path.unlink()
            messages.append(f"fix     {path} was a dangling symlink; replaced with a real file")
            return copy.deepcopy(default), messages
        raise
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    if path.is_symlink():
        path.unlink()
        messages.append(f"fix     {path} was a symlink; replaced with a real merged file")
    return data, messages


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _fragment_paths(hook: str, harness: str) -> list[Path]:
    hook_dir = HOOKS_DIR / hook
    paths = [
        path
        for path in hook_dir.glob(f"{harness}*.hook.json")
        if path.is_file()
    ]
    paths.extend(
        path
        for path in hook_dir.glob(f"{harness}*.hooks.json")
        if path.is_file()
    )
    return sorted(paths)


def _load_fragment(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("hooks"), dict):
        raise ValueError(f"{path} must contain a hooks object")
    return data


def _command_hook(command: object) -> str | None:
    if not isinstance(command, str):
        return None
    identity = _catstack_identity(command)
    if identity is None:
        return None
    return identity[1]


def _remove_registry_entries(data: dict, registry_hooks: set[str]) -> None:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        data["hooks"] = {}
        return
    for event, entries in list(hooks.items()):
        if not isinstance(entries, list):
            continue
        kept_entries: list[object] = []
        for entry in entries:
            if not isinstance(entry, dict):
                kept_entries.append(entry)
                continue
            nested = entry.get("hooks")
            if isinstance(nested, list):
                kept_hooks = [
                    hook
                    for hook in nested
                    if not (
                        isinstance(hook, dict)
                        and _command_hook(hook.get("command")) in registry_hooks
                    )
                ]
                if len(kept_hooks) == len(nested):
                    kept_entries.append(entry)
                elif kept_hooks:
                    copy_entry = copy.deepcopy(entry)
                    copy_entry["hooks"] = kept_hooks
                    kept_entries.append(copy_entry)
                continue
            if _command_hook(entry.get("command")) in registry_hooks:
                continue
            kept_entries.append(entry)
        hooks[event] = kept_entries


def _merge_fragment(data: dict, fragment: dict) -> None:
    hooks = data.setdefault("hooks", {})
    if not isinstance(hooks, dict):
        data["hooks"] = {}
        hooks = data["hooks"]
    for event, entries in fragment["hooks"].items():
        if not isinstance(entries, list):
            raise ValueError(f"hook event {event!r} must be a list")
        hooks.setdefault(event, [])
        if not isinstance(hooks[event], list):
            hooks[event] = []
        hooks[event].extend(copy.deepcopy(entries))


def install(home: Path | None = None, registry_path: Path | None = None) -> int:
    home = home or Path.home()
    registry, _thresholds = load_registry(registry_path)
    registry_hooks = set(registry)
    active_hooks = [
        name
        for name, record in registry.items()
        if record.mode != "off"
    ]
    python, warning = _pick_install_python()
    if warning:
        sys.stderr.write(warning)

    changed_any = False
    for harness, (relative, default) in CONFIGS.items():
        path = home / relative
        data, messages = _read_json(path, default)
        before = _json_key(data)
        _remove_registry_entries(data, registry_hooks)
        installed = 0
        for hook in active_hooks:
            for fragment_path in _fragment_paths(hook, harness):
                _merge_fragment(data, _load_fragment(fragment_path))
                installed += 1
        data, _wrapped, _unwrapped = wrap_data(data, python)
        changed = _json_key(data) != before or bool(messages)
        for message in messages:
            print(message)
        if changed:
            _write_json(path, data)
            print(f"link    {harness} hooks from registry ({installed} fragment(s))")
            changed_any = True
        else:
            print(f"ok      {harness} hooks already wired from registry ({installed} fragment(s))")
    if not changed_any:
        print("already wired: registry hook configs")
    return 0


def main() -> int:
    try:
        return install()
    except Exception as exc:
        print(f"error   install_from_registry: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
