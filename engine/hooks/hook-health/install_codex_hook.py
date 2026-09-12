from __future__ import annotations

import copy
import json
import os

HOOKS_PATH = os.path.expanduser("~/.codex/hooks.json")
HERE = os.path.dirname(os.path.abspath(__file__))
FRAGMENT_PATH = os.path.join(HERE, "codex.hook.json")
MARKER = "hook-health/codex_prompt_submit.py"
EVENT = "UserPromptSubmit"


def is_ours(entry: dict) -> bool:
    return any(MARKER in str(hook.get("command", "")) for hook in entry.get("hooks", []))


def merge_hooks(settings: dict) -> dict:
    result = copy.deepcopy(settings)
    hooks = result.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        result["hooks"] = hooks
    with open(FRAGMENT_PATH, encoding="utf-8") as handle:
        incoming = json.load(handle)["hooks"][EVENT]
    existing = hooks.get(EVENT, [])
    hooks[EVENT] = [entry for entry in existing if not is_ours(entry)] + incoming
    return result


def main() -> None:
    settings: dict = {}
    if os.path.exists(HOOKS_PATH):
        with open(HOOKS_PATH, encoding="utf-8") as handle:
            settings = json.load(handle)
    merged = merge_hooks(settings)
    if merged == settings:
        print("ok      codex UserPromptSubmit hook-health already up to date")
        return
    os.makedirs(os.path.dirname(HOOKS_PATH), exist_ok=True)
    with open(HOOKS_PATH, "w", encoding="utf-8") as handle:
        json.dump(merged, handle, indent=2)
        handle.write("\n")
    print("link    codex UserPromptSubmit hook-health merged")


if __name__ == "__main__":
    main()
