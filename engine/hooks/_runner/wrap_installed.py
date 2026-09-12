from __future__ import annotations

import copy
import json
import os
import re
from collections.abc import Iterator
from pathlib import Path

CONFIGS = (
    ("claude", ".claude/settings.json"),
    ("cursor", ".cursor/hooks.json"),
    ("codex", ".codex/hooks.json"),
)

DIRECT_RE = re.compile(
    r"^python3 \$HOME/\.(claude|cursor|codex)/hooks/([^/\s]+)/([^/\s]+\.py)((?:\s+.*)?)$"
)
RUNNER_RE = re.compile(
    r"^python3 \$HOME/\.(claude|cursor|codex)/hooks/_runner/run\.py(?:\s+--timeout\s+\S+)?\s+([^/\s]+)/([^/\s]+\.py)((?:\s+.*)?)$"
)
HOOKS_REF_RE = re.compile(r"\$HOME/\.(claude|cursor|codex)/hooks/")


def match_direct(command: str) -> tuple[str, str, str, str] | None:
    match = DIRECT_RE.fullmatch(command)
    if not match:
        return None
    harness, hook, script, trailing = match.groups()
    if hook == "_runner":
        return None
    return harness, hook, script, trailing


def _is_runner(command: str) -> bool:
    for harness in ("claude", "cursor", "codex"):
        prefix = f"python3 $HOME/.{harness}/hooks/_runner/run.py"
        if command.startswith(prefix):
            return True
    return False


def _timeout(entry: dict[str, object]) -> float:
    value = entry.get("timeout")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value - 0.5
    return 59.5


def _format_timeout(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return str(value)


def _iter_command_objects(node: object) -> Iterator[dict[str, object]]:
    if isinstance(node, dict):
        if isinstance(node.get("command"), str):
            yield node
        for value in node.values():
            yield from _iter_command_objects(value)
    elif isinstance(node, list):
        for item in node:
            yield from _iter_command_objects(item)


def _catstack_identity(command: str) -> tuple[str, str, str, str] | None:
    direct = match_direct(command)
    if direct:
        return direct
    match = RUNNER_RE.fullmatch(command)
    if not match:
        return None
    harness, hook, script, trailing = match.groups()
    if hook == "_runner":
        return None
    return harness, hook, script, trailing


def _entry_identity(item: object) -> tuple[str, tuple[tuple[str, str, str, str], ...]] | None:
    if not isinstance(item, dict) or not isinstance(item.get("hooks"), list):
        return None
    identities = []
    for hook in item["hooks"]:
        if not isinstance(hook, dict) or not isinstance(hook.get("command"), str):
            continue
        identity = _catstack_identity(hook["command"])
        if identity is not None:
            identities.append(identity)
    if not identities:
        return None
    outer = {key: value for key, value in item.items() if key != "hooks"}
    return json.dumps(outer, sort_keys=True), tuple(identities)


def _dedupe_command_lists(node: object) -> bool:
    changed = False
    if isinstance(node, list):
        seen: set[tuple[str, str, str, str]] = set()
        seen_entries: set[tuple[str, tuple[tuple[str, str, str, str], ...]]] = set()
        kept = []
        for item in node:
            identity = None
            if isinstance(item, dict) and isinstance(item.get("command"), str):
                identity = _catstack_identity(item["command"])
            if identity is not None and identity in seen:
                changed = True
                continue
            if identity is not None:
                seen.add(identity)
            changed = _dedupe_command_lists(item) or changed
            entry_identity = _entry_identity(item)
            if entry_identity is not None and entry_identity in seen_entries:
                changed = True
                continue
            if entry_identity is not None:
                seen_entries.add(entry_identity)
            kept.append(item)
        if len(kept) != len(node):
            node[:] = kept
    elif isinstance(node, dict):
        for value in node.values():
            changed = _dedupe_command_lists(value) or changed
    return changed


def wrap_data(data: object) -> tuple[object, int, list[str]]:
    wrapped = 0
    unwrapped = []
    result = copy.deepcopy(data)
    hooks = result.get("hooks") if isinstance(result, dict) else None
    for entry in _iter_command_objects(hooks):
        command = entry["command"]
        if _is_runner(command):
            continue
        match = match_direct(command)
        if match:
            harness, hook, script, trailing = match
            timeout = _format_timeout(_timeout(entry))
            entry["command"] = (
                f"python3 $HOME/.{harness}/hooks/_runner/run.py --timeout {timeout} "
                f"{hook}/{script}{trailing}"
            )
            wrapped += 1
        elif HOOKS_REF_RE.search(command):
            unwrapped.append(command)
    _dedupe_command_lists(hooks)
    return result, wrapped, unwrapped


def process(path: Path) -> int:
    if not path.exists():
        print(f"skip: {path} missing")
        return 0
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"unchecked: {path}: {exc}")
        return 2
    wrapped, count, unwrapped = wrap_data(data)
    for command in unwrapped:
        print(f"unwrapped: {path}: {command}")
    if wrapped == data:
        print(f"already up to date: {path}")
        return 0
    with path.open("w", encoding="utf-8") as handle:
        json.dump(wrapped, handle, indent=2)
        handle.write("\n")
    print(f"wrapped {count} entr(ies) in {path}")
    return 0


def main() -> int:
    home = Path(os.path.expanduser("~"))
    status = 0
    for _, relative in CONFIGS:
        status = max(status, process(home / relative))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
