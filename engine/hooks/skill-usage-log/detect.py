from __future__ import annotations

import os
import re
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding  # noqa: E402

SKILL_PATH = r"skills(?:-cursor)?/([A-Za-z0-9][A-Za-z0-9_.-]*)/SKILL\.md"
WHOLE_PATH_RE = re.compile(r"^[^\s:]*" + SKILL_PATH + r"$")
SHELL_READ_RE = re.compile(r"\b(?:cat|sed|head|tail|nl|less|more|bat)\b[^;|&\n]*?" + SKILL_PATH)
SKILL_FILE_RE = re.compile(r"[^\s'\";|&]*" + SKILL_PATH)
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
HOOK = "skill-usage-log"
OPT_OUT_ENV = "CATSTACK_SKILL_USAGE_LOG"
RULE_IDS = {
    "skill_tool": f"{HOOK}.skill-tool",
    "read": f"{HOOK}.read",
    "shell_read": f"{HOOK}.shell-read",
    "slash": f"{HOOK}.slash",
    "mention": f"{HOOK}.mention",
}
RULE_SKILLS_UNREADABLE = f"{HOOK}.skills-unreadable"
RULE_BAD_PAYLOAD = f"{HOOK}.bad-payload"


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


def detect(event: dict[str, object], *, harness: str, kind: str) -> list[Finding]:
    if os.environ.get(OPT_OUT_ENV) == "0":
        return []
    if kind == "prompt":
        installed = installed_skills(harness)
        if installed is None:
            return [
                Finding(
                    rule_id=RULE_SKILLS_UNREADABLE,
                    subject=harness,
                    message=f"{harness} skill folders unreadable; typed skill commands unchecked",
                    evidence="skills_unreadable",
                )
            ]
        uses = prompt_uses(event, harness, installed)
    else:
        uses = tool_uses(event)
    return [
        Finding(
            rule_id=RULE_IDS[source],
            subject=_subject(event, kind, skill, source),
            message=f"Skill used: {skill} ({source}).",
            evidence=f"skill={skill}; source={source}",
        )
        for skill, source in uses
    ]


def bad_payload_findings(raw: str, _exc: BaseException) -> list[Finding]:
    if os.environ.get(OPT_OUT_ENV) == "0":
        return []
    return [
        Finding(
            rule_id=RULE_BAD_PAYLOAD,
            subject=raw,
            message="Hook payload could not be read; skill usage was unchecked.",
            evidence="bad_payload",
        )
    ]


def bad_payload_message(exc: BaseException) -> str:
    return f"catstack-hook-error {HOOK}: {type(exc).__name__}: {exc}"


def diagnostic(_event: dict[str, object], findings: list[Finding]) -> str:
    if any(finding.rule_id == RULE_SKILLS_UNREADABLE for finding in findings):
        return f"catstack-hook-error {HOOK}: {findings[0].message}\n"
    return ""


def _subject(event: dict[str, object], kind: str, skill: str, source: str) -> str:
    if kind == "prompt":
        return prompt_text(event) or skill
    for key in ("tool_use_id", "toolUseId", "call_id", "callId"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    tool_input = next((event[key] for key in TOOL_INPUT_KEYS if event.get(key) is not None), {})
    for text in _strings(tool_input):
        if source == "read":
            match = WHOLE_PATH_RE.match(text.strip())
            if match and match.group(1) == skill:
                return text.strip()
        if source == "shell_read":
            for match in SKILL_FILE_RE.finditer(text):
                if match.group(1) == skill:
                    return match.group(0)
    return skill
