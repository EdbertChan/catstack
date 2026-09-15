from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None


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
_HEADER = re.compile(r"^\[([A-Za-z0-9_-]+)\]$")
_ASSIGNMENT = re.compile(r"^([A-Za-z0-9_]+)\s*=\s*(.+)$")


def load_registry(path: str | Path | None = None) -> HookRegistry:
    registry_path = Path(path) if path is not None else DEFAULT_PATH
    try:
        raw = _load_toml(registry_path)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
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


def _load_toml(path: Path) -> dict[str, Any]:
    if tomllib is not None:
        with path.open("rb") as handle:
            return tomllib.load(handle)

    data: dict[str, Any] = {}
    current: dict[str, Any] | None = None
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        header = _HEADER.fullmatch(stripped)
        if header:
            section = header.group(1)
            if section in data:
                raise ValueError(f"duplicate table {section!r} at line {line_number}")
            current = {}
            data[section] = current
            continue
        assignment = _ASSIGNMENT.fullmatch(stripped)
        if assignment and current is not None:
            key = assignment.group(1)
            if key in current:
                raise ValueError(f"duplicate key {key!r} at line {line_number}")
            current[key] = _parse_toml_scalar(assignment.group(2), line_number)
            continue
        raise ValueError(f"invalid TOML line {line_number}: {line}")
    return data


def _parse_toml_scalar(value: str, line_number: int) -> str | int | float:
    if value.startswith('"') and value.endswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError(f"invalid string at line {line_number}")
        return parsed
    if re.fullmatch(r"[+-]?\d+", value):
        return int(value)
    if re.fullmatch(r"[+-]?(?:\d+\.\d*|\d*\.\d+)", value):
        return float(value)
    raise ValueError(f"unsupported value at line {line_number}: {value}")


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
