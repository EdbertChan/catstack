from __future__ import annotations

import os
import shlex
import tempfile
from pathlib import Path
from typing import Any

HOOK_NAME = "bound-tool-result"
HELPER_REL_PARTS = ("corpus", "skills", "principle-guard-the-context-window", "scripts", "capture_tool_result.py")
SHELL_TOOL_NAMES = {
    "Bash",
    "bash",
    "Shell",
    "shell",
    "exec_command",
    "Exec",
}
ALREADY_WRAPPED_MARKERS = (
    "capture_tool_result.py",
    "bound-tool-result",
)


def tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    tool = payload.get("tool")
    if isinstance(tool, dict):
        for key in ("name", "tool_name"):
            value = tool.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def tool_input(payload: dict) -> dict:
    for key in ("tool_input", "toolInput", "input", "arguments"):
        value = payload.get(key)
        if isinstance(value, dict):
            return value
    tool = payload.get("tool")
    if isinstance(tool, dict) and isinstance(tool.get("input"), dict):
        return tool["input"]
    return {}


def extract_command(payload: dict) -> str | None:
    inp = tool_input(payload)
    for key in ("command", "cmd", "script"):
        value = inp.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    argv = inp.get("argv") or inp.get("args")
    if isinstance(argv, list) and all(isinstance(x, str) for x in argv) and argv:
        return shlex.join(argv)
    for key in ("command", "cmd"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def already_wrapped(command: str) -> bool:
    return any(marker in command for marker in ALREADY_WRAPPED_MARKERS)


def resolve_helper(home: str | None = None, environ: dict | None = None) -> Path | None:
    env = os.environ if environ is None else environ
    explicit = env.get("CATSTACK_CAPTURE_HELPER")
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
        return None
    root = home or env.get("HOME") or str(Path.home())
    candidates = [
        Path(root) / ".claude" / "skills" / "principle-guard-the-context-window" / "scripts" / "capture_tool_result.py",
        Path(root) / ".cursor" / "skills" / "principle-guard-the-context-window" / "scripts" / "capture_tool_result.py",
        Path(root) / ".codex" / "skills" / "principle-guard-the-context-window" / "scripts" / "capture_tool_result.py",
    ]
    here = Path(__file__).resolve()
    # engine/hooks/bound-tool-result/detect.py -> repo root is parents[3]
    candidates.append(here.parents[3].joinpath(*HELPER_REL_PARTS))
    for path in candidates:
        try:
            if path.is_file():
                return path
        except OSError:
            continue
    return None


def artifact_root(environ: dict | None = None) -> str:
    env = os.environ if environ is None else environ
    override = env.get("CATSTACK_TOOL_CAPTURE_ROOT")
    if override:
        return override
    return str(Path(tempfile.gettempdir()) / "catstack-tool-captures")


def wrap_command(command: str, helper: Path, environ: dict | None = None) -> str:
    root = artifact_root(environ)
    return (
        f"python3 {shlex.quote(str(helper))} "
        f"--artifact-root {shlex.quote(root)} -- "
        f"sh -c {shlex.quote(command)}"
    )


def decide(payload: dict, home: str | None = None, environ: dict | None = None) -> dict[str, Any]:
    """Return an explicit decision for a PreToolUse payload.

    Outcomes:
      unrelated — not a shell tool
      already_wrapped — leave alone
      rewrite — provide wrapped_command
      deny — helper missing; do not run raw command
      unchecked — unreadable / empty command on a shell tool
    """
    if not isinstance(payload, dict):
        return {"outcome": "unchecked", "reason": "payload is not an object"}
    name = tool_name(payload)
    if name and name not in SHELL_TOOL_NAMES:
        return {"outcome": "unrelated", "reason": f"tool {name} is not a shell tool"}
    if not name and extract_command(payload) is None:
        return {"outcome": "unrelated", "reason": "no shell tool name or command"}
    command = extract_command(payload)
    if command is None:
        if name in SHELL_TOOL_NAMES:
            return {"outcome": "unchecked", "reason": "shell tool with no command string"}
        return {"outcome": "unrelated", "reason": "no command"}
    if already_wrapped(command):
        return {"outcome": "already_wrapped", "command": command}
    helper = resolve_helper(home=home, environ=environ)
    if helper is None:
        return {
            "outcome": "deny",
            "command": command,
            "reason": (
                "bound-tool-result: capture helper missing. "
                "Install catstack (principle-guard-the-context-window) or set CATSTACK_CAPTURE_HELPER. "
                "Refusing to run the raw shell command."
            ),
        }
    wrapped = wrap_command(command, helper, environ=environ)
    return {
        "outcome": "rewrite",
        "command": command,
        "wrapped_command": wrapped,
        "helper": str(helper),
    }


def updated_tool_input(payload: dict, wrapped_command: str) -> dict:
    inp = dict(tool_input(payload))
    if "command" in inp or not inp:
        inp["command"] = wrapped_command
    elif "cmd" in inp:
        inp["cmd"] = wrapped_command
    else:
        inp["command"] = wrapped_command
    return inp
