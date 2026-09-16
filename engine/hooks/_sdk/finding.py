from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Finding:
    rule_id: str
    subject: str
    message: str
    evidence: str
    output: dict[str, Any] | None = None
