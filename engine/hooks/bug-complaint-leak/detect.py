"""Shared detection + checklist for bug-complaint leak hooks.

Deterministic only — no LLM. Fail-open callers catch any exception.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any
from typing import Iterable

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from finding import Finding  # noqa: E402
from state import (  # noqa: E402
    clear_empty_greps,
    consecutive_empty_for_quote,
    grep_signature,
    load_state,
    note_edit,
    note_git_history_lookup,
    record_empty_grep,
    remember_bug_complaint,
    save_state,
)

RULE_BUG_REPORT = "bug-complaint-leak.bug-report"
RULE_EMPTY_GREP = "bug-complaint-leak.empty-grep"
RULE_REPEAT_GREP = "bug-complaint-leak.repeat-grep"

# Phrases that mean "something is wrong in product," not ordinary implement work.
BUG_COMPLAINT_RES = [
    re.compile(r"\bwe have a bug\b", re.I),
    re.compile(r"\bthis is broken\b", re.I),
    re.compile(r"\bit'?s broken\b", re.I),
    re.compile(r"\brepro\b", re.I),
    re.compile(r"\breproduction\b", re.I),
    re.compile(r"doesn'?t keep\b", re.I),
    re.compile(r"does not keep\b", re.I),
    re.compile(r"\bfail[- ]clos", re.I),
    re.compile(r"draft not shown", re.I),
    re.compile(r"nothing was submitted", re.I),
    re.compile(r"\bbug report\b", re.I),
    re.compile(r"\binvestigate (this|the) bug\b", re.I),
]

# Ordinary implement asks that must NOT fire the checklist.
NON_BUG_RES = [
    re.compile(r"^add a comment to\b", re.I),
    re.compile(r"^please add a comment\b", re.I),
    re.compile(r"^rename\b", re.I),
]

QUOTE_RE = re.compile(
    r'"([^"\n]{8,120})"'
    r"|'([^'\n]{8,120})'"
    r"|`([^`\n]{8,120})`"
)
GIT_HISTORY_RE = re.compile(
    r"git\s+(?:grep\s+origin/master|log\s+(?:--all\s+)?-S|log\s+--oneline\s+--all\s+--grep)",
    re.I,
)

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace", "Delete"}
GREP_TOOLS = {"Grep", "grep", "rg"}


def extract_prompt_text(payload: dict) -> str:
    """Best-effort user prompt from Claude or Cursor hook stdin JSON."""
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


def is_bug_complaint(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return False
    for pattern in NON_BUG_RES:
        if pattern.search(text):
            return False
    return any(pattern.search(text) for pattern in BUG_COMPLAINT_RES)


def extract_quoted_symptoms(prompt: str, limit: int = 5) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in QUOTE_RE.finditer(prompt or ""):
        symptom = next((g for g in match.groups() if g), "").strip()
        if not symptom:
            continue
        key = symptom.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(symptom)
        if len(found) >= limit:
            break
    return found


def build_checklist(prompt: str) -> str:
    quotes = extract_quoted_symptoms(prompt)
    sample = quotes[0] if quotes else "<quoted symptom or error string>"
    quoted_list = ", ".join(f"`{q}`" for q in quotes) if quotes else "(none extracted — use the user-visible error string)"
    return "\n".join(
        [
            "Bug-complaint checklist (inject-only; fail-open; you still run the git):",
            f"1. Quoted product copy seen: {quoted_list}",
            f"2. How-we-got-here: `git log --all -S '{sample}'` and `git log --oneline --all --grep=<symptom>`.",
            "3. If workspace Grep of that copy is empty, run `git grep origin/master -e '<symptom>'` / `git log --all -S` before more local Grep.",
            "4. Class-search (CLAUDE.md): sibling jobs/hosts of the shared symbol; `gh pr list --search <file>` for unlanded fixes; fossil tests (`fails closed`, `toContainText` on the error string).",
            "5. Name every production host of the shared symbol before scoping the fix.",
            "Do not treat stack Non-goals that leave a shared policy alone as evidence the magic number is right.",
        ]
    )


def any_quote_in_pattern(pattern: str, quotes: Iterable[str]) -> bool:
    lowered = (pattern or "").lower()
    for quote in quotes:
        if quote.lower() in lowered or lowered in quote.lower():
            return True
    return False


def _event_name(event: dict[str, Any]) -> str:
    return str(
        event.get("hook_event_name")
        or event.get("hookEventName")
        or event.get("event_name")
        or event.get("event")
        or event.get("type")
        or ""
    )


def _set_event_name(event: dict[str, Any], name: str) -> None:
    if not _event_name(event):
        event["hook_event_name"] = name


def _tool_name(event: dict[str, Any]) -> str:
    return str(event.get("tool_name") or event.get("toolName") or event.get("tool") or "")


def _tool_input(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("tool_input") or event.get("toolInput") or event.get("arguments") or {}
    return raw if isinstance(raw, dict) else {}


def _tool_result_text(event: dict[str, Any]) -> str:
    for key in ("tool_result", "toolResult", "result", "output", "stdout"):
        value = event.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for inner in ("content", "output", "stdout", "text"):
                if isinstance(value.get(inner), str):
                    return value[inner]
    return ""


def _looks_empty_grep(result: str) -> bool:
    text = (result or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "no matches",
            "no files with matches",
            "0 matches",
            "found 0",
            "(no results)",
        )
    )


def _subject_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pending_cursor_checklist(event: dict[str, Any]) -> Finding | None:
    state = load_state(event)
    if not state.get("cursor_checklist_pending"):
        return None
    bug = state.get("bug_complaint") or {}
    checklist = bug.get("checklist")
    if not checklist:
        return None
    state["cursor_checklist_pending"] = False
    save_state(event, state)
    return Finding(
        rule_id=RULE_BUG_REPORT,
        subject=f"checklist:{_subject_hash(str(bug.get('prompt_preview') or checklist))}",
        message=str(checklist),
        evidence="pending cursor bug-complaint checklist",
    )


def _detect_prompt(event: dict[str, Any]) -> list[Finding]:
    prompt = extract_prompt_text(event)
    if not is_bug_complaint(prompt):
        return []
    _set_event_name(event, "UserPromptSubmit")
    checklist = build_checklist(prompt)
    quotes = extract_quoted_symptoms(prompt)
    remember_bug_complaint(event, prompt, quotes, checklist)
    if _event_name(event) in {"beforeSubmitPrompt", "BeforeSubmitPrompt"}:
        return []
    return [
        Finding(
            rule_id=RULE_BUG_REPORT,
            subject=f"prompt:{_subject_hash(prompt)}",
            message=checklist,
            evidence=", ".join(quotes[:3]),
        )
    ]


def _detect_pretool_grep(event: dict[str, Any]) -> list[Finding]:
    _set_event_name(event, "PreToolUse")
    tool_input = _tool_input(event)
    pattern = str(tool_input.get("pattern") or tool_input.get("query") or "")
    path = tool_input.get("path")
    glob = tool_input.get("glob")
    if isinstance(path, list):
        path = path[0] if path else ""
    path_s = str(path or "")
    glob_s = str(glob or "")
    current_state = load_state(event)
    bug = current_state.get("bug_complaint") or {}
    quotes = list(bug.get("quotes") or [])
    sig = grep_signature(pattern, path_s, glob_s) if pattern.strip() else None

    findings: list[Finding] = []
    if sig and current_state.get("last_grep_sig") == sig:
        findings.append(
            Finding(
                rule_id=RULE_REPEAT_GREP,
                subject=f"grep:{sig}",
                message=(
                    "Exact-repeat Grep with no intervening edit. Change path/pattern/glob, "
                    "or Read the file after an edit — repeating the same empty Grep is not progress."
                ),
                evidence=pattern,
            )
        )

    if quotes and consecutive_empty_for_quote(current_state, quotes) >= 2 and not current_state.get("did_origin_lookup"):
        sample = str(quotes[0])
        findings.append(
            Finding(
                rule_id=RULE_EMPTY_GREP,
                subject=f"quote:{_subject_hash(sample)}",
                message=(
                    "Workspace Grep of user-quoted product copy returned empty twice. "
                    f"Before more local Grep, run: git grep origin/master -e {sample!r} "
                    f"and/or git log --all -S {sample!r}. Fail-open checklist lives in bug-complaint-leak."
                ),
                evidence=sample,
            )
        )

    if sig and not findings:
        current_state["last_grep_sig"] = sig
        save_state(event, current_state)
    return findings


def _record_tool_outcome(event: dict[str, Any]) -> None:
    name = _tool_name(event)
    tool_input = _tool_input(event)

    if name in EDIT_TOOLS:
        note_edit(event)
        return

    if name in {"Bash", "Shell", "shell"}:
        command = str(tool_input.get("command") or "")
        if GIT_HISTORY_RE.search(command):
            note_git_history_lookup(event)
        return

    if name not in GREP_TOOLS:
        return

    pattern = str(tool_input.get("pattern") or tool_input.get("query") or "")
    path = tool_input.get("path")
    glob = tool_input.get("glob")
    if isinstance(path, list):
        path = path[0] if path else ""
    result = _tool_result_text(event)
    if _looks_empty_grep(result):
        record_empty_grep(event, pattern, str(path or ""), str(glob or ""))
    else:
        clear_empty_greps(event)


def _is_post_tool_event(event: dict[str, Any]) -> bool:
    name = _event_name(event)
    if name in {"PostToolUse", "PostToolUseFailure", "postToolUse"}:
        return True
    return any(key in event for key in ("tool_result", "toolResult", "result", "output", "stdout"))


def detect(event: dict[str, Any]) -> list[Finding]:
    if not isinstance(event, dict):
        return []
    if _tool_name(event):
        if _is_post_tool_event(event):
            _set_event_name(event, "PostToolUse")
            _record_tool_outcome(event)
            pending = _pending_cursor_checklist(event)
            return [pending] if pending else []
        if _tool_name(event) in GREP_TOOLS:
            return _detect_pretool_grep(event)
        return []
    return _detect_prompt(event)


def detect_cursor_before_submit(event: dict[str, Any]) -> list[Finding]:
    if isinstance(event, dict) and not _event_name(event):
        event["hook_event_name"] = "beforeSubmitPrompt"
    return detect(event)
