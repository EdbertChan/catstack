from __future__ import annotations

from dataclasses import dataclass
from typing import Any

STEP_LOG_FIELDS = ("acted", "runbook", "step", "override_reason", "evidence_ref")


@dataclass(frozen=True)
class Finding:
    rule_id: str
    subject: str
    message: str
    evidence: str
    output: dict[str, Any] | None = None
    acted: str = ""
    runbook: str = ""
    step: str = ""
    override_reason: str = ""
    evidence_ref: str = ""
