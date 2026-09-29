"""Stop completion claims for spreadsheet work without a coverage receipt."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "_sdk"))
from finding import Finding  # noqa: E402

RULE_INCOMPLETE = "spreadsheet-completeness-guard.incomplete"
SPREADSHEET_RE = re.compile(r"\b(?:spreadsheet|google sheet|google sheets|workbook|raw tab|aggregation table|chart)\b", re.I)
COMPLETION_RE = re.compile(r"\b(?:complete|completed|done|filled|populated|regenerated|ready|all competitors)\b", re.I)
RECEIPT_RE = re.compile(r"SPREADSHEET_COVERAGE\s*:\s*PASS\b", re.I)
FAIL_RE = re.compile(r"SPREADSHEET_COVERAGE\s*:\s*FAIL\b", re.I)


def claims_completion(message: str) -> bool:
    return bool(SPREADSHEET_RE.search(message or "") and COMPLETION_RE.search(message or ""))


def has_receipt(message: str) -> bool:
    return bool(RECEIPT_RE.search(message or ""))


def decide(payload: dict) -> Finding | None:
    message = str(payload.get("last_assistant_message") or payload.get("message") or "")
    if not claims_completion(message) or has_receipt(message):
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
