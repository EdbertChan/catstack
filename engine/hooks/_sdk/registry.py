"""Load the central hook mode registry."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class HookRecord:
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


def load_registry(path: str | Path | None = None) -> dict[str, HookRecord | Thresholds]:
    """Return hook records and the shared ``thresholds`` record."""
    registry_path = Path(path) if path is not None else Path(__file__).resolve().parents[1] / "hooks.toml"
    try:
        with registry_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise OSError(f"Unable to read hook registry at {registry_path}: {exc}") from exc

    hooks = data.get("hooks")
    thresholds = data.get("thresholds")
    if not isinstance(hooks, dict) or not isinstance(thresholds, dict):
        raise ValueError(f"Invalid hook registry at {registry_path}: missing hooks or thresholds")

    result: dict[str, HookRecord | Thresholds] = {
        name: HookRecord(
            mode=record["mode"],
            why_mode=record["why_mode"],
            summary=record["summary"],
            target_mode=record.get("target_mode"),
            enabled_by=record.get("enabled_by"),
        )
        for name, record in hooks.items()
    }
    result["thresholds"] = Thresholds(**thresholds)
    return result
