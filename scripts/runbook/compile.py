#!/usr/bin/env python3
"""Compile the rule order real sessions took into a playbook proposal, and backtest that order across a cutoff."""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

RULES_TSV = Path("engine/runbook/rules.tsv")
HOOKS_TOML = Path("engine/hooks/hooks.toml")
DEFAULT_PROPOSALS_DIRECTORY = Path("proposals")
CHECK_PLAYBOOK_SCRIPT = "check_playbook.py"
PLAYBOOK_GLOBS = ("*/skills/*/playbooks/*.md", "*/playbooks/*.md")
MINIMUM_SESSIONS = 3
MAXIMUM_STEPS = 9
MAXIMUM_TITLE_CHARACTERS = 72
MAXIMUM_DROPPED_SHOWN = 10
CHARACTERS_PER_TOKEN = 4
FALSE_FIRE_CEILING_PERCENT = 10.0
DEFAULT_WINDOW_DAYS = 90
SECONDS_PER_DAY = 86400
HARNESS = "claude"
RULE_STEP_KINDS = frozenset({"skill", "hook"})
INTERVENTION_KIND = "intervention"
LEVEL_SOFT = "soft"
LEVELS_REQUIRING_EVIDENCE = ("hard", "conditional")
PROFILE_ADVISORY = "advisory"
PROFILE_GUIDED = "guided"
PLAYBOOK_VERSION = 1
BINDING_SEPARATOR = "·"
FRONT_MATTER_RUNBOOK = re.compile(r"^runbook:[ \t]*(?P<task>\S+)[ \t]*$", re.MULTILINE)
TITLE_UNSAFE = re.compile(r"[\[\]\n\r]+")
EXIT_CLEAN = 0
EXIT_NOTHING = 1
EXIT_UNCHECKED = 2
USAGE = (
    "propose mines one task type's sessions for ordered rule pairs: A before B in "
    f"{MINIMUM_SESSIONS} or more sessions, with B never having run without A first (decision D11). The "
    "surviving rules are ordered by earliest catch point and written as a playbook under proposals/, plus a "
    "unified diff when a playbook for that task already ships, and the proposal is handed to "
    f"{CHECK_PLAYBOOK_SCRIPT}. The profile stays {PROFILE_ADVISORY} until --false-fire-percent shows a measured "
    f"rate under {FALSE_FIRE_CEILING_PERCENT:.0f} percent (decision D4). backtest builds from the sessions "
    "before a cutoff, scores on the sessions after it, and prints interventions caught earlier, order false "
    "fires and injected tokens. Exit 0 wrote a proposal, exit 1 proposed nothing and names the disqualifier, "
    "and exit 2 is unchecked: an input could not be read, which is never reported as a pass."
)


class Unchecked(Exception):
    """Raised when an input cannot be read, so the answer is unchecked rather than clean.

    The caller prints the reason and exits 2.
    """


@dataclass(frozen=True)
class Rule:
    """One rule id: every place it ships, and the summary a step title comes from.

    An id the inventory ships twice, as a hook and as a skill, keeps both
    sources rather than letting the second row overwrite the first.
    """

    rule_id: str
    sources: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class Binding:
    """One rule's level, the evidence key a step can show for it, and the harness event that sees it."""

    level: str
    evidence_key: str
    event_name: str


@dataclass(frozen=True)
class Session:
    """One mined session: its task type, its ordered steps, and the earliest timestamp it carries."""

    path: str
    session_id: str
    task_type: str
    steps: tuple[tuple[str, str], ...]
    started: float | None
    unchecked: tuple[str, ...]


@dataclass(frozen=True)
class Pair:
    """One ordered rule pair and the session counts that qualified or disqualified it."""

    earlier: str
    later: str
    before: int
    reversed_order: int
    later_without_earlier: int


@dataclass(frozen=True)
class Compiled:
    """One compilation: the rules in order, the pairs that put them there, and what was dropped."""

    task_type: str
    rules_in_order: tuple[str, ...]
    pairs: tuple[Pair, ...]
    dropped: tuple[str, ...]
    session_count: int
    candidate_count: int
    unmined: tuple[tuple[str, int], ...]
    catch_points: dict[str, float]
    rule_session_counts: dict[str, int]


SOFT_BINDING = Binding(LEVEL_SOFT, "", "")


def iso_seconds(stamp: object) -> float:
    """One ISO timestamp as epoch seconds, raising rather than letting an unreadable stamp read as absent."""
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError) as error:
        raise ValueError(f"{stamp!r} is not an ISO timestamp ({error})") from error


def read_rules(root: Path) -> dict[str, Rule]:
    """Read every rule the inventory ships, or refuse rather than compile against an empty inventory."""
    path = root / RULES_TSV
    rules: dict[str, Rule] = {}
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                rule_id = (row.get("rule_id") or "").strip()
                if rule_id:
                    rules[rule_id] = merged_rule(rules.get(rule_id), rule_id, row)
    except OSError as error:
        raise Unchecked(f"{path}: rule inventory unreadable ({error}); every mined rule id would look unknown") from error
    except UnicodeDecodeError as error:
        raise Unchecked(f"{path}: rule inventory is not UTF-8 ({error}); every mined rule id would look unknown") from error
    if not rules:
        raise Unchecked(f"{path}: rule inventory has no rule_id rows; every mined rule id would look unknown")
    return rules


def merged_rule(existing: Rule | None, rule_id: str, row: dict[str, str]) -> Rule:
    """One inventory row folded into any row the same id already had."""
    source = (row.get("source") or "").strip()
    summary = (row.get("summary") or "").strip()
    if existing is None:
        return Rule(rule_id=rule_id, sources=(source,) if source else (), summary=summary)
    sources = existing.sources if source in existing.sources else existing.sources + ((source,) if source else ())
    return Rule(rule_id=rule_id, sources=sources, summary=existing.summary or summary)


def read_bindings(root: Path) -> dict[str, Binding]:
    """Read each hook's declared level, evidence key and harness event, or refuse rather than call every step soft."""
    path = root / HOOKS_TOML
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise Unchecked(f"{path}: hook inventory unreadable ({error}); every step's level would read as {LEVEL_SOFT}") from error
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise Unchecked(f"{path}: hook inventory unparsable ({error}); every step's level would read as {LEVEL_SOFT}") from error
    return {name: binding_from_entry(entry) for name, entry in (data.get("hooks") or {}).items()}


def binding_from_entry(entry: object) -> Binding:
    """One hook's binding from its inventory entry, soft whenever no claude event and evidence key are declared."""
    enforcement = entry.get("enforcement") if isinstance(entry, dict) else None
    if not isinstance(enforcement, dict):
        return SOFT_BINDING
    capabilities = [str(value) for value in enforcement.get("capability") or []]
    evidence_keys = [str(value) for value in enforcement.get("evidence") or []]
    events = [value.split(":", 1)[1] for value in capabilities if value.startswith(HARNESS + ":")]
    level = str(enforcement.get("default") or "").strip().lower()
    if level in LEVELS_REQUIRING_EVIDENCE and events and evidence_keys:
        return Binding(level, evidence_keys[0], events[0])
    return SOFT_BINDING


def session_from_report(entry: dict[str, object], position: int) -> Session:
    """One step_order report entry as a session, carrying its own unchecked reasons."""
    raw_steps = entry.get("steps") if isinstance(entry.get("steps"), list) else []
    steps: list[tuple[str, str]] = []
    stamps: list[float] = []
    unchecked = [str(reason) for reason in entry.get("unchecked") or []]
    malformed = sum(1 for step in raw_steps if not isinstance(step, dict))
    if malformed:
        unchecked.append(f"step order partly unchecked: {malformed} step row(s) are not objects")
    for step in [row for row in raw_steps if isinstance(row, dict)]:
        steps.append((str(step.get("kind") or ""), str(step.get("id") or "")))
        if step.get("ts") is None:
            unchecked.append(f"step {step.get('id')!r} carries no timestamp, so it cannot place the session in time")
            continue
        try:
            stamps.append(iso_seconds(step.get("ts")))
        except ValueError as error:
            unchecked.append(f"step {step.get('id')!r} timestamp unchecked: {error}")
    task_type = entry.get("task_type")
    if not isinstance(task_type, str) or not task_type:
        unchecked.append("task type unchecked: the report names none for this session")
        task_type = ""
    return Session(
        path=str(entry.get("path") or f"session {position}"),
        session_id=str(entry.get("session_id") or f"session-{position}"),
        task_type=task_type,
        steps=tuple(steps),
        started=min(stamps) if stamps else None,
        unchecked=tuple(unchecked),
    )


def read_sessions_json(path: Path) -> list[Session]:
    """Read a step_order report, or refuse rather than compile from an empty session list."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise Unchecked(f"{path}: session report unreadable ({error}); no session order could be mined") from error
    except (UnicodeDecodeError, ValueError) as error:
        raise Unchecked(f"{path}: session report is not readable JSON ({error}); no session order could be mined") from error
    entries = payload.get("sessions") if isinstance(payload, dict) else payload
    if not isinstance(entries, list) or not entries:
        raise Unchecked(f"{path}: session report carries no sessions list; no session order could be mined")
    return [session_from_report(entry, position) for position, entry in enumerate(entries, start=1) if isinstance(entry, dict)]


def read_sessions_from_transcripts(paths: list[Path], metrics_directory: str | None) -> list[Session]:
    """Mine each named transcript with the reflect step-order miner, or refuse when it cannot be imported."""
    scripts = Path(__file__).resolve().parents[2] / "engine" / "skills" / "reflect" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import step_order
    except ImportError as error:
        raise Unchecked(f"{scripts}: the step-order miner could not be imported ({error}); no session order could be mined") from error
    sessions = []
    for position, path in enumerate(paths, start=1):
        sessions.append(session_from_report(step_order.step_order(str(path), metrics_directory), position))
    return sessions


def first_positions(session: Session, rule_ids: set[str]) -> dict[str, int]:
    """Where each known rule id first appears in one session's step order."""
    positions: dict[str, int] = {}
    for index, (kind, step_id) in enumerate(session.steps):
        if kind in RULE_STEP_KINDS and step_id in rule_ids and step_id not in positions:
            positions[step_id] = index
    return positions


def unmined_step_ids(sessions: list[Session], rule_ids: set[str]) -> tuple[tuple[str, int], ...]:
    """Every skill or hook step whose id the rule inventory does not ship, so a stale inventory is named."""
    counts: dict[str, int] = {}
    for session in sessions:
        for kind, step_id in session.steps:
            if kind in RULE_STEP_KINDS and step_id and step_id not in rule_ids:
                counts[step_id] = counts.get(step_id, 0) + 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def intervention_positions(session: Session) -> list[int]:
    """Where each classified human intervention sits in one session's step order."""
    return [index for index, (kind, _step_id) in enumerate(session.steps) if kind == INTERVENTION_KIND]


def candidate_pairs(positions_per_session: list[dict[str, int]]) -> list[Pair]:
    """Every ordered rule pair the sessions show, with the counts that qualify or disqualify it."""
    before: dict[tuple[str, str], int] = {}
    for positions in positions_per_session:
        for earlier, earlier_at in positions.items():
            for later, later_at in positions.items():
                if earlier != later and earlier_at < later_at:
                    before[(earlier, later)] = before.get((earlier, later), 0) + 1
    pairs = []
    for (earlier, later), count in before.items():
        reversed_order = 0
        later_without_earlier = 0
        for positions in positions_per_session:
            if later not in positions:
                continue
            if earlier not in positions:
                later_without_earlier += 1
            elif positions[later] < positions[earlier]:
                reversed_order += 1
        pairs.append(Pair(earlier, later, count, reversed_order, later_without_earlier))
    return sorted(pairs, key=lambda pair: (-pair.before, pair.earlier, pair.later))


def qualifies(pair: Pair) -> bool:
    """True when this pair's order held in enough sessions and the later rule never ran without the earlier one."""
    return pair.before >= MINIMUM_SESSIONS and pair.reversed_order == 0 and pair.later_without_earlier == 0


def disqualifier(pair: Pair) -> str:
    """Why one candidate pair is not an ordered rule pair, named rather than dropped in silence."""
    reasons = []
    if pair.before < MINIMUM_SESSIONS:
        reasons.append(f"{pair.before} session(s), fewer than {MINIMUM_SESSIONS}")
    if pair.reversed_order:
        reasons.append(f"reversed in {pair.reversed_order} session(s)")
    if pair.later_without_earlier:
        reasons.append(f"{pair.later} ran without {pair.earlier} in {pair.later_without_earlier} session(s)")
    return f"{pair.earlier} before {pair.later}: " + "; ".join(reasons)


def catch_points(positions_per_session: list[dict[str, int]]) -> tuple[dict[str, float], dict[str, int]]:
    """Each rule's mean first position across the sessions it appears in, and how many that is."""
    totals: dict[str, int] = {}
    counts: dict[str, int] = {}
    for positions in positions_per_session:
        for rule_id, index in positions.items():
            totals[rule_id] = totals.get(rule_id, 0) + index
            counts[rule_id] = counts.get(rule_id, 0) + 1
    return {rule_id: totals[rule_id] / counts[rule_id] for rule_id in totals}, counts


def order_by_catch_point(pairs: list[Pair], points: dict[str, float]) -> tuple[list[str], list[str]]:
    """The qualifying rules in dependency order, earliest catch point first, or a named cycle."""
    nodes = {pair.earlier for pair in pairs} | {pair.later for pair in pairs}
    successors: dict[str, set[str]] = {node: set() for node in nodes}
    incoming: dict[str, int] = {node: 0 for node in nodes}
    for pair in pairs:
        if pair.later not in successors[pair.earlier]:
            successors[pair.earlier].add(pair.later)
            incoming[pair.later] += 1
    available = sorted(node for node in nodes if incoming[node] == 0)
    ordered: list[str] = []
    while available:
        available.sort(key=lambda node: (points.get(node, float("inf")), node))
        node = available.pop(0)
        ordered.append(node)
        for successor in sorted(successors[node]):
            incoming[successor] -= 1
            if incoming[successor] == 0:
                available.append(successor)
    if len(ordered) != len(nodes):
        stuck = ", ".join(sorted(node for node in nodes if node not in ordered))
        return [], [f"ordering unchecked: {stuck} form a cycle, so no single order satisfies every pair"]
    return ordered, []


def compile_order(sessions: list[Session], task_type: str, rule_ids: set[str]) -> Compiled:
    """Mine one task type's sessions into the ordered rule list a playbook proposal states."""
    matching = [session for session in sessions if session.task_type == task_type]
    positions_per_session = [first_positions(session, rule_ids) for session in matching]
    candidates = candidate_pairs(positions_per_session)
    qualifying = [pair for pair in candidates if qualifies(pair)]
    points, rule_counts = catch_points(positions_per_session)
    ordered, problems = order_by_catch_point(qualifying, points)
    dropped = [disqualifier(pair) for pair in candidates if not qualifies(pair)] + problems
    if len(ordered) > MAXIMUM_STEPS:
        dropped.append(
            f"{len(ordered) - MAXIMUM_STEPS} rule(s) past the {MAXIMUM_STEPS}-step cap dropped: "
            + ", ".join(ordered[MAXIMUM_STEPS:])
        )
        ordered = ordered[:MAXIMUM_STEPS]
    return Compiled(
        task_type=task_type,
        rules_in_order=tuple(ordered),
        pairs=tuple(qualifying),
        dropped=tuple(dropped),
        session_count=len(matching),
        candidate_count=len(candidates),
        unmined=unmined_step_ids(matching, rule_ids),
        catch_points=points,
        rule_session_counts=rule_counts,
    )


def step_title(rule: Rule) -> str:
    """One step's title, taken from the rule's own inventory summary."""
    flat = " ".join(TITLE_UNSAFE.sub(" ", rule.summary).split()).rstrip(".")
    if not flat:
        flat = f"Apply {rule.rule_id}"
    if len(flat) > MAXIMUM_TITLE_CHARACTERS:
        flat = flat[: MAXIMUM_TITLE_CHARACTERS - 1].rstrip() + "…"
    return flat


def step_binding(rule_id: str, binding: Binding) -> str:
    """One step's `[rule-id · level · evidence: key · @event]` binding."""
    parts = [rule_id, binding.level]
    if binding.level in LEVELS_REQUIRING_EVIDENCE:
        parts.append(f"evidence: {binding.evidence_key}")
        parts.append(f"@{binding.event_name}")
    return f" {BINDING_SEPARATOR} ".join(parts)


def trigger_phrase(task_type: str) -> str:
    """The phrase a person types for this task type, as plain words the router can match."""
    return " ".join(task_type.replace("-", " ").split()) + " playbook"


def step_body(compiled: Compiled, rule_id: str) -> list[str]:
    """The two body lines under one step: how often it was seen, and what put it here."""
    seen = compiled.rule_session_counts.get(rule_id, 0)
    point = compiled.catch_points.get(rule_id)
    place = "no recorded place" if point is None else f"step {point:.1f} on average"
    successors = sorted({pair.later for pair in compiled.pairs if pair.earlier == rule_id})
    kept = [successor for successor in successors if successor in compiled.rules_in_order]
    capped = len(successors) - len(kept)
    if kept:
        order = f"Runs before {', '.join(kept)}, which never ran without it in these sessions."
        if capped:
            order = order[:-1] + f", and before {capped} more rule(s) dropped past the {MAXIMUM_STEPS}-step cap."
    elif capped:
        order = f"Every rule that needed it fell past the {MAXIMUM_STEPS}-step cap, so its place is its own catch point."
    else:
        order = "Nothing here needed its evidence, so its place is its own catch point."
    return [f"Seen in {seen} session(s) of {compiled.task_type}, entering at {place}.", order]


def profile_for(false_fire_percent: float | None) -> tuple[str, str]:
    """The enforcement profile this proposal may claim, and why decision D4 allows that one."""
    ceiling = f"{FALSE_FIRE_CEILING_PERCENT:.0f}"
    if false_fire_percent is None:
        return PROFILE_ADVISORY, (
            f"no measured false-fire rate was given, and decision D4 keeps a hard gate hard only under "
            f"{ceiling} percent, so this proposal stays {PROFILE_ADVISORY}"
        )
    if false_fire_percent < FALSE_FIRE_CEILING_PERCENT:
        return PROFILE_GUIDED, (
            f"the measured false-fire rate {false_fire_percent:.1f} percent is under {ceiling} percent, "
            f"so decision D4 allows {PROFILE_GUIDED}"
        )
    return PROFILE_ADVISORY, (
        f"the measured false-fire rate {false_fire_percent:.1f} percent is not under {ceiling} percent, "
        f"so decision D4 keeps this proposal {PROFILE_ADVISORY}"
    )


def render_playbook(compiled: Compiled, rules: dict[str, Rule], bindings: dict[str, Binding], profile: str) -> str:
    """The proposal in the shape check_playbook.py validates."""
    sources = sorted({
        source for rule_id in compiled.rules_in_order for source in rules[rule_id].sources if source
    })
    lines = ["---", f"runbook: {compiled.task_type}", f"version: {PLAYBOOK_VERSION}", "applies_to:"]
    lines.extend(f"  - {source}" for source in sources or [f"engine/runbook/{RULES_TSV.name}"])
    lines.append("compiled_from:")
    lines.extend(f"  - {rule_id}" for rule_id in compiled.rules_in_order)
    lines.append(f"playbook-trigger: {trigger_phrase(compiled.task_type)}")
    lines.append(f"enforcement_profile: {profile}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {compiled.task_type}, compiled from {compiled.session_count} session(s)")
    lines.append("")
    lines.append(
        f"Each step below is one rule that {MINIMUM_SESSIONS} or more sessions ran in this order, "
        "earliest catch point first."
    )
    for number, rule_id in enumerate(compiled.rules_in_order, start=1):
        binding = bindings.get(rule_id, SOFT_BINDING)
        lines.append("")
        lines.append(f"## {number}. {step_title(rules[rule_id])} [{step_binding(rule_id, binding)}]")
        lines.append("")
        lines.extend(step_body(compiled, rule_id))
    return "\n".join(lines) + "\n"


def installed_playbook(root: Path, task_type: str) -> Path | None:
    """The playbook already installed for this task type, when one ships."""
    for pattern in PLAYBOOK_GLOBS:
        for path in sorted(root.glob(pattern)):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as error:
                raise Unchecked(f"{path}: installed playbook unreadable ({error}); a diff against it would look like a new file") from error
            found = FRONT_MATTER_RUNBOOK.search(text)
            if found and found.group("task") == task_type:
                return path
    return None


def unified_diff(current: Path, proposed_text: str, label: str) -> str:
    """The unified diff from the installed playbook to this proposal."""
    current_text = current.read_text(encoding="utf-8")
    return "".join(difflib.unified_diff(
        current_text.splitlines(keepends=True),
        proposed_text.splitlines(keepends=True),
        fromfile=str(current),
        tofile=label,
    ))


def estimated_tokens(text: str) -> int:
    """The injected size of one proposal, estimated at a fixed characters-per-token rate."""
    return math.ceil(len(text) / CHARACTERS_PER_TOKEN)


def run_check_playbook(root: Path, path: Path) -> subprocess.CompletedProcess[str]:
    """Hand the written proposal to the playbook validator."""
    script = Path(__file__).resolve().with_name(CHECK_PLAYBOOK_SCRIPT)
    return subprocess.run(
        [sys.executable, str(script), str(path), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def report_mined(compiled: Compiled, limit: int) -> None:
    """Say how much order was mined, and name every step id the inventory does not ship."""
    print(
        f"mined {compiled.candidate_count} candidate pair(s) from {compiled.session_count} session(s) "
        f"of {compiled.task_type}"
    )
    if not compiled.unmined:
        print(f"every mined step id is in {RULES_TSV}")
        return
    shown = list(compiled.unmined) if limit <= 0 else list(compiled.unmined)[:limit]
    print(f"{len(compiled.unmined)} step id(s) are not in {RULES_TSV} and were not mined, showing {len(shown)}:")
    for step_id, count in shown:
        print(f"  {step_id}: {count} firing(s)")


def report_dropped(dropped: tuple[str, ...], limit: int) -> None:
    """Name the candidate pairs that did not qualify, and say how many were not printed."""
    if not dropped:
        print("dropped nothing: every candidate pair qualified")
        return
    shown = list(dropped) if limit <= 0 else list(dropped)[:limit]
    print(f"dropped {len(dropped)} candidate pair(s), showing {len(shown)}:")
    for reason in shown:
        print(f"  {reason}")
    if len(shown) < len(dropped):
        print(f"  {len(dropped) - len(shown)} more not shown; raise --show-dropped to see them")


def report_unchecked_sessions(sessions: list[Session]) -> None:
    """Say which mined sessions carried unchecked reasons, so a partial mine never reads as a full one."""
    partial = [session for session in sessions if session.unchecked]
    if not partial:
        print(f"every one of the {len(sessions)} mined session(s) was fully checked")
        return
    grouped: dict[str, int] = {}
    for session in partial:
        for reason in session.unchecked:
            grouped[reason] = grouped.get(reason, 0) + 1
    print(
        f"{len(partial)} of {len(sessions)} session(s) carried unchecked reasons, so this mine is partial:",
        file=sys.stderr,
    )
    for reason, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count} session(s): {reason}", file=sys.stderr)


def load_sessions(arguments: argparse.Namespace) -> list[Session]:
    """The sessions this run mines, from a step-order report, named transcripts, or both."""
    sessions: list[Session] = []
    if arguments.sessions_json:
        sessions.extend(read_sessions_json(arguments.sessions_json))
    if arguments.paths:
        sessions.extend(read_sessions_from_transcripts(arguments.paths, arguments.metrics_dir))
    if not sessions:
        raise Unchecked("no sessions were given; pass --sessions-json, transcript paths, or both")
    return sessions


def propose(arguments: argparse.Namespace) -> int:
    """Write one task type's proposal under proposals/, diff it against any installed playbook, and validate it."""
    root = arguments.root.resolve()
    rules = read_rules(root)
    bindings = read_bindings(root)
    sessions = load_sessions(arguments)
    report_unchecked_sessions(sessions)
    compiled = compile_order(sessions, arguments.task, set(rules))
    report_mined(compiled, arguments.show_dropped)
    report_dropped(compiled.dropped, arguments.show_dropped)
    if not compiled.rules_in_order:
        print(
            f"proposed nothing for {arguments.task}: no ordered rule pair reached {MINIMUM_SESSIONS} session(s) "
            f"across the {compiled.session_count} session(s) of that task type",
            file=sys.stderr,
        )
        return EXIT_NOTHING
    profile, profile_reason = profile_for(arguments.false_fire_percent)
    print(f"enforcement_profile {profile}: {profile_reason}")
    text = render_playbook(compiled, rules, bindings, profile)
    directory = arguments.out_dir if arguments.out_dir.is_absolute() else root / arguments.out_dir
    directory.mkdir(parents=True, exist_ok=True)
    proposal = directory / f"{arguments.task}.md"
    proposal.write_text(text, encoding="utf-8")
    print(f"wrote {proposal}: {len(compiled.rules_in_order)} step(s) from {compiled.session_count} session(s)")
    current = installed_playbook(root, arguments.task)
    if current is not None:
        diff_path = directory / f"{arguments.task}.diff"
        diff_path.write_text(unified_diff(current, text, str(proposal)), encoding="utf-8")
        print(f"wrote {diff_path}: unified diff against the installed {current}")
    else:
        print(f"no installed playbook declares runbook: {arguments.task}, so the proposal is a new playbook")
    print(f"estimated injected tokens per session: {estimated_tokens(text)}")
    checked = run_check_playbook(root, proposal)
    sys.stdout.write(checked.stdout)
    sys.stderr.write(checked.stderr)
    if checked.returncode != EXIT_CLEAN:
        print(f"{CHECK_PLAYBOOK_SCRIPT} exited {checked.returncode} on {proposal}", file=sys.stderr)
        return EXIT_NOTHING if checked.returncode == EXIT_NOTHING else EXIT_UNCHECKED
    return EXIT_CLEAN


def window_start(now_seconds: float, window_days: int) -> float:
    """The epoch second the scored window opens on."""
    return now_seconds - window_days * SECONDS_PER_DAY


def split_cutoff(starts: list[float], declared: float | None) -> float:
    """The cutoff the backtest splits on: the one declared, else the median session start."""
    if declared is not None:
        return declared
    ordered = sorted(starts)
    return ordered[len(ordered) // 2]


def caught_earlier(sessions: list[Session], rules_in_order: tuple[str, ...], rule_ids: set[str]) -> tuple[int, int]:
    """How many interventions in the scored sessions had a compiled rule still ahead of them, and how many there were."""
    compiled_rules = set(rules_in_order)
    total = 0
    caught = 0
    for session in sessions:
        positions = first_positions(session, rule_ids)
        later_than = [positions[rule_id] for rule_id in compiled_rules if rule_id in positions]
        for index in intervention_positions(session):
            total += 1
            if any(position > index for position in later_than):
                caught += 1
    return caught, total


def order_false_fires(sessions: list[Session], pairs: tuple[Pair, ...], rule_ids: set[str]) -> int:
    """How many times a compiled pair's order did not hold in the scored sessions."""
    count = 0
    for session in sessions:
        positions = first_positions(session, rule_ids)
        for pair in pairs:
            if pair.later not in positions:
                continue
            if pair.earlier not in positions or positions[pair.later] < positions[pair.earlier]:
                count += 1
    return count


def backtest(arguments: argparse.Namespace) -> int:
    """Build a proposal from the sessions before a cutoff and score it on the sessions after it."""
    root = arguments.root.resolve()
    rules = read_rules(root)
    bindings = read_bindings(root)
    sessions = load_sessions(arguments)
    report_unchecked_sessions(sessions)
    rule_ids = set(rules)
    try:
        now_seconds = iso_seconds(arguments.now) if arguments.now else datetime.now(timezone.utc).timestamp()
    except ValueError as error:
        raise Unchecked(f"--now unusable ({error}); the window could not be placed") from error
    opens = window_start(now_seconds, arguments.window_days)
    matching = [session for session in sessions if session.task_type == arguments.task]
    undated = [session for session in matching if session.started is None]
    in_window = [session for session in matching if session.started is not None and session.started >= opens]
    if not in_window:
        print(
            f"backtested nothing for {arguments.task}: {len(matching)} of {len(sessions)} mined session(s) carry "
            f"that task type, {len(undated)} of those carry no timestamp, and none of the rest falls in the last "
            f"{arguments.window_days} day(s)",
            file=sys.stderr,
        )
        return EXIT_NOTHING
    try:
        declared = iso_seconds(arguments.cutoff) if arguments.cutoff else None
    except ValueError as error:
        raise Unchecked(f"--cutoff unusable ({error}); the split could not be placed") from error
    cutoff = split_cutoff([session.started for session in in_window], declared)
    built_from = [session for session in in_window if session.started < cutoff]
    scored_on = [session for session in in_window if session.started >= cutoff]
    compiled = compile_order(built_from, arguments.task, rule_ids)
    report_mined(compiled, arguments.show_dropped)
    report_dropped(compiled.dropped, arguments.show_dropped)
    if not built_from or not scored_on or not compiled.rules_in_order:
        print(
            f"backtested nothing for {arguments.task}: {len(built_from)} session(s) before the cutoff, "
            f"{len(scored_on)} after it, {len(compiled.rules_in_order)} compiled step(s)",
            file=sys.stderr,
        )
        return EXIT_NOTHING
    text = render_playbook(compiled, rules, bindings, PROFILE_ADVISORY)
    per_session = estimated_tokens(text)
    caught, interventions = caught_earlier(scored_on, compiled.rules_in_order, rule_ids)
    print(render_backtest_table({
        "task_type": arguments.task,
        "window_days": arguments.window_days,
        "window_opens": stamp(opens),
        "cutoff": stamp(cutoff),
        "cutoff_source": "declared" if declared is not None else "median session start",
        "built_from": len(built_from),
        "scored_on": len(scored_on),
        "steps": len(compiled.rules_in_order),
        "interventions": interventions,
        "caught_earlier": caught,
        "order_false_fires": order_false_fires(scored_on, compiled.pairs, rule_ids),
        "tokens_per_session": per_session,
        "tokens_over_scored": per_session * len(scored_on),
        "undated": len(undated),
        "outside_window": len(matching) - len(in_window) - len(undated),
    }))
    return EXIT_CLEAN


def stamp(seconds: float) -> str:
    """One epoch second as a UTC ISO timestamp."""
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat()


def render_backtest_table(result: dict[str, object]) -> str:
    """The backtest table, in the markdown shape a pull request body carries."""
    rows = [
        ("task type", result["task_type"]),
        ("window", f"{result['window_days']} day(s) from {result['window_opens']}"),
        ("cutoff", f"{result['cutoff']} ({result['cutoff_source']})"),
        ("sessions built from (before cutoff)", result["built_from"]),
        ("sessions scored on (after cutoff)", result["scored_on"]),
        ("compiled steps", result["steps"]),
        ("interventions in scored sessions", result["interventions"]),
        ("interventions caught earlier", result["caught_earlier"]),
        ("order false fires", result["order_false_fires"]),
        ("injected tokens per session (estimated)", result["tokens_per_session"]),
        ("injected tokens over scored sessions", result["tokens_over_scored"]),
        ("sessions with no timestamp (unchecked)", result["undated"]),
        ("sessions outside the window", result["outside_window"]),
    ]
    lines = ["| measure | value |", "| --- | --- |"]
    lines.extend(f"| {name} | {value} |" for name, value in rows)
    return "\n".join(lines)


def add_shared_arguments(parser: argparse.ArgumentParser) -> None:
    """The inputs both subcommands read sessions and the rule inventory from."""
    parser.add_argument("paths", nargs="*", type=Path, help="Claude session transcripts to mine with step_order")
    parser.add_argument("--task", required=True, help="the task type to compile, as step_order tags it")
    parser.add_argument("--sessions-json", type=Path, default=None, help="a step_order.py report to read instead of transcripts")
    parser.add_argument("--metrics-dir", default=None, help="hook metrics directory passed to step_order")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--show-dropped", type=int, default=MAXIMUM_DROPPED_SHOWN, help="how many dropped pairs to print; 0 prints every one")


def build_parser() -> argparse.ArgumentParser:
    """The two subcommands: write a proposal, or backtest one across a cutoff."""
    parser = argparse.ArgumentParser(description=__doc__, epilog=USAGE)
    subparsers = parser.add_subparsers(dest="command", required=True)
    proposer = subparsers.add_parser("propose", help="write the proposal and validate it")
    add_shared_arguments(proposer)
    proposer.add_argument("--out-dir", type=Path, default=DEFAULT_PROPOSALS_DIRECTORY)
    proposer.add_argument(
        "--false-fire-percent",
        type=float,
        default=None,
        help=f"the measured gate false-fire rate; under {FALSE_FIRE_CEILING_PERCENT:.0f} percent allows {PROFILE_GUIDED}",
    )
    proposer.set_defaults(handler=propose)
    backtester = subparsers.add_parser("backtest", help="build before a cutoff and score after it")
    add_shared_arguments(backtester)
    backtester.add_argument("--cutoff", default=None, help="ISO timestamp to split on; default is the median session start")
    backtester.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    backtester.add_argument("--now", default=None, help="ISO timestamp the window ends on; default is now")
    backtester.set_defaults(handler=backtest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    try:
        return arguments.handler(arguments)
    except Unchecked as unchecked:
        print(f"unchecked: {unchecked}", file=sys.stderr)
        return EXIT_UNCHECKED


if __name__ == "__main__":
    raise SystemExit(main())
