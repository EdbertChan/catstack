from __future__ import annotations

import copy
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MARKER = "skill-usage-log/"


def merge(config: dict, fragment: dict) -> dict:
    result = copy.deepcopy(config)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        result["hooks"] = hooks
    for event, incoming in fragment["hooks"].items():
        existing = hooks.get(event, [])
        hooks[event] = [entry for entry in existing if MARKER not in json.dumps(entry)] + incoming
    return result


def install(harness: str, config_path: str, default: dict) -> None:
    path = os.path.expanduser(config_path)
    config = copy.deepcopy(default)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            config = json.load(handle)
    with open(os.path.join(HERE, f"{harness}.hook.json"), encoding="utf-8") as handle:
        fragment = json.load(handle)
    merged = merge(config, fragment)
    if merged == config and not os.path.islink(path):
        print(f"ok      {harness} skill-usage-log already up to date")
        return
    if os.path.islink(path):
        os.unlink(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    print(f"link    {harness} skill-usage-log merged into {path}")
