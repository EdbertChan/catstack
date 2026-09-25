from __future__ import annotations

import os
from typing import Any

from finding import Finding
import registry

VALID_MODES = {"off", "warn", "stop"}


def effective_mode(hook: str, event: dict[str, Any]) -> tuple[str, str]:
    env_name = "CATSTACK_HOOK_MODE_" + hook.upper().replace("-", "_")
    override = os.environ.get(env_name)
    if override in VALID_MODES:
        return override, "override"

    path = event.get("registry_path") if isinstance(event, dict) else None
    hooks, _thresholds = registry.load_registry(path)
    try:
        return hooks[hook].mode, "registry"
    except KeyError as exc:
        raise registry.RegistryError(f"hook registry has no entry for {hook!r}") from exc


def effective_finding_modes(
    hook: str,
    event: dict[str, Any],
    findings: list[Finding],
) -> tuple[str, str, list[tuple[Finding, str, str]]]:
    """Return the default hook mode and each finding's effective mode.

    A machine override applies to the whole hook. Otherwise a registry rule
    mode can narrow a single rule while the hook keeps its default mode.
    """
    env_name = "CATSTACK_HOOK_MODE_" + hook.upper().replace("-", "_")
    override = os.environ.get(env_name)
    if override in VALID_MODES:
        return override, "override", [(finding, override, "override") for finding in findings]

    path = event.get("registry_path") if isinstance(event, dict) else None
    hooks, _thresholds = registry.load_registry(path)
    try:
        record = hooks[hook]
    except KeyError as exc:
        raise registry.RegistryError(f"hook registry has no entry for {hook!r}") from exc

    rule_modes = record.rule_modes or {}
    finding_modes = []
    for finding in findings:
        mode = rule_modes.get(finding.rule_id, record.mode)
        if mode not in VALID_MODES:
            raise registry.RegistryError(
                f"hook registry has invalid mode {mode!r} for {finding.rule_id!r}"
            )
        finding_modes.append((finding, mode, "registry"))
    return record.mode, "registry", finding_modes
