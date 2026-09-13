"""Decide whether a UserPromptSubmit turn gets the cat-mode default context.

Two questions, both pure functions over the payload and environment:

1. Is the flag on? `CATSTACK_CAT_MODE_DEFAULT` is read from the process
   environment first. If it is not set there, a `.env` file is searched in
   this order and the first file that defines the key wins:
     a. the file named by `$CATSTACK_ENV_FILE`, if that variable is set
     b. `<repo root>/.env` for the repo containing the hook's `cwd`
     c. `~/.catstack.env`
   Files are parsed as plain `KEY=VALUE` lines. They are never sourced, and
   no key other than the flag is read back or printed.

2. Does the prompt already contain a typed /cat-mode? Every other prompt gets
   the context when the flag is on.

The text injected names the installed cat-mode SKILL.md so the model reads
the real file rather than a summary. When the skill is not installed the
injected line says so instead.
"""
from __future__ import annotations

import os
import re

FLAG = "CATSTACK_CAT_MODE_DEFAULT"
ENV_FILE_VAR = "CATSTACK_ENV_FILE"
HOME_ENV_FILE = "~/.catstack.env"
SKILL_RELPATH = os.path.join(".claude", "skills", "cat-mode", "SKILL.md")

TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
CAT_MODE_COMMAND_RE = re.compile(r"(?:^|\s)/cat-mode\b")
ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def extract_prompt_text(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
        return "\n".join(parts)
    return ""


def repo_root(start: str | None) -> str | None:
    if not start:
        return None
    current = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(current, ".git")):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def env_file_candidates(environ: dict, cwd: str | None, home: str | None = None) -> list[str]:
    candidates: list[str] = []
    explicit = environ.get(ENV_FILE_VAR)
    if explicit:
        candidates.append(os.path.expanduser(explicit))
    root = repo_root(cwd)
    if root:
        candidates.append(os.path.join(root, ".env"))
    home_dir = home or environ.get("HOME") or os.path.expanduser("~")
    candidates.append(os.path.join(home_dir, HOME_ENV_FILE.replace("~/", "", 1)))
    return candidates


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def read_flag_from_file(path: str, key: str = FLAG) -> str | None:
    """Return the value of `key` from a KEY=VALUE file, or None if the file
    is missing, unreadable, or does not define the key. Nothing else in the
    file is retained."""
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return None
    found: str | None = None
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = ENV_LINE_RE.match(raw)
        if match and match.group(1) == key:
            found = _unquote(match.group(2))
    return found


def resolve_flag(environ: dict, cwd: str | None, home: str | None = None) -> tuple[str | None, str | None]:
    """(value, source). source is "env" or the path of the .env file that
    defined the key; (None, None) when nothing defines it."""
    if FLAG in environ:
        return environ[FLAG], "env"
    for path in env_file_candidates(environ, cwd, home):
        value = read_flag_from_file(path)
        if value is not None:
            return value, path
    return None, None


def flag_on(environ: dict, cwd: str | None, home: str | None = None) -> bool:
    value, _source = resolve_flag(environ, cwd, home)
    return value is not None and value.strip().lower() in TRUE_VALUES


def typed_cat_mode(prompt: str) -> bool:
    return bool(CAT_MODE_COMMAND_RE.search(prompt or ""))


def installed_skill_path(home: str | None = None) -> str | None:
    home_dir = home or os.path.expanduser("~")
    path = os.path.join(home_dir, SKILL_RELPATH)
    return path if os.path.isfile(path) else None


def context_text(skill_path: str | None) -> str:
    if skill_path is None:
        return f"cat-mode default is on ({FLAG}=1) but cat-mode is not installed: run install.sh."
    return (
        f"cat-mode default is on ({FLAG}=1): read and apply {skill_path} for this turn "
        "-- investigation and execution follow the user's conventions."
    )


def decide(payload: dict, environ: dict | None = None, home: str | None = None) -> str | None:
    """Return the additionalContext to inject, or None to stay silent."""
    env = os.environ if environ is None else environ
    prompt = extract_prompt_text(payload if isinstance(payload, dict) else {})
    if typed_cat_mode(prompt):
        return None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if not flag_on(env, cwd or os.getcwd(), home):
        return None
    return context_text(installed_skill_path(home))


AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})
CAT_MODE_MENTION_RE = re.compile(r"cat-mode", re.IGNORECASE)


def mentions_cat_mode(prompt: str) -> bool:
    """Any mention, not just a typed /cat-mode: a parent that already told
    the subagent to read cat-mode must not get a second copy."""
    return bool(CAT_MODE_MENTION_RE.search(prompt or ""))


def agent_prefix_line(skill_path: str | None) -> str:
    if skill_path is None:
        return f"cat-mode default is on ({FLAG}=1) but cat-mode is not installed: run install.sh."
    return f"cat-mode default is on: read and apply {skill_path} before starting."


def agent_updated_input(payload: dict, environ: dict | None = None, home: str | None = None) -> dict | None:
    """For a PreToolUse payload on the Agent tool, return the full tool_input
    with the prompt prefixed by one line, or None to leave the call alone.

    UserPromptSubmit never fires for a subagent (its prompt arrives through
    the Agent tool), so this is the only place the default can reach it.
    `updatedInput` replaces the whole tool_input, so every other field is
    carried over unchanged."""
    env = os.environ if environ is None else environ
    if not isinstance(payload, dict) or payload.get("tool_name") not in AGENT_TOOL_NAMES:
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    if mentions_cat_mode(prompt):
        return None
    cwd = payload.get("cwd")
    if not flag_on(env, cwd or os.getcwd(), home):
        return None
    updated = dict(tool_input)
    updated["prompt"] = agent_prefix_line(installed_skill_path(home)) + "\n\n" + prompt
    return updated
