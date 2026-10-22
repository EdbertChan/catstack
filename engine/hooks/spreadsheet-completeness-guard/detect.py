"""Stop completion claims for spreadsheet work without a coverage receipt.

The reply's words alone are not enough: "the chart row ... Done." matched
the vocabulary with no spreadsheet anywhere in the session. The guard fires
only when the transcript shows spreadsheet work -- a Sheets or Excel tool
call, or a written .xlsx/.csv file. With no transcript to read, it reports
the reply unchecked instead of blocking it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_sdk"))
from finding import Finding  # noqa: E402

RULE_INCOMPLETE = "spreadsheet-completeness-guard.incomplete"
RULE_UNCHECKED = "spreadsheet-completeness-guard.unchecked"
SPREADSHEET_RE = re.compile(r"\b(?:spreadsheet|google sheet|google sheets|workbook|raw tab|aggregation table)\b", re.I)
COMPLETION_RE = re.compile(r"\b(?:complete|completed|done|filled|populated|regenerated|ready|all competitors)\b", re.I)
RECEIPT_RE = re.compile(r"SPREADSHEET_COVERAGE\s*:\s*PASS\b", re.I)
FAIL_RE = re.compile(r"SPREADSHEET_COVERAGE\s*:\s*FAIL\b", re.I)
SHEET_TOOL_RE = re.compile(r"sheets?|xlsx|excel|spreadsheet", re.I)
SHEET_FILE_RE = re.compile(r"[\w.-]+\.(?:xlsx|xlsm|xls|csv)\b", re.I)
WRITE_TOOLS = {"write", "edit", "multiedit", "notebookedit", "apply_patch", "write_file", "edit_file"}
WRITE_IN_COMMAND_RE = re.compile(
    r">\s*\S*\.(?:xlsx|xlsm|csv)\b|\bto_csv\b|\bto_excel\b|\.save\(|\bopenpyxl\b|\bxlsxwriter\b"
    r"|\bcsv\.writer\b|\btee\s",
    re.I,
)


def claims_completion(message: str) -> bool:
    return bool(SPREADSHEET_RE.search(message or "") and COMPLETION_RE.search(message or ""))


def has_receipt(message: str) -> bool:
    return bool(RECEIPT_RE.search(message or ""))


def _tool_calls(node: object):
    """Every (name, arguments-as-text) tool call under one transcript row.

    Claude rows carry `tool_use` blocks with `input`; Codex rows carry
    `function_call` payloads with `arguments`."""
    if isinstance(node, dict):
        name = node.get("name")
        args = node.get("input", node.get("arguments"))
        if isinstance(name, str) and args is not None and node.get("type") in ("tool_use", "function_call", None):
            yield name, args if isinstance(args, str) else json.dumps(args, default=str)
        for value in node.values():
            yield from _tool_calls(value)
    elif isinstance(node, list):
        for value in node:
            yield from _tool_calls(value)


def is_spreadsheet_call(name: str, args: str) -> bool:
    if SHEET_TOOL_RE.search(name):
        return True
    if not SHEET_FILE_RE.search(args):
        return False
    return name.lower() in WRITE_TOOLS or bool(WRITE_IN_COMMAND_RE.search(args))


def spreadsheet_work(payload: dict) -> tuple[bool | None, str]:
    """(True, "") when the transcript shows spreadsheet work, (False, "")
    when it shows none, (None, reason) when it could not be read."""
    path = payload.get("transcript_path")
    if not isinstance(path, str) or not path:
        return None, "the Stop payload names no transcript"
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if any(is_spreadsheet_call(name, args) for name, args in _tool_calls(row)):
                    return True, ""
    except (OSError, UnicodeError) as exc:
        return None, f"cannot read {path}: {exc}"
    return False, ""


def _note_unchecked(payload: dict, reason: str) -> None:
    text = (f"spreadsheet-completeness-guard: this reply claims spreadsheet completion, "
            f"but whether this session did spreadsheet work is unchecked: {reason}.")
    print(text, file=sys.stderr)
    payload["_catstack_unchecked_findings"] = [
        Finding(rule_id=RULE_UNCHECKED, subject="spreadsheet work unchecked", message=text, evidence=text)]


def decide(payload: dict) -> Finding | None:
    message = str(payload.get("last_assistant_message") or payload.get("message") or "")
    if not claims_completion(message) or has_receipt(message):
        return None
    work, reason = spreadsheet_work(payload)
    if work is None:
        _note_unchecked(payload, reason)
        return None
    if not work:
        return None
    try:
        retry_count = int(payload.get("spreadsheet_retry_count") or 0)
    except (TypeError, ValueError):
        retry_count = 0
    retry_count = max(0, min(retry_count, 3))
    if FAIL_RE.search(message):
        return Finding(
            rule_id=RULE_INCOMPLETE,
            subject="spreadsheet coverage failure",
            message="Coverage failed after the bounded retry loop. Do not generate or declare the table/chart complete; list the unresolved entity/period keys.",
            evidence=f"SPREADSHEET_COVERAGE: FAIL; retry {retry_count}/3",
        )
    return Finding(
        rule_id=RULE_INCOMPLETE,
        subject="spreadsheet completion claim",
        message=(f"Do not declare spreadsheet data complete until the expected-entity coverage "
                 f"validator has passed. Run source collection retry {min(retry_count + 1, 3)}/3; "
                 "add source-backed rows or state unresolved entity/period keys. "
                 "Only SPREADSHEET_COVERAGE: PASS permits completion."),
        evidence=f"completion claim without a coverage receipt; retry {retry_count}/3",
    )


def detect(event: dict[str, object]) -> list[Finding]:
    finding = decide(event)
    return [] if finding is None else [finding]
