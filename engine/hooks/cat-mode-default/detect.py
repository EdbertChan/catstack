"""Decide whether a UserPromptSubmit turn gets the cat-mode default context.

Two questions, both pure functions over the payload and environment:

1. Is the flag `on`? `CATSTACK_CAT_MODE_DEFAULT` takes `off`, `decide`, or
   `on` (`1`/`true`/`yes` also mean `on`). Only `on` fires this hook;
   `decide` is handled by install.sh, which lets the model pick cat-mode
   itself. The value is read from the process
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
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

import flags  # noqa: E402
from finding import Finding  # noqa: E402

env_file_candidates = flags.env_file_candidates

FLAG = "CATSTACK_CAT_MODE_DEFAULT"
ENV_FILE_VAR = flags.ENV_FILE_VAR
SKILL_RELPATH = os.path.join(".claude", "skills", "cat-mode", "SKILL.md")
STOP_AFTER_ANSWER_FLAG = "CATSTACK_CAT_MODE_STOP_AFTER_ANSWER"
STOP_AFTER_ANSWER_TEXT = (
    f"{STOP_AFTER_ANSWER_FLAG}=on: answering the opening question is a stopping point. "
    "When a result answers a numbered item from the original ask, say which item it "
    "answered and ask whether to continue before launching further work."
)
RULE_PROMPT = "cat-mode-default.prompt"
RULE_AGENT_PROMPT = "cat-mode-default.agent-prompt"

CAT_MODE_COMMAND_RE = re.compile(r"(?:^|\s)/cat-mode\b")


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


def flag_on(environ: dict, cwd: str | None, home: str | None = None) -> bool:
    """True only when a source sets the flag on. An env file that exists and
    could not be read is named on stderr instead of passing as "not set"."""
    found = flags.resolve_flag(FLAG, environ, cwd, home)
    note = found.unreadable_note(FLAG)
    if note:
        print(f"cat-mode-default: {note}", file=sys.stderr)
    return found.on


def typed_cat_mode(prompt: str) -> bool:
    return bool(CAT_MODE_COMMAND_RE.search(prompt or ""))


def installed_skill_path(home: str | None = None) -> str | None:
    home_dir = home or os.path.expanduser("~")
    path = os.path.join(home_dir, SKILL_RELPATH)
    return path if os.path.isfile(path) else None


def context_text(skill_path: str | None) -> str:
    if skill_path is None:
        return f"cat-mode default is on ({FLAG}=on) but cat-mode is not installed: run install.sh."
    return (
        f"cat-mode default is on ({FLAG}=on): read and apply {skill_path} for this turn "
        "-- investigation and execution follow the user's conventions."
    )


def decide(payload: dict, environ: dict | None = None, home: str | None = None) -> str | None:
    """Return the additionalContext to inject, or None to stay silent.

    The stop-after-answer rule is opt-in and lives here rather than in the
    skill text, so turning it on or off is a flag and not an edit. It rides
    along on a typed /cat-mode turn too: the skill loaded by the typed
    command defers to this line.
    """
    env = os.environ if environ is None else environ
    prompt = extract_prompt_text(payload if isinstance(payload, dict) else {})
    cwd = (payload.get("cwd") if isinstance(payload, dict) else None) or os.getcwd()
    if not flag_on(env, cwd, home):
        return None
    lines = [] if typed_cat_mode(prompt) else [context_text(installed_skill_path(home))]
    if flags.flag_on(STOP_AFTER_ANSWER_FLAG, env, cwd, home):
        lines.append(STOP_AFTER_ANSWER_TEXT)
    return "\n".join(lines) or None


AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})
CAT_MODE_MENTION_RE = re.compile(r"cat-mode", re.IGNORECASE)


def mentions_cat_mode(prompt: str) -> bool:
    """Any mention, not just a typed /cat-mode: a parent that already told
    the subagent to read cat-mode must not get a second copy."""
    return bool(CAT_MODE_MENTION_RE.search(prompt or ""))


def agent_prefix_line(skill_path: str | None) -> str:
    if skill_path is None:
        return f"cat-mode default is on ({FLAG}=on) but cat-mode is not installed: run install.sh."
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


def detect(event: dict) -> list[Finding]:
    """Return findings for the shared hook runtime."""
    if not isinstance(event, dict):
        return []
    if event.get("hook_event_name") == "PreToolUse" or event.get("tool_name") in AGENT_TOOL_NAMES:
        return _agent_findings(event)
    return _prompt_findings(event)


def _prompt_findings(event: dict) -> list[Finding]:
    context = decide(event)
    if context is None:
        return []
    prompt = extract_prompt_text(event)
    return [
        Finding(
            rule_id=RULE_PROMPT,
            subject=_prompt_subject(prompt),
            message=context,
            evidence=prompt,
        )
    ]


def _agent_findings(event: dict) -> list[Finding]:
    updated = agent_updated_input(event)
    if updated is None:
        return []
    tool_input = event.get("tool_input")
    original_prompt = ""
    if isinstance(tool_input, dict) and isinstance(tool_input.get("prompt"), str):
        original_prompt = tool_input["prompt"]
    first_line = str(updated.get("prompt") or "").splitlines()[0]
    return [
        Finding(
            rule_id=RULE_AGENT_PROMPT,
            subject=_agent_subject(event, original_prompt),
            message=first_line,
            evidence=original_prompt,
            output={"updatedInput": updated},
        )
    ]


def _prompt_subject(prompt: str) -> str:
    return f"prompt:{_hash_text(prompt)}"


def _agent_subject(event: dict, prompt: str) -> str:
    for key in ("tool_call_id", "toolCallId", "id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return f"tool-call:{value}"
    return f"agent-prompt:{_hash_text(prompt)}"


def _hash_text(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
