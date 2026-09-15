from __future__ import annotations

import os
from typing import Any

import registry


ALLOWED_MODES = {"off", "warn", "stop"}


def _override_name(hook: str) -> str:
    return "CATSTACK_HOOK_MODE_" + hook.upper().replace("-", "_")


def effective_mode(hook: str, event: dict[str, Any] | None = None) -> tuple[str, str]:
    del event
    override = os.environ.get(_override_name(hook))
    if override in ALLOWED_MODES:
        return override, "override"
    loaded = registry.load_registry()
    return loaded.hooks[hook].mode, "registry"
