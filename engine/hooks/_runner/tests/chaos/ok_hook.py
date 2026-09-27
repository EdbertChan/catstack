from __future__ import annotations

from finding import Finding


def detect(event: dict[str, object]) -> list[Finding]:
    label = str(event.get("chaos_label", "sibling"))
    return [
        Finding(
            rule_id=f"chaos.{label}",
            subject=label,
            message=f"{label} survived chaos dispatch",
            evidence="fixture sibling detector emitted a verdict",
        )
    ]
