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

2. Is the prompt an investigation or execution? A bare slash command, a
   one-word acknowledgement ("ok", "thanks"), or a prompt that already
   invokes /cat-mode is not. Anything longer than a short phrase, or that
   carries a work verb (why, how, fix, build, run, ...), is.

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
MIN_WORK_LENGTH = 12
ACKS = frozenset({
    "ok", "okay", "k", "kk", "yes", "y", "yep", "yup", "no", "nope", "sure",
    "thanks", "thank you", "thx", "ty", "cool", "great", "nice", "good",
    "done", "go", "continue", "proceed", "got it", "lgtm", "np", "fine",
})
WORK_VERBS = (
    "why", "how", "what", "where", "fix", "build", "run", "land", "make",
    "investigate", "check", "debug", "test", "repro", "find", "explain",
    "add", "remove", "delete", "refactor", "write", "implement", "deploy",
    "ship", "merge", "open", "update", "review", "compare", "verify",
)
WORK_VERB_RE = re.compile(r"\b(?:" + "|".join(WORK_VERBS) + r")\b", re.IGNORECASE)
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


def is_work_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    if typed_cat_mode(text):
        return False
    tokens = text.split()
    if text.startswith("/") and len(tokens) == 1:
        return False
    normalized = re.sub(r"[^a-z ]", "", text.lower()).strip()
    if normalized in ACKS:
        return False
    if len(text) > MIN_WORK_LENGTH:
        return True
    return bool(WORK_VERB_RE.search(text))


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
    if not is_work_prompt(prompt):
        return None
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    if not flag_on(env, cwd or os.getcwd(), home):
        return None
    return context_text(installed_skill_path(home))
