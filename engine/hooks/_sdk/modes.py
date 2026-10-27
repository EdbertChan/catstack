from __future__ import annotations

import os
import sys
from typing import Any

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

import counters  # noqa: E402
import flags  # noqa: E402
from finding import Finding  # noqa: E402
import registry  # noqa: E402

VALID_MODES = {"off", "warn", "stop"}
UNCHECKED_LEVEL = "unchecked"
UNDECLARED_LEVEL = ""


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


def effective_level(
    policy: registry.EnforcementPolicy | None,
    harness: str,
    event: dict[str, Any],
    counts: dict[str, int] | None = None,
) -> tuple[str, str]:
    """The level a rule's enforcement policy reaches here, and the reason it is not the declared one.

    A hook that declares no policy has no level here, which is written as an
    empty level rather than as a level the registry never declared.

    The declared level is the policy default, raised to the escalate level once
    the shared counter it names has reached its threshold. A level of hard or
    conditional then has to be checkable: when the capability list names no
    event of the running harness, nothing on this harness can check the rule, so
    the level becomes unchecked and the reason says what was missing. The reason
    is empty whenever the declared level stands.
    """
    if policy is None:
        return UNDECLARED_LEVEL, ""
    running_harness = harness or _running_harness(event)
    level = policy.default
    if policy.escalate is not None:
        reached = counters.state_int((counts or {}).get(policy.escalate.counter))
        if reached >= policy.escalate.threshold:
            level = policy.escalate.to
    if level not in registry.LEVELS_NEEDING_CAPABILITY:
        return level, ""
    if policy.harness_capability(running_harness):
        return level, ""
    return UNCHECKED_LEVEL, _downgrade_reason(level, running_harness, policy, event)


def _downgrade_reason(
    level: str,
    harness: str,
    policy: registry.EnforcementPolicy,
    event: dict[str, Any],
) -> str:
    """Why a declared level could not be checked on the running harness."""
    listed = ", ".join(policy.capability) or "no event"
    event_name = _event_name(event) or "an unnamed event"
    return (
        f"{level} rule unchecked: {harness or 'an unknown harness'} ran {event_name} and the "
        f"capability list names no {harness or 'harness'} event (lists {listed})"
    )


def _running_harness(event: dict[str, Any]) -> str:
    """The harness this event came from, as the shared runtime stamped it."""
    value = event.get("_catstack_harness")
    return value if isinstance(value, str) else ""


def _event_name(event: dict[str, Any]) -> str:
    """The harness event name on this payload."""
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def enforcement_policy(hook: str, event: dict[str, Any]) -> registry.EnforcementPolicy | None:
    """This hook's enforcement policy from the registry, None when the hook declares none."""
    path = event.get("registry_path")
    hooks, _thresholds = registry.load_registry(path if isinstance(path, str) else None)
    try:
        return hooks[hook].enforcement
    except KeyError as exc:
        raise registry.RegistryError(f"hook registry has no entry for {hook!r}") from exc


def finding_enforcement(hook: str, harness: str, event: dict[str, Any]) -> tuple[str, str]:
    """The level this hook's rules reach on the running harness, and any downgrade reason."""
    return effective_level(
        enforcement_policy(hook, event),
        harness,
        event,
        counters.session_counters(event),
    )
