from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402

SKILL_PATH = r"skills(?:-cursor)?/([A-Za-z0-9][A-Za-z0-9_.-]*)/SKILL\.md"
WHOLE_PATH_RE = re.compile(r"^[^\s:]*" + SKILL_PATH + r"$")
SHELL_READ_RE = re.compile(r"\b(?:cat|sed|head|tail|nl|less|more|bat)\b[^;|&\n]*?" + SKILL_PATH)
NOT_A_USE_TOOL_RE = re.compile(r"write|edit|replace|task|agent|todo|plan|glob|grep|fetch|search", re.IGNORECASE)
SLASH_RE = re.compile(r"^\s*/([A-Za-z0-9][A-Za-z0-9_.:-]*)")
MENTION_RE = re.compile(r"(?:^|\s)\$([A-Za-z0-9][A-Za-z0-9_.:-]*)")
PROMPT_KEYS = ("prompt", "user_prompt", "userPrompt", "message")
TOOL_INPUT_KEYS = ("tool_input", "toolInput", "arguments")
SKILL_ROOTS = {
    "claude": (".claude/skills",),
    "cursor": (".cursor/skills", ".cursor/skills-cursor"),
    "codex": (".codex/skills", ".agents/skills"),
}
RULE_IDS = {
    "skill_tool": "skill-usage-log.skill-tool",
    "read": "skill-usage-log.read",
    "shell_read": "skill-usage-log.shell-read",
    "slash": "skill-usage-log.slash",
    "mention": "skill-usage-log.mention",
}


def installed_skills(harness: str, home: str | None = None) -> set[str] | None:
    base = home or os.path.expanduser("~")
    names: set[str] = set()
    for relative in SKILL_ROOTS.get(harness, ()):
        root = os.path.join(base, relative)
        try:
            entries = os.listdir(root)
        except FileNotFoundError:
            continue
        except OSError:
            return None
        names.update(name for name in entries if os.path.isfile(os.path.join(root, name, "SKILL.md")))
    return names


def _strings(node: object) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return []


def tool_uses(payload: dict) -> list[tuple[str, str]]:
    name = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")
    tool_input = next((payload[key] for key in TOOL_INPUT_KEYS if payload.get(key) is not None), {})
    if name == "Skill" and isinstance(tool_input, dict):
        skill = tool_input.get("skill")
        return [(skill.strip(), "skill_tool")] if isinstance(skill, str) and skill.strip() else []
    if NOT_A_USE_TOOL_RE.search(name):
        return []
    found: list[tuple[str, str]] = []
    for text in _strings(tool_input):
        whole = WHOLE_PATH_RE.match(text.strip())
        if whole:
            found.append((whole.group(1), "read"))
            continue
        found.extend((skill, "shell_read") for skill in SHELL_READ_RE.findall(text))
    return list(dict.fromkeys(found))


def prompt_text(payload: dict) -> str:
    for key in PROMPT_KEYS:
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def prompt_uses(payload: dict, harness: str, installed: set[str]) -> list[tuple[str, str]]:
    text = prompt_text(payload)
    found: list[tuple[str, str]] = []
    slash = SLASH_RE.match(text)
    if slash and slash.group(1) in installed:
        found.append((slash.group(1), "slash"))
    if harness == "codex":
        found.extend((name, "mention") for name in MENTION_RE.findall(text) if name in installed)
    return list(dict.fromkeys(found))


def detect(event: dict[str, object]) -> list[Finding]:
    active_harness = str(event.get("_catstack_harness") or event.get("harness") or "")
    event_name = str(event.get("hook_event_name") or event.get("hookEventName") or event.get("event") or "")
    if event_name in {"UserPromptSubmit", "beforeSubmitPrompt"}:
        installed = installed_skills(active_harness)
        if installed is None:
            raise OSError(f"{active_harness} skill folders unreadable; typed skill commands unchecked")
        uses = prompt_uses(event, active_harness, installed)
    else:
        uses = tool_uses(event)
    return [
        Finding(
            rule_id=RULE_IDS[source],
            subject=skill,
            message=f"skill-usage-log: recorded skill {skill!r} via {source}.",
            evidence=source,
        )
        for skill, source in uses
    ]
