from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

import flags  # noqa: E402
from finding import Finding  # noqa: E402
import registry  # noqa: E402

VALID_MODES = {"off", "warn", "stop"}


def _override(hook: str, event: dict[str, Any]) -> str | None:
    """The machine's CATSTACK_HOOK_MODE_<HOOK> value when it is a valid mode,
    looked up like every other flag: shell, then the .env files."""
    env_name = flags.HOOK_MODE_PREFIX + hook.upper().replace("-", "_")
    cwd = event.get("cwd") if isinstance(event, dict) else None
    found = flags.resolve_flag(env_name, os.environ, cwd if isinstance(cwd, str) else None)
    note = found.unreadable_note(env_name)
    if note:
        print(f"{hook}: {note}", file=sys.stderr)
    value = (found.value or "").strip().lower()
    return value if value in VALID_MODES else None


def effective_mode(hook: str, event: dict[str, Any]) -> tuple[str, str]:
    override = _override(hook, event)
    if override:
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
    override = _override(hook, event)
    if override:
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
