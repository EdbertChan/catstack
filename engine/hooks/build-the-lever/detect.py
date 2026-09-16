"""Shared detection for build-the-lever inject hooks.

Deterministic only. No LLM. Fail-open callers catch exceptions.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
from typing import Any

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402
from state import load_state, save_state

REMINDER = (
    "build-the-lever: this work is not a glance-sized edit. Build a "
    "rerunnable script, codemod, generator, or delegate skill before "
    "continuing. Full rules: skills/principle-build-the-lever/SKILL.md. "
    "If the diff is growing past the ask, see "
    "skills/principle-laziness-protocol/SKILL.md (smallest change)."
)

FILES_COUNT_RE = re.compile(r"\b([4-9]|\d{2,})\s+files\b", re.I)
ACROSS_RE = re.compile(r"\bacross\b", re.I)
ACROSS_TARGET_RE = re.compile(r"\b(files|call sites|modules|packages)\b", re.I)
EVERY_CALL_SITE_RE = re.compile(r"\bevery call site\b", re.I)
MIGRATE_RE = re.compile(r"\bmigrat(e|ion)\b", re.I)
BULK_RE = re.compile(r"\bbulk\b", re.I)
ALL_THE_RE = re.compile(r"\ball the (files|call sites|modules)\b", re.I)

MUTATE_TOOLS = {
    "Write",
    "StrReplace",
    "Edit",
    "MultiEdit",
    "NotebookEdit",
}
LEVER_SUFFIXES = (".py", ".sh", ".mjs", ".js", ".ts")
EDIT_THRESHOLD = 4
RULE_BULK_PROMPT = "build-the-lever.bulk-prompt"
RULE_MANY_FILE_EDITS = "build-the-lever.many-file-edits"


def reminder_text() -> str:
    return REMINDER


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


def is_bulk_work(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    if FILES_COUNT_RE.search(text):
        return True
    if ACROSS_RE.search(text) and ACROSS_TARGET_RE.search(text):
        return True
    if EVERY_CALL_SITE_RE.search(text):
        return True
    if MIGRATE_RE.search(text):
        return True
    if BULK_RE.search(text):
        return True
    if ALL_THE_RE.search(text):
        return True
    return False


def _tool_name(payload: dict) -> str:
    return str(
        payload.get("tool_name")
        or payload.get("toolName")
        or payload.get("tool")
        or ""
    )


def _tool_input(payload: dict) -> dict:
    raw = payload.get("tool_input") or payload.get("toolInput") or payload.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


def _mutation_path(payload: dict) -> str | None:
    name = _tool_name(payload)
    if name not in MUTATE_TOOLS:
        return None
    tool_input = _tool_input(payload)
    for key in ("path", "file_path", "filePath", "notebook_path", "notebookPath"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value[0].strip()
    return None


def _is_lever_script(path: str) -> bool:
    lowered = path.replace("\\", "/").lower()
    if not lowered.endswith(LEVER_SUFFIXES):
        return False
    return "codemod" in lowered or "generate" in lowered or "/scripts/" in lowered or lowered.startswith("scripts/")


def remember_bulk_prompt(payload: dict) -> None:
    state = load_state(payload)
    state["cursor_prompt_pending"] = True
    state["cursor_prompt"] = extract_prompt_text(payload)
    save_state(payload, state)


def consume_prompt_pending(payload: dict) -> bool:
    state = load_state(payload)
    if not state.get("cursor_prompt_pending"):
        return False
    state["cursor_prompt_pending"] = False
    state["injected"] = True
    save_state(payload, state)
    return True


def record_file_mutation(payload: dict, path: str | None = None) -> dict[str, Any]:
    state = load_state(payload)
    resolved = path or _mutation_path(payload)
    if not resolved:
        return state
    mutated = list(state.get("mutated_paths") or [])
    if resolved not in mutated:
        mutated.append(resolved)
    state["mutated_paths"] = mutated
    if _tool_name(payload) == "Write" and _is_lever_script(resolved):
        state["lever_written"] = True
    save_state(payload, state)
    return state


def should_inject_for_edits(payload: dict) -> bool:
    state = load_state(payload)
    if state.get("injected"):
        return False
    if state.get("lever_written"):
        return False
    mutated = state.get("mutated_paths") or []
    if len(mutated) < EDIT_THRESHOLD:
        return False
    state["injected"] = True
    save_state(payload, state)
    return True


def mark_injected(payload: dict) -> None:
    state = load_state(payload)
    state["injected"] = True
    state["cursor_prompt_pending"] = False
    save_state(payload, state)


def _event_name(event: dict) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _subject_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _prompt_finding(prompt: str) -> Finding:
    return Finding(
        rule_id=RULE_BULK_PROMPT,
        subject=f"prompt:{_subject_hash(prompt)}",
        message=reminder_text(),
        evidence=prompt,
    )


def _edit_finding(event: dict, current_state: dict[str, Any]) -> Finding:
    path = _mutation_path(event) or str((current_state.get("mutated_paths") or [""])[-1])
    return Finding(
        rule_id=RULE_MANY_FILE_EDITS,
        subject=path,
        message=reminder_text(),
        evidence=", ".join(str(item) for item in current_state.get("mutated_paths") or []),
    )


def detect(event: dict) -> list[Finding]:
    name = _event_name(event)
    prompt = extract_prompt_text(event)
    if name in {"beforeSubmitPrompt", "BeforeSubmitPrompt"}:
        if is_bulk_work(prompt):
            remember_bulk_prompt(event)
        return []

    if name in {"UserPromptSubmit", "userPromptSubmit"} or (prompt and not _tool_name(event)):
        if not is_bulk_work(prompt):
            return []
        mark_injected(event)
        return [_prompt_finding(prompt)]

    current_state = record_file_mutation(event)
    if consume_prompt_pending(event):
        pending_prompt = str(current_state.get("cursor_prompt") or "bulk prompt")
        return [_prompt_finding(pending_prompt)]
    if should_inject_for_edits(event):
        return [_edit_finding(event, current_state)]
    return []
