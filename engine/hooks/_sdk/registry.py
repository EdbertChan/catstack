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


class Registry(dict[str, HookRecord]):
    def __init__(self, hooks: dict[str, HookRecord], thresholds: Thresholds) -> None:
        super().__init__(hooks)
        self.thresholds = thresholds

    @property
    def hooks(self) -> "Registry":
        return self


class RegistryLoadError(Exception):
    pass


def default_registry_path() -> Path:
    return Path(__file__).resolve().parents[1] / "hooks.toml"


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RegistryLoadError(f"could not load hook registry {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RegistryLoadError(f"could not load hook registry {path}: top level is not a table")
    return data


def _record(name: str, data: Any, path: Path) -> HookRecord:
    if not isinstance(data, dict):
        raise RegistryLoadError(f"could not load hook registry {path}: {name} is not a table")
    try:
        return HookRecord(
            name=name,
            mode=data["mode"],
            why_mode=data["why_mode"],
            summary=data["summary"],
            target_mode=data.get("target_mode"),
            enabled_by=data.get("enabled_by"),
        )
    except KeyError as exc:
        raise RegistryLoadError(
            f"could not load hook registry {path}: {name} missing {exc.args[0]}"
        ) from exc


def _thresholds(data: Any, path: Path) -> Thresholds:
    if not isinstance(data, dict):
        raise RegistryLoadError(f"could not load hook registry {path}: thresholds is not a table")
    try:
        return Thresholds(
            min_closed_findings=data["min_closed_findings"],
            promote_max_ignore_rate=data["promote_max_ignore_rate"],
            demote_min_ignore_rate=data["demote_min_ignore_rate"],
            review_min_ignore_rate=data["review_min_ignore_rate"],
            review_min_unchecked_rate=data["review_min_unchecked_rate"],
            followup_window_checks=data["followup_window_checks"],
        )
    except KeyError as exc:
        raise RegistryLoadError(
            f"could not load hook registry {path}: thresholds missing {exc.args[0]}"
        ) from exc


def load_registry(path: str | Path | None = None) -> Registry:
    registry_path = Path(path) if path is not None else default_registry_path()
    data = _read_toml(registry_path)
    thresholds_data = data.pop("thresholds", None)
    return Registry(
        hooks={name: _record(name, value, registry_path) for name, value in data.items()},
        thresholds=_thresholds(thresholds_data, registry_path),
    )
