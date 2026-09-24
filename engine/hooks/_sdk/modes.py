from __future__ import annotations

import os
from typing import Any

from finding import Finding
import registry

VALID_MODES = {"off", "warn", "stop"}
MODE_RANK = {"off": 0, "warn": 1, "stop": 2}


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
) -> tuple[str, str, list[str]]:
    env_name = "CATSTACK_HOOK_MODE_" + hook.upper().replace("-", "_")
    override = os.environ.get(env_name)
    if override in VALID_MODES:
        return override, "override", [override for _finding in findings]

    path = event.get("registry_path") if isinstance(event, dict) else None
    hooks, _thresholds = registry.load_registry(path)
    try:
        record = hooks[hook]
    except KeyError as exc:
        raise registry.RegistryError(f"hook registry has no entry for {hook!r}") from exc

    modes = [
        _valid_mode(record.rule_modes.get(finding.rule_id, record.mode), hook, finding.rule_id)
        for finding in findings
    ]
    if not modes:
        return record.mode, "registry", []
    return max(modes, key=lambda mode: MODE_RANK[mode]), "registry", modes


def _valid_mode(mode: str, hook: str, rule_id: str) -> str:
    if mode not in VALID_MODES:
        raise registry.RegistryError(f"hook registry has invalid mode {mode!r} for {hook}:{rule_id}")
    return mode
