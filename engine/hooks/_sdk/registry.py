from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import tomllib


ALLOWED_MODES = frozenset({"off", "warn", "stop"})
ALLOWED_WHY_MODES = frozenset({"attention", "outward", "habit"})
THRESHOLD_KEYS = frozenset(
    {
        "min_closed_findings",
        "promote_max_ignore_rate",
        "demote_min_ignore_rate",
        "review_min_ignore_rate",
        "review_min_unchecked_rate",
        "followup_window_checks",
    }
)
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[1] / "hooks.toml"


class RegistryLoadError(RuntimeError):
    pass


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


@dataclass(frozen=True)
class Registry:
    hooks: dict[str, HookRecord]
    thresholds: Thresholds


def load_registry(path: str | Path | None = None) -> Registry:
    registry_path = Path(path) if path is not None else DEFAULT_REGISTRY_PATH
    try:
        with registry_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except OSError as exc:
        raise RegistryLoadError(f"could not read hook registry {registry_path}: {exc}") from exc

    thresholds_raw = _table(raw.get("thresholds"), registry_path, "thresholds")
    thresholds = _thresholds(thresholds_raw, registry_path)
    hooks = {
        name: _hook_record(name, table, registry_path)
        for name, table in raw.items()
        if name != "thresholds"
    }
    return Registry(hooks=hooks, thresholds=thresholds)


def _table(value: Any, path: Path, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise RegistryLoadError(f"{path}: [{name}] must be a table")
    return value


def _hook_record(name: str, raw: Any, path: Path) -> HookRecord:
    table = _table(raw, path, name)
    return HookRecord(
        name=name,
        mode=_string(table, "mode", path, name),
        why_mode=_string(table, "why_mode", path, name),
        summary=_string(table, "summary", path, name),
        target_mode=_optional_string(table, "target_mode", path, name),
        enabled_by=_optional_string(table, "enabled_by", path, name),
    )


def _thresholds(raw: dict[str, Any], path: Path) -> Thresholds:
    missing = sorted(THRESHOLD_KEYS - raw.keys())
    if missing:
        raise RegistryLoadError(f"{path}: [thresholds] missing {', '.join(missing)}")
    return Thresholds(
        min_closed_findings=_int(raw, "min_closed_findings", path),
        promote_max_ignore_rate=_number(raw, "promote_max_ignore_rate", path),
        demote_min_ignore_rate=_number(raw, "demote_min_ignore_rate", path),
        review_min_ignore_rate=_number(raw, "review_min_ignore_rate", path),
        review_min_unchecked_rate=_number(raw, "review_min_unchecked_rate", path),
        followup_window_checks=_int(raw, "followup_window_checks", path),
    )


def _string(table: dict[str, Any], key: str, path: Path, section: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RegistryLoadError(f"{path}: [{section}] {key} must be a non-empty string")
    return value


def _optional_string(table: dict[str, Any], key: str, path: Path, section: str) -> str | None:
    if key not in table:
        return None
    return _string(table, key, path, section)


def _int(table: dict[str, Any], key: str, path: Path) -> int:
    value = table.get(key)
    if not isinstance(value, int):
        raise RegistryLoadError(f"{path}: [thresholds] {key} must be an integer")
    return value


def _number(table: dict[str, Any], key: str, path: Path) -> float:
    value = table.get(key)
    if not isinstance(value, (int, float)):
        raise RegistryLoadError(f"{path}: [thresholds] {key} must be a number")
    return float(value)
