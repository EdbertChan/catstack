from __future__ import annotations

import os
from typing import Any

import registry

VALID_MODES = {"off", "warn", "stop"}


def effective_mode(hook: str, event: dict[str, Any]) -> tuple[str, str]:
    env_name = "CATSTACK_HOOK_MODE_" + hook.upper().replace("-", "_")
    override = os.environ.get(env_name)
    if override in VALID_MODES:
        return override, "override"

    path = event.get("registry_path") if isinstance(event, dict) else None
    loaded = registry.load_registry(path)
    try:
        return loaded.hooks[hook].mode, "registry"
    except KeyError as exc:
        raise registry.RegistryError(f"hook registry has no entry for {hook!r}") from exc
