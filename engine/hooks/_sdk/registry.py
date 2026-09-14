from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomllib


@dataclass(frozen=True)
class HookRecord:
    name: str
    mode: str
    why_mode: str
    summary: str
    target_mode: str | None = None
    enabled_by: str | None = None


@dataclass(frozen=True)
class Thresholds:
    min_closed_findings: int
    promote_max_ignore_rate: float
    demote_min_ignore_rate: float
    review_min_ignore_rate: float
    review_min_unchecked_rate: float
    followup_window_checks: int


class HookRegistry(dict[str, HookRecord]):
    def __init__(self, hooks: dict[str, HookRecord], thresholds: Thresholds) -> None:
        super().__init__(hooks)
        self.thresholds = thresholds

    @property
    def hooks(self) -> dict[str, HookRecord]:
        return self


class RegistryError(RuntimeError):
    pass


DEFAULT_PATH = Path(__file__).resolve().parents[1] / "hooks.toml"


def load_registry(path: str | Path | None = None) -> HookRegistry:
    registry_path = Path(path) if path is not None else DEFAULT_PATH
    try:
        with registry_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"could not load hook registry {registry_path}: {exc}") from exc

    thresholds_raw = raw.pop("thresholds", None)
    if not isinstance(thresholds_raw, dict):
        raise RegistryError(f"hook registry {registry_path} is missing [thresholds]")

    hooks: dict[str, HookRecord] = {}
    for name, value in raw.items():
        if not isinstance(value, dict):
            raise RegistryError(f"hook registry {registry_path} has invalid entry {name!r}")
        hooks[name] = _hook_record(registry_path, name, value)

    return HookRegistry(hooks=hooks, thresholds=_thresholds(registry_path, thresholds_raw))


def _hook_record(path: Path, name: str, value: dict[str, Any]) -> HookRecord:
    required = ("mode", "why_mode", "summary")
    missing = [key for key in required if key not in value]
    if missing:
        raise RegistryError(f"hook registry {path} entry {name!r} is missing {', '.join(missing)}")
    return HookRecord(
        name=name,
        mode=_string(path, name, value, "mode"),
        why_mode=_string(path, name, value, "why_mode"),
        summary=_string(path, name, value, "summary"),
        target_mode=_optional_string(path, name, value, "target_mode"),
        enabled_by=_optional_string(path, name, value, "enabled_by"),
    )


def _thresholds(path: Path, value: dict[str, Any]) -> Thresholds:
    return Thresholds(
        min_closed_findings=_integer(path, value, "min_closed_findings"),
        promote_max_ignore_rate=_number(path, value, "promote_max_ignore_rate"),
        demote_min_ignore_rate=_number(path, value, "demote_min_ignore_rate"),
        review_min_ignore_rate=_number(path, value, "review_min_ignore_rate"),
        review_min_unchecked_rate=_number(path, value, "review_min_unchecked_rate"),
        followup_window_checks=_integer(path, value, "followup_window_checks"),
    )


def _string(path: Path, name: str, value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise RegistryError(f"hook registry {path} entry {name!r} has invalid {key}")
    return item


def _optional_string(path: Path, name: str, value: dict[str, Any], key: str) -> str | None:
    item = value.get(key)
    if item is None:
        return None
    if not isinstance(item, str) or not item.strip():
        raise RegistryError(f"hook registry {path} entry {name!r} has invalid {key}")
    return item


def _integer(path: Path, value: dict[str, Any], key: str) -> int:
    item = value.get(key)
    if not isinstance(item, int):
        raise RegistryError(f"hook registry {path} threshold {key!r} must be an integer")
    return item


def _number(path: Path, value: dict[str, Any], key: str) -> float:
    item = value.get(key)
    if not isinstance(item, (int, float)):
        raise RegistryError(f"hook registry {path} threshold {key!r} must be a number")
    return float(item)
