"""Typed result returned by hook detectors."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Finding:
    rule_id: str
    subject: str
    message: str
    evidence: str
