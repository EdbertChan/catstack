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
CODEX_CONFIG = ".codex/config.toml"
NOTIFY_LINE_RE = re.compile(r"^notify[ \t]*=[ \t]*(\[.*\])[ \t]*$", re.MULTILINE)
NOTIFY_TIMEOUT = "59.5"


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


def _notify_script(item: object, home: str) -> tuple[str, str] | None:
    prefix = os.path.join(home, ".codex", "hooks") + "/"
    if not isinstance(item, str) or not item.startswith(prefix):
        return None
    parts = item[len(prefix):].split("/")
    if len(parts) != 2 or parts[0] == "_runner" or not parts[1].endswith(".py"):
        return None
    return parts[0], parts[1]


def _nested_notify_lists(argv: list[object]) -> Iterator[list[object]]:
    for item in argv:
        if isinstance(item, str) and item.startswith("["):
            try:
                nested = json.loads(item)
            except json.JSONDecodeError:
                continue
            if isinstance(nested, list):
                yield nested
                yield from _nested_notify_lists(nested)


def _scripts(argv: list[object], home: str) -> list[str]:
    found = (_notify_script(item, home) for item in argv)
    return [f"{hook}/{script}" for hook, script in filter(None, found)]


def notify_bypasses(argv: list[object], home: str) -> tuple[list[str], list[str]]:
    nested = [script for inner in _nested_notify_lists(argv) for script in _scripts(inner, home)]
    return _scripts(argv, home), nested


RUNNER_SCRIPT_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.py$")


def notify_identities(argv: list[object], home: str) -> list[str]:
    wrapped = [item for item in argv if isinstance(item, str) and RUNNER_SCRIPT_RE.match(item)]
    return wrapped + _scripts(argv, home)


CATSTACK_PATH_SUFFIX_RE = re.compile(r"(?:^|/)hooks/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+\.py)$")
RUNNER_PATH_SUFFIX_RE = re.compile(r"(?:^|/)hooks/_runner/run\.py$")


def _catstack_path_identity(path: str) -> tuple[str, str] | None:
    match = CATSTACK_PATH_SUFFIX_RE.search(path)
    if not match:
        return None
    hook, script = match.groups()
    if hook == "_runner":
        return None
    return hook, script


def _leading_catstack_run(argv: list[object]) -> tuple[list[tuple[str, str]], int]:
    identities: list[tuple[str, str]] = []
    index = 0
    while index < len(argv):
        item = argv[index]
        following = argv[index + 1] if index + 1 < len(argv) else None
        if item != "python3" or not isinstance(following, str):
            break
        direct = _catstack_path_identity(following)
        if direct is not None:
            identities.append(direct)
            index += 2
            continue
        if (
            RUNNER_PATH_SUFFIX_RE.search(following)
            and index + 5 < len(argv)
            and argv[index + 2] == "--notify"
            and argv[index + 3] == "--timeout"
            and isinstance(argv[index + 5], str)
            and RUNNER_SCRIPT_RE.match(argv[index + 5])
        ):
            hook, script = argv[index + 5].split("/", 1)
            identities.append((hook, script))
            index += 6
            continue
        break
    return identities, index


def _strip_previous_notify(tail: list[object]) -> tuple[list[object], list[object] | None]:
    for i, token in enumerate(tail):
        if token != "--previous-notify" or i + 1 >= len(tail) or not isinstance(tail[i + 1], str):
            continue
        try:
            nested = json.loads(tail[i + 1])
        except json.JSONDecodeError:
            return tail, None
        if isinstance(nested, list):
            return tail[:i] + tail[i + 2:], nested
        return tail, None
    return tail, None


def _walk_notify_chain(
    argv: list[object],
    depth: int,
    identities: list[tuple[str, str, int]],
    tails: list[list[object]],
    seen_tails: set[str],
) -> None:
    leading, consumed = _leading_catstack_run(argv)
    identities.extend((hook, script, depth) for hook, script in leading)
    own_tail, nested = _strip_previous_notify(argv[consumed:])
    if own_tail:
        key = json.dumps(own_tail)
        if key not in seen_tails:
            seen_tails.add(key)
            tails.append(own_tail)
    if nested is not None:
        _walk_notify_chain(nested, depth + 1, identities, tails, seen_tails)


def normalize_notify_argv(argv: list[object], home: str) -> tuple[list[object], list[str]]:
    identities: list[tuple[str, str, int]] = []
    tails: list[list[object]] = []
    _walk_notify_chain(argv, 0, identities, tails, set())

    kept: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    messages: list[str] = []
    for hook, script, depth in identities:
        if (hook, script) in seen:
            if depth > 0:
                messages.append(f"nested duplicate of {hook}/{script} removed")
            continue
        if depth > 0:
            script_path = os.path.join(home, ".codex", "hooks", hook, script)
            if not os.path.exists(script_path):
                messages.append(f"dropped {hook}/{script}: {script_path} does not exist")
                continue
            messages.append(f"notify chain nested in another program's argument: {hook}/{script}")
        seen.add((hook, script))
        kept.append((hook, script))

    result: list[object] = []
    for hook, script in kept:
        result += ["python3", os.path.join(home, ".codex", "hooks", hook, script)]
    for tail in tails:
        result += tail
    return result, messages


def wrap_notify(argv: list[object], home: str) -> tuple[list[object], int]:
    runner = os.path.join(home, ".codex", "hooks", "_runner", "run.py")
    wrapped: list[object] = []
    count = 0
    index = 0
    while index < len(argv):
        found = _notify_script(argv[index + 1], home) if index + 1 < len(argv) else None
        if argv[index] == "python3" and found:
            hook, script = found
            wrapped += ["python3", runner, "--notify", "--timeout", NOTIFY_TIMEOUT, f"{hook}/{script}"]
            count += 1
            index += 2
            continue
        wrapped.append(argv[index])
        index += 1
    return wrapped, count


def read_notify(path: Path) -> tuple[str, re.Match[str] | None, list[object] | None]:
    text = path.read_text(encoding="utf-8")
    match = NOTIFY_LINE_RE.search(text)
    if match is None:
        return text, None, None
    argv = json.loads(match.group(1))
    if not isinstance(argv, list):
        raise ValueError("notify is not a JSON array")
    return text, match, argv


def process_notify(path: Path, home: str) -> int:
    if not path.exists():
        print(f"skip: {path} missing")
        return 0
    try:
        text, match, argv = read_notify(path)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"unchecked: {path}: notify: {exc}")
        return 2
    if match is None or argv is None:
        print(f"already up to date: {path} (no notify)")
        return 0
    normalized, messages = normalize_notify_argv(argv, home)
    wrapped, count = wrap_notify(normalized, home)
    for message in messages:
        print(f"unwrapped: {path}: {message}")
    if wrapped == argv:
        print(f"already up to date: {path}")
        return 0
    line = "notify = " + json.dumps(wrapped)
    path.write_text(text[: match.start()] + line + text[match.end():], encoding="utf-8")
    print(f"wrapped {count} notify entr(ies) in {path}")
    return 0


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
    status = max(status, process_notify(home / CODEX_CONFIG, str(home)))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
