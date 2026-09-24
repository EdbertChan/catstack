"""Load the central hook mode registry."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class HookRecord:
    mode: str
    why_mode: str
    summary: str
    target_mode: str | None = None
    enabled_by: str | None = None
    rule_modes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Thresholds:
    min_closed_findings: int
    promote_max_ignore_rate: float
    demote_min_ignore_rate: float
    review_min_ignore_rate: float
    review_min_unchecked_rate: float
    followup_window_checks: int


class RegistryError(ValueError):
    """The hook registry is missing, unreadable, or invalid."""


def _default_path() -> Path:
    return Path(__file__).resolve().parents[1] / "hooks.toml"


def load_registry(path=None) -> tuple[dict[str, HookRecord], Thresholds]:
    registry_path = Path(path) if path is not None else _default_path()
    try:
        with registry_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"could not read hook registry {registry_path}: {exc}") from exc

    try:
        hooks = {
            name: HookRecord(**record)
            for name, record in data["hooks"].items()
        }
        thresholds = Thresholds(**data["thresholds"])
    except (AttributeError, KeyError, TypeError) as exc:
        raise RegistryError(f"invalid hook registry {registry_path}: {exc}") from exc
    return hooks, thresholds
