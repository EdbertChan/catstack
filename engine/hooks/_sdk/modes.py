"""Resolve the effective mode for a hook run."""
from __future__ import annotations

import os

from engine.hooks._sdk.registry import RegistryError, load_registry

ALLOWED_MODES = {"off", "warn", "stop"}


def override_name(hook: str) -> str:
    return "CATSTACK_HOOK_MODE_" + hook.upper().replace("-", "_")


def effective_mode(hook: str, event: dict | None = None) -> tuple[str, str]:
    del event
    override = os.environ.get(override_name(hook))
    if override:
        value = override.lower()
        if value not in ALLOWED_MODES:
            raise RegistryError(f"invalid override {override_name(hook)}={override}")
        return value, "override"

    hooks, _thresholds = load_registry()
    try:
        return hooks[hook].mode, "registry"
    except KeyError as exc:
        raise RegistryError(f"hook {hook!r} is not listed in the registry") from exc
