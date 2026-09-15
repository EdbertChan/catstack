"""Load the central hook mode registry."""

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


def _default_path() -> Path:
    return Path(__file__).resolve().parents[1] / "hooks.toml"


def load_registry(path=None) -> dict[str, HookRecord | Thresholds]:
    registry_path = Path(path) if path is not None else _default_path()
    try:
        with registry_path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Unable to read hook registry at {registry_path}: {exc}") from exc

    hooks = raw.get("hooks")
    thresholds = raw.get("thresholds")
    if not isinstance(hooks, dict) or not isinstance(thresholds, dict):
        raise ValueError(f"Invalid hook registry at {registry_path}: missing hooks or thresholds")

    result: dict[str, HookRecord | Thresholds] = {
        name: HookRecord(**values) for name, values in hooks.items()
    }
    result["thresholds"] = Thresholds(**thresholds)
    return result
