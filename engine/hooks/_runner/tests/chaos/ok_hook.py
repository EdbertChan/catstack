from __future__ import annotations

from finding import Finding


def detect(event):
    hook_name = str(event.get("_catstack_current_hook") or "chaos-ok")
    return [
        Finding(
            rule_id=f"{hook_name}.spoke",
            subject=hook_name,
            message=f"{hook_name} sibling spoke",
            evidence="chaos fixture",
        )
    ]
