"""narrow-the-scope as a PostToolUse hook.

The skill's trigger is mechanical: "three or more edits to the same file
without a passing test/build/lint run in between". Previously the
skill asked the model to notice this itself and hand-run token_audit.py.
This hook counts edits per file in session state, resets every file's count
when a verification-shaped Bash command runs, and injects the skill's
reminder once per streak episode when a file reaches EDIT_THRESHOLD.

Inject-only. Never blocks. Fail-open on any error.

Fixture: tests/fixtures/real_edit_streak_2026-09-01.json is the verbatim
tool sequence from a real Invoker session where slack-surface.ts was edited
six times in a row with no check between.
"""
from __future__ import annotations

import os
import re
import sys

SDK_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "_sdk"))
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding

from state import load_state, save_state

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
EDIT_THRESHOLD = 3
RULE_EDIT_STREAK = "narrow-the-scope.edit-streak"

VERIFY_RE = re.compile(
    r"\b(?:pytest|unittest|npm (?:run )?test|pnpm (?:run )?test|yarn test|jest|vitest|"
    r"cargo (?:test|check|build)|go (?:test|build|vet)|make (?:test|check|lint)|tsc\b|eslint|"
    r"ruff|mypy|pyright|flake8|run_all_tests|check_\w+\.py|gradle(?:w)? (?:test|build)|"
    r"swift (?:test|build)|xcodebuild|dotnet test|python3? -m (?:pytest|unittest)|node --test|"
    r"(?:ba)?sh\s+\S*(?:test|check|verify|prove|run)[\w.-]*\.(?:sh|bash)|"
    r"docker\s+(?:build|compose\s+(?:build|up))|"
    r"node --check)",
    re.IGNORECASE,
)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _file_of(payload: dict) -> str:
    inp = payload.get("tool_input") or {}
    return str(inp.get("file_path") or inp.get("notebook_path") or inp.get("path") or "")


def reminder_text(path: str, count: int) -> str:
    return (
        f"narrow-the-scope: {count} edits to {path} with no test/build/lint run in between. "
        "Say so plainly, run the check now, and propose the smallest verifiable slice before "
        "the next edit. Full rules: skills/narrow-the-scope/SKILL.md."
    )


def observe(payload: dict) -> str | None:
    """Update per-session counts; return reminder text when a streak crosses the threshold."""
    findings = detect(payload)
    return findings[0].message if findings else None


def detect(payload: dict) -> list[Finding]:
    """Update per-session counts and return a finding when a file crosses the edit threshold."""
    tool = payload.get("tool_name") or ""
    state = load_state(payload)
    counts: dict = state.get("counts") or {}
    fired: list = state.get("fired") or []
    if tool == "Bash":
        cmd = str((payload.get("tool_input") or {}).get("command") or "")
        if VERIFY_RE.search(cmd):
            state["counts"] = {}
            state["fired"] = []
            save_state(payload, state)
            return []
        executed = [p for p in counts if _basename(p) and _basename(p) in cmd]
        if executed:
            for path in executed:
                counts.pop(path, None)
                if path in fired:
                    fired.remove(path)
            state["counts"] = counts
            state["fired"] = fired
            save_state(payload, state)
        return []
    if tool not in EDIT_TOOLS:
        return []
    path = _file_of(payload)
    if not path:
        return []
    counts[path] = counts.get(path, 0) + 1
    state["counts"] = counts
    findings: list[Finding] = []
    if counts[path] >= EDIT_THRESHOLD and path not in fired:
        fired.append(path)
        state["fired"] = fired
        findings.append(
            Finding(
                rule_id=RULE_EDIT_STREAK,
                subject=path,
                message=reminder_text(path, counts[path]),
                evidence=f"{counts[path]} edits to {path} with no verification-shaped Bash command",
            )
        )
    save_state(payload, state)
    return findings
