from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "hooks.toml"
MODES = frozenset({"off", "warn", "stop"})
WHY_MODES = frozenset({"attention", "outward", "habit"})
TARGET_MODES = MODES | frozenset({"stop-on-deleted"})


@dataclass(frozen=True)
class HookRecord:
    name: str
    mode: str
    why_mode: str
    summary: str
    target_mode: str | None = None
    enabled_by: str | None = None


class RegistryError(RuntimeError):
    pass


def _registry_path(path: str | Path | None) -> Path:
    return Path(path) if path is not None else REGISTRY_PATH


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"Could not load hook registry at {path}: {exc}") from exc


def _optional_string(data: dict[str, Any], key: str, hook: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if isinstance(value, str) and value:
        return value
    raise RegistryError(f"Invalid {key!r} for hook {hook!r}")


def _required_string(data: dict[str, Any], key: str, hook: str) -> str:
    value = data.get(key)
    if isinstance(value, str) and value:
        return value
    raise RegistryError(f"Missing or invalid {key!r} for hook {hook!r}")


def _record(name: str, data: Any) -> HookRecord:
    if not isinstance(data, dict):
        raise RegistryError(f"Invalid registry entry for hook {name!r}")
    mode = _required_string(data, "mode", name)
    why_mode = _required_string(data, "why_mode", name)
    summary = _required_string(data, "summary", name)
    target_mode = _optional_string(data, "target_mode", name)
    enabled_by = _optional_string(data, "enabled_by", name)
    if mode not in MODES:
        raise RegistryError(f"Invalid mode {mode!r} for hook {name!r}")
    if why_mode not in WHY_MODES:
        raise RegistryError(f"Invalid why_mode {why_mode!r} for hook {name!r}")
    if target_mode is not None and target_mode not in TARGET_MODES:
        raise RegistryError(f"Invalid target_mode {target_mode!r} for hook {name!r}")
    return HookRecord(
        name=name,
        mode=mode,
        why_mode=why_mode,
        summary=summary,
        target_mode=target_mode,
        enabled_by=enabled_by,
    )


def load_registry(path: str | Path | None = None) -> tuple[dict[str, HookRecord], dict[str, int | float]]:
    registry_path = _registry_path(path)
    raw = _read_toml(registry_path)
    thresholds = raw.get("thresholds")
    if not isinstance(thresholds, dict):
        raise RegistryError(f"Missing thresholds table in hook registry at {registry_path}")
    hooks = {
        name: _record(name, data)
        for name, data in raw.items()
        if name != "thresholds"
    }
    return hooks, dict(thresholds)
