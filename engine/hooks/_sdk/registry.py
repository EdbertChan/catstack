"""Load the central hook mode registry."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))

from counters import COUNTER_NAMES  # noqa: E402

HARD = "hard"
CONDITIONAL = "conditional"
SOFT = "soft"
VALID_LEVELS = (HARD, CONDITIONAL, SOFT)
LEVELS_NEEDING_CAPABILITY = (HARD, CONDITIONAL)
VALID_OVERRIDES = ("reason_required", "never")
VALID_HARNESSES = ("claude", "cursor", "codex")
WHEN_PATTERN = re.compile(r"\A(?P<counter>[a-z_]+)\s*>=\s*(?P<threshold>\d+)\Z")


@dataclass(frozen=True)
class EscalateRule:
    """One escalation: a shared counter, the threshold it must reach, and the level it then reaches."""

    counter: str
    threshold: int
    to: str
    when: str


@dataclass(frozen=True)
class EnforcementPolicy:
    """How strongly a hook's rules are enforced, and what the running harness must offer to enforce them."""

    default: str
    capability: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    override: str = "reason_required"
    escalate: EscalateRule | None = None

    def declared_levels(self) -> tuple[str, ...]:
        """Every level this policy can reach, the default and any escalation."""
        if self.escalate is None:
            return (self.default,)
        return (self.default, self.escalate.to)

    def harness_capability(self, harness: str) -> tuple[str, ...]:
        """The listed capabilities the named harness offers."""
        prefix = f"{harness}:"
        return tuple(name for name in self.capability if name.startswith(prefix))


@dataclass(frozen=True)
class HookRecord:
    mode: str
    why_mode: str
    summary: str
    target_mode: str | None = None
    enabled_by: str | None = None
    rule_modes: dict[str, str] | None = None
    worker: bool = False
    enforcement: EnforcementPolicy | None = None


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


def _string_list(name: str, key: str, value: object) -> tuple[str, ...]:
    """One list of names from an enforcement table, rejecting anything that is not a list of strings."""
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(item, str) and item.strip() for item in value):
        raise RegistryError(f"{name} enforcement {key} must be a list of names, got {value!r}")
    return tuple(item.strip() for item in value)


def _parse_escalate(name: str, raw: object) -> EscalateRule:
    """One escalate rule, checked against the shared counters and the levels it may reach."""
    if not isinstance(raw, dict):
        raise RegistryError(f"{name} enforcement escalate must be a table, got {raw!r}")
    unknown = set(raw) - {"when", "to"}
    if unknown:
        raise RegistryError(f"{name} enforcement escalate has unknown keys {sorted(unknown)}")
    when = raw.get("when")
    if not isinstance(when, str):
        raise RegistryError(f"{name} enforcement escalate needs when = \"<counter> >= N\"")
    match = WHEN_PATTERN.match(when.strip())
    if match is None:
        raise RegistryError(f"{name} enforcement escalate when must read \"<counter> >= N\", got {when!r}")
    counter = match.group("counter")
    if counter not in COUNTER_NAMES:
        raise RegistryError(
            f"{name} enforcement escalate names unknown counter {counter!r}; "
            f"the shared counters are {', '.join(COUNTER_NAMES)}"
        )
    to = raw.get("to")
    if to not in LEVELS_NEEDING_CAPABILITY:
        raise RegistryError(
            f"{name} enforcement escalate must raise to one of {', '.join(LEVELS_NEEDING_CAPABILITY)}, got {to!r}"
        )
    return EscalateRule(counter=counter, threshold=int(match.group("threshold")), to=to, when=when.strip())


def _parse_enforcement(name: str, raw: object) -> EnforcementPolicy:
    """One hook's enforcement policy, with every level it can reach backed by a capability."""
    if not isinstance(raw, dict):
        raise RegistryError(f"{name} enforcement must be a table, got {raw!r}")
    unknown = set(raw) - {"default", "escalate", "capability", "evidence", "override"}
    if unknown:
        raise RegistryError(f"{name} enforcement has unknown keys {sorted(unknown)}")
    default = raw.get("default")
    if default not in VALID_LEVELS:
        raise RegistryError(
            f"{name} enforcement default must be one of {', '.join(VALID_LEVELS)}, got {default!r}"
        )
    override = raw.get("override", "reason_required")
    if override not in VALID_OVERRIDES:
        raise RegistryError(
            f"{name} enforcement override must be one of {', '.join(VALID_OVERRIDES)}, got {override!r}"
        )
    capability = _string_list(name, "capability", raw.get("capability"))
    for entry in capability:
        harness, _, event = entry.partition(":")
        if harness not in VALID_HARNESSES or not event:
            raise RegistryError(
                f"{name} enforcement capability entries read \"<harness>:<event>\" with harness "
                f"in {', '.join(VALID_HARNESSES)}, got {entry!r}"
            )
    escalate = _parse_escalate(name, raw["escalate"]) if "escalate" in raw else None
    policy = EnforcementPolicy(
        default=default,
        capability=capability,
        evidence=_string_list(name, "evidence", raw.get("evidence")),
        override=override,
        escalate=escalate,
    )
    needs_capability = [level for level in policy.declared_levels() if level in LEVELS_NEEDING_CAPABILITY]
    if needs_capability and not capability:
        raise RegistryError(
            f"{name} enforcement declares {needs_capability[0]} with no capability list; "
            "a rule enforced that strongly must name the harness events that can check it"
        )
    return policy


def _parse_hook(name: str, record: object) -> HookRecord:
    """One hook entry, with its optional enforcement table parsed into a policy."""
    if not isinstance(record, dict):
        raise RegistryError(f"{name} entry must be a table, got {record!r}")
    fields = dict(record)
    if "enforcement" in fields:
        fields["enforcement"] = _parse_enforcement(name, fields["enforcement"])
    return HookRecord(**fields)


def load_registry(path=None) -> tuple[dict[str, HookRecord], Thresholds]:
    registry_path = Path(path) if path is not None else _default_path()
    try:
        with registry_path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise RegistryError(f"could not read hook registry {registry_path}: {exc}") from exc

    try:
        hooks = {
            name: _parse_hook(name, record)
            for name, record in data["hooks"].items()
        }
        thresholds = Thresholds(**data["thresholds"])
    except (AttributeError, KeyError, TypeError) as exc:
        raise RegistryError(f"invalid hook registry {registry_path}: {exc}") from exc
    return hooks, thresholds
