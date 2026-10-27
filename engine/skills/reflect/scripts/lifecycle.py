#!/usr/bin/env python3
"""Revisit old rules: own every mined cluster, judge overlap, and propose at most one change per lifecycle class."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS_DIRECTORY = Path(__file__).resolve().parent
DEFAULT_REPOSITORY_ROOT = SCRIPTS_DIRECTORY.parents[3]
PHRASES_DIRECTORY = SCRIPTS_DIRECTORY / "phrases"
OVERLAP_CHECKER = "lifecycle-overlap"
DEFAULT_WINDOW_DAYS = 60
DEFAULT_STATE_DIRECTORY = "~/.cache/catstack-session-mine"
DEFAULT_METRICS_DIRECTORY = "~/.cache/catstack-hook-metrics"
DEFAULT_TRANSCRIPTS_DIRECTORY = "~/.claude/projects"
DEFAULT_REPORT_PATH = "lifecycle/report.tsv"
DEFAULT_STRUCTURAL_WINS_PATH = "engine/runbook/structural-wins.txt"
DEFAULT_MAXIMUM_JUDGE_PAIRS = 120
DEFAULT_MAXIMUM_SESSIONS = 25
DEFAULT_REWORK_MINIMUM_RUNS = 10
DEFAULT_REWORK_OVERRIDE_RATE = 0.5
DEFAULT_REWORK_MINIMUM_SKIPS = 1
QUEUE_FILE_NAME = "queue.json"
RUNS_FILE_NAME = "runs.jsonl"
HARNESSES = ("claude", "cursor", "codex")
SKILL_USAGE_HOOK = "skill-usage-log"
SKILL_USED_ACTION = "skill_used"
SKILL_UNCHECKED_ACTION = "skill_usage_unchecked"
SPEAKING_ACTIONS = frozenset({"stopped", "warned"})
SPEAKING_OUTCOMES = frozenset({"spoke", "blocked"})
OVERRIDDEN_ACTED = "overridden"
SKILL_KIND = "skill"
HOOK_KIND = "hook"
INTERVENTION_KIND = "intervention"
STRENGTHEN = "strengthen"
WEAKEN = "weaken"
MOVE_EARLIER = "move-earlier"
SIMPLIFY = "simplify"
COMBINE = "combine"
REWORK = "rework"
RETIRE = "retire"
COVERAGE_GAP = "coverage-gap"
PROPOSAL_CLASSES = (STRENGTHEN, WEAKEN, MOVE_EARLIER, SIMPLIFY, COMBINE, REWORK, RETIRE, COVERAGE_GAP)
SUGGESTION_CLASSES = {
    "warn to stop": STRENGTHEN,
    "stop to warn": WEAKEN,
    "review or turn off": SIMPLIFY,
}
STRUCTURAL_WIN_CLASS = "structural-win"
CAPPED_CLASS = "overlap-capped"
NOTE_CLASS = "note"
UNCHECKED_CLASS = "unchecked"
OUTCOME_CLEAN = "clean"
OUTCOME_CHANGED = "changed"
OUTCOME_BLOCKED = "blocked"
EXIT_CLEAN = 0
EXIT_CHANGED = 1
EXIT_BLOCKED = 2
AUTOMATIC_TITLE_PREFIX = "[auto]"
PROPOSALS_DIRECTORY_NAME = "proposals"
REPORT_COLUMNS = ("class", "subject", "measure", "base_count", "head_count", "evidence", "proposal")
SECONDS_PER_DAY = 86400
CITATION_PATTERNS = ("skills?/{name}/SKILL\\.md", "`{name}`")
READABLE_SUFFIXES = (".py", ".md", ".json", ".txt", ".toml")
FRONTMATTER_DESCRIPTION = re.compile(r"^description:\s*(.*)$")
CLUSTER_OWNER_SKILLS = {
    "make_pr": "draft-pr",
    "commit_push": "draft-pr",
    "reflect": "reflect",
    "automate_me": "automate-me",
    "eli5": "diu",
    "try_again": "narrow-the-scope",
    "just_do_it": "cat-mode",
}
USAGE = (
    "One pass over the window's own records: the mine queue's clusters, the skill-use rows every harness wrote, "
    "the hook rows per rule with their outcome and effective level, and the step-log rows per playbook step. "
    "Every mined cluster is given an owner skill from the cluster-owner table; a cluster the table does not name "
    "is a coverage gap. Skills and hooks are then checked pairwise for overlap through the llm-judge channel, "
    "which answers whether two stated rules say the same thing or one already covers the other. "
    "A retire needs all three: no skill-use row on any harness inside the window, no owned cluster, and every "
    "hook that cites the skill silent; a skill named in the structural-wins file is recorded as a structural win "
    "instead. A rework needs a step skipped with a reason, or a gate overridden in more than half of at least the "
    "minimum number of runs. A move-earlier needs an intervention landing after a step whose evidence an earlier "
    "step of the same playbook already recorded. Strengthen, weaken and simplify come from the hook runner's own "
    "per-rule suggestions, read at the thresholds given here. A combine comes from a judge hit. "
    "Each class becomes at most one proposal under the report's proposals folder, titled with the automatic "
    "prefix and carrying its base and head counts; --open-prs hands those bodies to a pull request, skipping a "
    "class that already has one open. Nothing is merged and no live skill, hook or playbook is edited. "
    "The pass ends in exactly one outcome, printed with its reason: clean when nothing was found, changed when a "
    "proposal was written, blocked when a source could not be read at all, a judged pair came back unchecked, or "
    "a write failed. A blocked pass proposes nothing. Exit 0 is clean, exit 1 is changed and exit 2 is blocked. "
    "A partial read inside one session, and a pair left unjudged by the pair cap, are reported as their own rows "
    "with their counts printed, and never counted as clean."
)


class Unchecked(Exception):
    """Raised when a source cannot be read at all, so no part of the pass is reported clean.

    The caller prints the reason, writes what it has, and ends blocked.
    """


@dataclass(frozen=True)
class Item:
    """One thing the pass can propose a change to: a registered skill or a registered hook."""

    kind: str
    name: str
    purpose: str


@dataclass(frozen=True)
class Row:
    """One line of the report: a finding, a note, a capped pair, or an unchecked source."""

    finding_class: str
    subject: str
    measure: str
    base_count: int
    head_count: int
    evidence: str


@dataclass
class Pass:
    """Everything one pass produced: its rows, the proposals it wrote, and why it ended the way it did."""

    rows: list[Row] = field(default_factory=list)
    proposals: dict[str, Path] = field(default_factory=dict)
    opened: dict[str, str] = field(default_factory=dict)
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    outcome: str = OUTCOME_CLEAN
    reason: str = ""

    def attempt(self, read, *arguments):
        """One signal that only some rules need: its value, or None with the reason recorded as a blocker."""
        try:
            return read(*arguments)
        except Unchecked as error:
            self.blockers.append(one_line(error))
            return None


def one_line(text: object) -> str:
    """One tab-free, newline-free line, so a report cell never breaks its own column."""
    return " ".join(str(text).split())


def load_hook_report(repository_root: Path):
    """Import the hook runner's report module and the hook registry, or refuse rather than count no rule."""
    directories = (
        repository_root / "engine" / "hooks" / "_runner",
        repository_root / "engine" / "hooks" / "_sdk",
        repository_root / "engine" / "hooks" / "skill-usage-log",
    )
    for directory in directories:
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    try:
        import registry
        import report
    except Exception as error:
        raise Unchecked(
            f"{directories[0]}: the hook report module could not be imported "
            f"({type(error).__name__}: {error}); no rule could be measured"
        ) from error
    return report, registry


def load_step_order():
    """Import the per-session step reader, or refuse rather than count no intervention."""
    if str(SCRIPTS_DIRECTORY) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIRECTORY))
    try:
        import step_order
    except Exception as error:
        raise Unchecked(
            f"{SCRIPTS_DIRECTORY}: the step reader could not be imported "
            f"({type(error).__name__}: {error}); no intervention could be placed"
        ) from error
    return step_order


def load_judge(repository_root: Path):
    """Import the shared model judge and its phrase loader, or refuse rather than call a pair distinct."""
    directory = repository_root / "engine" / "hooks" / "llm-judge"
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    try:
        import judge
        import phrases
    except Exception as error:
        raise Unchecked(
            f"{directory}: the model judge could not be imported "
            f"({type(error).__name__}: {error}); no pair could be judged for overlap"
        ) from error
    return judge, phrases


def read_json_file(path: Path, what: str) -> object:
    """One JSON file, or an Unchecked naming what could not be read."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise Unchecked(f"{path}: {what} unreadable ({type(error).__name__}: {error})") from error
    try:
        return json.loads(text)
    except ValueError as error:
        raise Unchecked(f"{path}: {what} is not valid JSON ({error})") from error


def owner_skill(cluster_key: object) -> str:
    """The skill whose job it is to stop one mined cluster, or empty when the table names none."""
    if not isinstance(cluster_key, str):
        return ""
    return CLUSTER_OWNER_SKILLS.get(cluster_key, "")


def assign_owner_skills(clusters: list[dict[str, object]]) -> list[dict[str, object]]:
    """Every mined cluster with its owner skill attached, empty when the table names none."""
    owned = []
    for cluster in clusters:
        if not isinstance(cluster, dict):
            continue
        attached = dict(cluster)
        attached["owner_skill"] = owner_skill(cluster.get("cluster_key"))
        owned.append(attached)
    return owned


def read_mine_clusters(state_directory: Path) -> list[dict[str, object]]:
    """The mine queue's clusters with owners attached, or an Unchecked when the queue cannot be read."""
    path = state_directory / QUEUE_FILE_NAME
    queue = read_json_file(path, "the mine queue")
    if not isinstance(queue, dict):
        raise Unchecked(f"{path}: the mine queue is a JSON {type(queue).__name__}, not an object")
    clusters = queue.get("clusters")
    if not isinstance(clusters, list):
        raise Unchecked(f"{path}: the mine queue carries no cluster list, so no cluster could be owned")
    return assign_owner_skills([cluster for cluster in clusters if isinstance(cluster, dict)])


def read_skill_items(repository_root: Path) -> tuple[list[Item], list[str]]:
    """Every registered skill with the purpose its own file states, plus every purpose that could not be read."""
    path = repository_root / "skills.toml"
    try:
        inventory = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise Unchecked(
            f"{path}: the skill inventory could not be read ({type(error).__name__}: {error}); "
            "no skill could be measured"
        ) from error
    skills = inventory.get("skills")
    if not isinstance(skills, dict) or not skills:
        raise Unchecked(f"{path}: the skill inventory names no skill, so no skill could be measured")
    items = []
    notes: list[str] = []
    for name in sorted(skills):
        record = skills[name] if isinstance(skills[name], dict) else {}
        bucket = str(record.get("bucket") or "engine")
        purpose, note = skill_purpose(repository_root, bucket, name)
        if note:
            notes.append(note)
        items.append(Item(SKILL_KIND, name, purpose))
    return items, notes


def skill_purpose(repository_root: Path, bucket: str, name: str) -> tuple[str, str]:
    """One skill's stated purpose from its own description, and the reason that purpose stayed empty."""
    path = repository_root / bucket / "skills" / name / "SKILL.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        return "", f"{path}: unreadable ({type(error).__name__}: {error}); {name} was judged for overlap by its name alone"
    purpose = described_purpose(lines)
    if not purpose:
        return "", f"{path}: states no description; {name} was judged for overlap by its name alone"
    return purpose[:400], ""


def described_purpose(lines: list[str]) -> str:
    """The description a front matter states, read on its own line or from the indented block under it."""
    for index, line in enumerate(lines):
        found = FRONTMATTER_DESCRIPTION.match(line)
        if found is None:
            continue
        head = found.group(1).strip().strip("'\"")
        if head.strip(">|-+ "):
            return one_line(head)
        block = []
        for follower in lines[index + 1 :]:
            if not follower.strip():
                continue
            if not follower.startswith((" ", "\t")):
                break
            block.append(follower.strip())
        return one_line(" ".join(block))
    return ""


def read_hook_items(registry_module, registry_path: Path) -> tuple[list[Item], dict[str, object], object]:
    """Every registered hook with the purpose the registry states, plus the registry's own records."""
    try:
        hooks, thresholds = registry_module.load_registry(str(registry_path))
    except registry_module.RegistryError as error:
        raise Unchecked(f"{registry_path}: the hook registry could not be read ({error}); no hook could be measured") from error
    items = [Item(HOOK_KIND, name, one_line(record.summary)) for name, record in sorted(hooks.items())]
    return items, hooks, thresholds


def skill_use_counts(event_rows: list[dict[str, object]]) -> tuple[dict[str, dict[str, int]], int]:
    """How many skill-use rows each skill has per harness in the window, and how many runs could not read their input."""
    counts: dict[str, dict[str, int]] = {}
    unreadable = 0
    for row in event_rows:
        if row.get("hook") != SKILL_USAGE_HOOK:
            continue
        if row.get("action") == SKILL_UNCHECKED_ACTION:
            unreadable += 1
            continue
        if row.get("action") != SKILL_USED_ACTION:
            continue
        skill = row.get("skill")
        if not isinstance(skill, str) or not skill:
            continue
        harness = str(row.get("harness") or "")
        per_harness = counts.setdefault(skill, {known: 0 for known in HARNESSES})
        if harness in per_harness:
            per_harness[harness] += 1
    return counts, unreadable


def skill_use_basis(event_rows: list[dict[str, object]], counts: dict[str, dict[str, int]]) -> str:
    """What the skill-use signal rests on, so a reader can weigh a retire instead of trusting a bare zero."""
    rows = [row for row in event_rows if row.get("hook") == SKILL_USAGE_HOOK and row.get("action") == SKILL_USED_ACTION]
    harnesses = sorted({str(row.get("harness") or "") for row in rows if row.get("harness")})
    machines = sorted({str(row.get("machine") or "") for row in rows if row.get("machine")})
    return (
        f"the skill-use signal rests on {len(rows)} row(s) naming {len(counts)} skill(s), "
        f"from harness(es) {', '.join(harnesses) or 'none'} on {len(machines)} machine(s); "
        "a skill used only where no row was collected reads as unused here"
    )


def speaking_hooks(event_rows: list[dict[str, object]], run_rows: list[dict[str, object]]) -> set[str]:
    """Every hook that stopped, warned or blocked at least once inside the window."""
    spoke = set()
    for row in event_rows:
        if row.get("action") in SPEAKING_ACTIONS and isinstance(row.get("hook"), str):
            spoke.add(str(row["hook"]))
    for row in run_rows:
        if row.get("outcome") in SPEAKING_OUTCOMES and isinstance(row.get("hook"), str):
            spoke.add(str(row["hook"]))
    return spoke


def hook_citations(repository_root: Path, skill_names: list[str]) -> tuple[dict[str, set[str]], list[str]]:
    """Which hooks name each skill in their own files, and which hook directories could not be read."""
    hooks_root = repository_root / "engine" / "hooks"
    patterns = {
        name: re.compile("|".join(piece.format(name=re.escape(name)) for piece in CITATION_PATTERNS))
        for name in skill_names
    }
    citations: dict[str, set[str]] = {name: set() for name in skill_names}
    notes: list[str] = []
    try:
        directories = sorted(entry for entry in hooks_root.iterdir() if entry.is_dir())
    except OSError as error:
        raise Unchecked(
            f"{hooks_root}: the hook directories could not be listed ({type(error).__name__}: {error}); "
            "a citing hook could not be told from a silent one"
        ) from error
    for directory in directories:
        text_parts = []
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix not in READABLE_SUFFIXES:
                continue
            try:
                text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError as error:
                notes.append(f"{path}: unreadable ({type(error).__name__}: {error}); its citations were not read")
        text = "\n".join(text_parts)
        for name, pattern in patterns.items():
            if pattern.search(text):
                citations[name].add(directory.name)
    return citations, notes


def read_structural_wins(path: Path) -> set[str]:
    """The skills whose mistake is now structurally impossible, or an Unchecked when the list cannot be read."""
    if not path.exists():
        return set()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise Unchecked(
            f"{path}: the structural-wins list could not be read ({type(error).__name__}: {error}); "
            "a retired skill could not be told from a solved one"
        ) from error
    names = set()
    for line in lines:
        entry = line.split("#", 1)[0].strip()
        if entry:
            names.add(entry)
    return names


def retire_rows(
    skill_items: list[Item],
    counts: dict[str, dict[str, int]],
    clusters: list[dict[str, object]],
    citations: dict[str, set[str]],
    spoke: set[str],
    structural: set[str],
    window_days: int,
) -> list[Row]:
    """A retire row per unused, unowned, uncited skill, or a structural-win row when the list names it."""
    owned = {str(cluster.get("owner_skill") or "") for cluster in clusters}
    unused: list[tuple[Item, str]] = []
    for item in skill_items:
        used = sum((counts.get(item.name) or {}).values())
        if used:
            continue
        if item.name in owned:
            continue
        loud = sorted(citations.get(item.name, set()) & spoke)
        if loud:
            continue
        citing = sorted(citations.get(item.name, set()))
        unused.append(
            (
                item,
                one_line(
                    f"no skill-use row on {', '.join(HARNESSES)} in {window_days} day(s); no owned cluster; "
                    f"{len(citing)} citing hook(s) silent: {', '.join(citing) or 'none'}"
                ),
            )
        )
    solved = [entry for entry in unused if entry[0].name in structural]
    retiring = [entry for entry in unused if entry[0].name not in structural]
    base = len(skill_items)
    rows = [Row(STRUCTURAL_WIN_CLASS, item.name, "structural wins", 0, len(solved), evidence) for item, evidence in solved]
    rows.extend(
        Row(RETIRE, item.name, "registered skills", base, base - len(retiring), evidence)
        for item, evidence in retiring
    )
    return rows


def coverage_gap_rows(clusters: list[dict[str, object]]) -> list[Row]:
    """A coverage-gap row per mined cluster the owner table does not name."""
    owned = sum(1 for cluster in clusters if cluster.get("owner_skill"))
    gaps = [cluster for cluster in clusters if not cluster.get("owner_skill")]
    rows = []
    for cluster in gaps:
        evidence = (
            f"cluster {cluster.get('cluster_key')} hash={cluster.get('hash')} "
            f"sessions={cluster.get('session_count')} utterances={cluster.get('utterance_count')} has no owner skill"
        )
        rows.append(Row(COVERAGE_GAP, str(cluster.get("cluster_key") or cluster.get("hash") or "unnamed"),
                        "owned clusters", owned, owned + len(gaps), one_line(evidence)))
    return rows


def step_log_rows(run_rows: list[dict[str, object]]) -> list[dict[str, str]]:
    """Every run row that measured a playbook step, as its own step-log fields."""
    logs = []
    for row in run_rows:
        runbook = str(row.get("runbook") or "")
        step = str(row.get("step") or "")
        if not runbook or not step:
            continue
        logs.append(
            {
                "runbook": runbook,
                "step": step,
                "acted": str(row.get("acted") or ""),
                "override_reason": str(row.get("override_reason") or ""),
                "evidence_ref": str(row.get("evidence_ref") or ""),
                "session_id": str(row.get("session_id") or ""),
                "timestamp": str(row.get("ts") or ""),
                "hook": str(row.get("hook") or ""),
            }
        )
    return logs


def rework_rows(logs: list[dict[str, str]], minimum_runs: int, override_rate: float, minimum_skips: int) -> list[Row]:
    """A rework row per playbook step skipped with a reason, or overridden in more than the given share of runs."""
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for log in logs:
        grouped.setdefault((log["runbook"], log["step"]), []).append(log)
    rows = []
    for (runbook, step), entries in sorted(grouped.items()):
        skipped = [entry for entry in entries if entry["override_reason"]]
        overridden = [entry for entry in entries if entry["acted"] == OVERRIDDEN_ACTED]
        measured = len(entries)
        share = len(overridden) / measured if measured else 0.0
        reasons = []
        if len(skipped) >= minimum_skips:
            reasons.append(
                f"{len(skipped)} of {measured} run(s) skipped it with a reason, first: {skipped[0]['override_reason'][:120]}"
            )
        if measured >= minimum_runs and share > override_rate:
            reasons.append(f"overridden in {len(overridden)} of {measured} run(s), {share:.0%} over {override_rate:.0%}")
        if not reasons:
            continue
        rows.append(
            Row(
                REWORK,
                f"{runbook} step {step}",
                "steps overridden or skipped",
                len(skipped) + len(overridden),
                0,
                one_line("; ".join(reasons)),
            )
        )
    return rows


def timestamp_seconds(value: object) -> float | None:
    """One recorded timestamp in seconds, or None when it cannot be placed in time."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def step_number(value: str) -> float:
    """One step's position as a number, or infinity when its label carries none."""
    digits = re.findall(r"\d+", value)
    return float(digits[0]) if digits else float("inf")


def move_earlier_rows(
    logs: list[dict[str, str]], interventions: dict[str, list[float]]
) -> tuple[list[Row], list[str]]:
    """A move-earlier row per intervention landing after a step whose evidence an earlier step already had."""
    by_session: dict[str, list[dict[str, str]]] = {}
    undated = 0
    for log in logs:
        if not log["session_id"]:
            continue
        if timestamp_seconds(log["timestamp"]) is None:
            undated += 1
            continue
        by_session.setdefault(log["session_id"], []).append(log)
    notes = []
    if undated:
        notes.append(f"{undated} step-log row(s) carry no readable timestamp, so no intervention could be placed after them")
    rows = []
    seen: set[tuple[str, str, str]] = set()
    for session_id, stamps in sorted(interventions.items()):
        entries = sorted(by_session.get(session_id, []), key=lambda entry: timestamp_seconds(entry["timestamp"]))
        if not entries:
            continue
        for landed in sorted(stamps):
            before = [entry for entry in entries if timestamp_seconds(entry["timestamp"]) <= landed]
            if not before:
                continue
            late = before[-1]
            if not late["evidence_ref"]:
                continue
            earlier = [
                entry
                for entry in before[:-1]
                if entry["runbook"] == late["runbook"]
                and entry["evidence_ref"] == late["evidence_ref"]
                and step_number(entry["step"]) < step_number(late["step"])
            ]
            if not earlier:
                continue
            first = earlier[0]
            key = (late["runbook"], late["step"], first["step"])
            if key in seen:
                continue
            seen.add(key)
            evidence = (
                f"an intervention landed after {late['runbook']} step {late['step']}, whose evidence "
                f"{late['evidence_ref']} step {first['step']} already recorded in session {session_id[:8]}"
            )
            rows.append(
                Row(MOVE_EARLIER, f"{late['runbook']} step {late['step']}", "late catch points", 1, 0, one_line(evidence))
            )
    return rows, notes


def level_rows(rules: list[dict[str, object]], hooks: dict[str, object]) -> list[Row]:
    """A strengthen, weaken or simplify row per rule the hook runner's own suggestion names."""
    stopping = sum(1 for record in hooks.values() if getattr(record, "mode", "") == "stop")
    per_class: dict[str, list[dict[str, object]]] = {}
    for rule in rules:
        finding_class = SUGGESTION_CLASSES.get(str(rule.get("suggestion") or ""))
        if finding_class is None:
            continue
        per_class.setdefault(finding_class, []).append(rule)
    rows = []
    for finding_class, found in sorted(per_class.items()):
        for rule in found:
            if finding_class == STRENGTHEN:
                measure, base, head = "hooks at stop", stopping, stopping + len(found)
            elif finding_class == WEAKEN:
                measure, base, head = "hooks at stop", stopping, stopping - len(found)
            else:
                measure, base, head = "registered hooks", len(hooks), len(hooks) - len(found)
            evidence = (
                f"{rule.get('hook')} rule {rule.get('rule_id')}: fires={rule.get('fires')} "
                f"stopped={rule.get('stopped')} warned={rule.get('warned')} acted={rule.get('acted')} "
                f"ignored={rule.get('ignored')} overridden={rule.get('overridden')} "
                f"unchecked={rule.get('unchecked')} ignore_rate={rule.get('ignore_rate')} "
                f"suggestion={rule.get('suggestion')}"
            )
            rows.append(Row(finding_class, f"{rule.get('hook')} {rule.get('rule_id')}", measure, base, head, one_line(evidence)))
    return rows


def shared_word_count(left: Item, right: Item) -> int:
    """How many words two stated purposes have in common, used only to order which pair is judged first."""
    def words(item: Item) -> set[str]:
        return {word for word in re.findall(r"[a-z]{4,}", f"{item.name} {item.purpose}".lower())}

    return len(words(left) & words(right))


def candidate_pairs(items: list[Item]) -> list[tuple[Item, Item]]:
    """Every unordered pair of items, the ones sharing the most words first so a cap judges those first."""
    pairs = []
    for first in range(len(items)):
        for second in range(first + 1, len(items)):
            pairs.append((items[first], items[second]))
    pairs.sort(key=lambda pair: (-shared_word_count(*pair), pair[0].name, pair[1].name))
    return pairs


def render_pair(left: Item, right: Item) -> str:
    """One pair as the two lines the judge reads."""
    return (
        f"A: {left.kind} {left.name} - {left.purpose or 'no stated purpose'}\n"
        f"B: {right.kind} {right.name} - {right.purpose or 'no stated purpose'}"
    )


def judge_overlap(
    repository_root: Path,
    items: list[Item],
    maximum_pairs: int,
    skipped_pairs: int,
    report_path: Path,
) -> tuple[list[Row], int]:
    """Overlap rows the judge called a hit, and how many pairs this run's window left unjudged."""
    pairs = candidate_pairs(items)
    if not pairs:
        return [], 0
    judge, phrases = load_judge(repository_root)
    try:
        dictionary = phrases.load(OVERLAP_CHECKER, str(PHRASES_DIRECTORY))
    except ValueError as error:
        raise Unchecked(f"{PHRASES_DIRECTORY}: the overlap dictionary is unusable ({error}); no pair could be judged") from error
    start = max(0, skipped_pairs)
    judged = pairs[start:] if maximum_pairs <= 0 else pairs[start : start + maximum_pairs]
    capped = len(pairs) - len(judged)
    hits: list[tuple[str, str]] = []
    for left, right in judged:
        rendered = render_pair(left, right)
        job = phrases.job(dictionary, str(report_path), rendered)
        job["id"] = f"{OVERLAP_CHECKER}-{left.name}-{right.name}"
        verdict = judge.verdict(job, judge.ask_once(job["prompt"]))
        if verdict.get("outcome") == "unchecked":
            raise Unchecked(
                f"{left.name} and {right.name} came back unchecked from the judge ({one_line(verdict.get('reason'))}); "
                "an overlapping pair could not be told from a distinct one"
            )
        if verdict.get("outcome") != "hit":
            continue
        hits.append(
            (
                f"{left.name} and {right.name}",
                one_line(f"the judge answered {verdict.get('reason')} for: {rendered}"),
            )
        )
    rows = [
        Row(COMBINE, subject, "registered skills and hooks", len(items), len(items) - len(hits), evidence)
        for subject, evidence in hits
    ]
    return rows, capped


def discover_transcripts(
    directory: Path,
    window_days: int,
    now_seconds: float,
    maximum_sessions: int,
) -> tuple[list[Path], int, list[str]]:
    """The newest own-session transcripts inside the window, how many the cap left out, and what could not be timed."""
    root = Path(os.path.expanduser(str(directory)))
    if not root.is_dir():
        raise Unchecked(f"{root}: no transcript directory; no intervention could be placed in a session's step order")
    opens = now_seconds - window_days * SECONDS_PER_DAY
    dated: list[tuple[float, Path]] = []
    notes: list[str] = []
    for path in sorted(root.glob("**/*.jsonl")):
        if "subagents" in path.parts:
            continue
        try:
            modified = path.stat().st_mtime
        except OSError as error:
            notes.append(f"{path}: modification time unreadable ({type(error).__name__}: {error}); the window could not place it")
            continue
        if modified >= opens:
            dated.append((modified, path))
    dated.sort(key=lambda entry: -entry[0])
    kept = dated if maximum_sessions <= 0 else dated[:maximum_sessions]
    return [path for _modified, path in kept], len(dated) - len(kept), notes


def intervention_timestamps(
    step_order_module,
    paths: list[Path],
    metrics_directory: Path,
) -> tuple[dict[str, list[float]], list[str]]:
    """When a human intervened in each session, and every session whose step order was only partly read."""
    landed: dict[str, list[float]] = {}
    notes: list[str] = []
    for path in paths:
        session = step_order_module.step_order(str(path), str(metrics_directory))
        for reason in session.get("unchecked") or []:
            notes.append(f"{path.name}: {one_line(reason)}")
        session_id = str(session.get("session_id") or "")
        if not session_id:
            continue
        for step in session.get("steps") or []:
            if step.get("kind") != INTERVENTION_KIND:
                continue
            seconds = timestamp_seconds(step.get("ts"))
            if seconds is None:
                notes.append(f"{path.name}: an intervention carries no timestamp, so it could not be placed after a step")
                continue
            landed.setdefault(session_id, []).append(seconds)
    return landed, notes


def proposal_title(finding_class: str, rows: list[Row]) -> str:
    """The title one class's proposal carries, with the automatic prefix the mine path reserves."""
    return f"{AUTOMATIC_TITLE_PREFIX} lifecycle: {finding_class} ({len(rows)} subject(s))"


def proposal_body(finding_class: str, rows: list[Row], window_days: int, command: str) -> str:
    """One class's proposal in the house pull request schema, carrying its base and head counts."""
    measure = rows[0].measure
    base = rows[0].base_count
    head = rows[0].head_count
    subjects = "\n".join(f"| {row.subject} | {row.evidence} |" for row in rows)
    return "\n".join(
        [
            "## Summary",
            "",
            f"The lifecycle pass read the last {window_days} days of its own records and found {len(rows)} "
            f"thing(s) a person should decide to {finding_class.replace('-', ' ')}.",
            "",
            "Nothing here is applied. The pass never edits a live rule and never merges.",
            "",
            "## Review Claim",
            "",
            f"Each subject below meets the {finding_class} rule on the window's measured records, at the "
            "thresholds the command names.",
            "",
            "## Review Lane",
            "",
            "behavior",
            "",
            "## Safety Invariant",
            "",
            "Assumptions: unconfirmed. This body was drafted headlessly. The pass reads records and writes only "
            "its own report and proposals; it never edits a skill, a hook, or a playbook, and never merges.",
            "",
            "## Non-goals",
            "",
            "- No automatic merge.",
            "- No live edit to any skill, hook, or playbook.",
            "- No change to any other lifecycle class; each class is its own proposal.",
            "",
            "## Measured",
            "",
            f"base {measure} = {base}",
            f"head {measure} = {head}",
            "",
            "| subject | evidence |",
            "| --- | --- |",
            subjects,
            "",
            "## Test Plan",
            "",
            "```sh",
            command,
            "python3 engine/skills/reflect/scripts/tests/test_lifecycle.py",
            "```",
            "",
            "## Revert Plan",
            "",
            "Close this proposal. Nothing was applied, so there is nothing to revert.",
            "",
        ]
    )


def proposal_paths(rows: list[Row], directory: Path) -> dict[str, Path]:
    """Where each class with a finding gets its one proposal, so a report row can name it before it is written."""
    classes = {row.finding_class for row in rows if row.finding_class in PROPOSAL_CLASSES}
    return {name: directory / f"{name}.md" for name in PROPOSAL_CLASSES if name in classes}


def write_proposals(
    rows: list[Row],
    paths: dict[str, Path],
    window_days: int,
    command: str,
) -> dict[str, Path]:
    """One proposal file per class with a finding, or an Unchecked naming the write that failed."""
    per_class: dict[str, list[Row]] = {}
    for row in rows:
        if row.finding_class in paths:
            per_class.setdefault(row.finding_class, []).append(row)
    written: dict[str, Path] = {}
    for finding_class, path in paths.items():
        found = per_class[finding_class]
        body = proposal_body(finding_class, found, window_days, command)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{proposal_title(finding_class, found)}\n\n{body}", encoding="utf-8")
        except OSError as error:
            raise Unchecked(f"{path}: the proposal could not be written ({type(error).__name__}: {error})") from error
        written[finding_class] = path
    return written


def write_report(rows: list[Row], path: Path, proposals: dict[str, Path]) -> None:
    """The report as one tab-separated file, or an Unchecked naming the write that failed."""
    lines = ["\t".join(REPORT_COLUMNS)]
    for row in rows:
        proposal = proposals.get(row.finding_class)
        lines.append(
            "\t".join(
                [
                    row.finding_class,
                    one_line(row.subject),
                    one_line(row.measure),
                    str(row.base_count),
                    str(row.head_count),
                    one_line(row.evidence),
                    "none" if proposal is None else str(proposal),
                ]
            )
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as error:
        raise Unchecked(f"{path}: the report could not be written ({type(error).__name__}: {error})") from error


def open_proposal_pull_requests(
    proposals: dict[str, Path],
    repository_root: Path,
    base_branch: str,
    head_branch: str,
) -> tuple[dict[str, str], list[str]]:
    """One pull request per class that has none open yet, and every class whose open attempt failed."""
    opened: dict[str, str] = {}
    failures: list[str] = []
    for finding_class, path in sorted(proposals.items()):
        title = f"{AUTOMATIC_TITLE_PREFIX} lifecycle: {finding_class}"
        existing, error = open_pull_request_titles(title, repository_root)
        if error:
            failures.append(error)
            continue
        if existing:
            opened[finding_class] = f"already open: {existing[0]}"
            continue
        arguments = [
            "gh",
            "pr",
            "create",
            "--draft",
            "--title",
            title,
            "--body-file",
            str(path),
            "--base",
            base_branch,
            "--head",
            head_branch,
        ]
        try:
            finished = subprocess.run(arguments, capture_output=True, text=True, timeout=120, cwd=str(repository_root))
        except (OSError, subprocess.SubprocessError) as error:
            failures.append(f"{finding_class}: gh pr create failed ({type(error).__name__}: {error})")
            continue
        if finished.returncode != 0:
            failures.append(f"{finding_class}: gh pr create exited {finished.returncode}: {one_line(finished.stderr)[:200]}")
            continue
        opened[finding_class] = one_line(finished.stdout)
    return opened, failures


def open_pull_request_titles(title: str, repository_root: Path) -> tuple[list[str], str]:
    """The open pull requests already carrying this title, and the reason the listing could not be trusted."""
    arguments = ["gh", "pr", "list", "--state", "open", "--search", title, "--json", "number,url,title"]
    try:
        finished = subprocess.run(arguments, capture_output=True, text=True, timeout=60, cwd=str(repository_root))
    except (OSError, subprocess.SubprocessError) as error:
        return [], f"gh pr list failed ({type(error).__name__}: {error}); an open proposal could not be told from none"
    if finished.returncode != 0:
        return [], f"gh pr list exited {finished.returncode}: {one_line(finished.stderr)[:200]}"
    try:
        listed = json.loads(finished.stdout or "[]")
    except ValueError as error:
        return [], f"gh pr list printed no readable JSON ({error})"
    if not isinstance(listed, list):
        return [], "gh pr list printed a JSON object, not a list of pull requests"
    return [str(entry.get("url") or entry.get("number")) for entry in listed if str(entry.get("title") or "") == title], ""


def read_window_rows(report_module, metrics_directory: Path, threshold: datetime):
    """The window's hook event rows and step-log rows, or an Unchecked when neither signal can be read."""
    event_rows, event_malformed, event_warnings = report_module.read_event_rows(metrics_directory, threshold)
    if event_rows is None:
        raise Unchecked(f"{metrics_directory}: no hook event rows could be read ({'; '.join(event_warnings)})")
    run_rows, run_malformed, run_error = report_module.read_rows(metrics_directory / RUNS_FILE_NAME, threshold)
    if run_rows is None:
        raise Unchecked(f"{metrics_directory / RUNS_FILE_NAME}: no step-log rows could be read ({run_error})")
    notes = [one_line(warning) for warning in event_warnings]
    if event_malformed or run_malformed:
        notes.append(f"skipped {event_malformed} malformed event row(s) and {run_malformed} malformed run row(s)")
    return event_rows, event_malformed, run_rows, notes


def measured_skill_use(event_rows: list[dict[str, object]], metrics_directory: Path) -> dict[str, dict[str, int]]:
    """How often each skill was used in the window, or an Unchecked when no row names any skill at all."""
    counts, _unreadable = skill_use_counts(event_rows)
    if not counts:
        raise Unchecked(
            f"{metrics_directory}: no skill-use row names any skill inside the window, so no skill's use could be "
            "measured; a skill nobody recorded is not a skill nobody used"
        )
    return counts


def read_interventions(
    metrics_directory: Path,
    transcripts_directory: Path,
    window_days: int,
    now_seconds: float,
    maximum_sessions: int,
) -> tuple[dict[str, list[float]], list[str]]:
    """When a human intervened in each session of the window, or an Unchecked when no session could be read."""
    step_order_module = load_step_order()
    transcripts, dropped, notes = discover_transcripts(transcripts_directory, window_days, now_seconds, maximum_sessions)
    if dropped:
        notes.append(f"{dropped} session(s) inside the window were left out by --max-sessions {maximum_sessions}")
    landed, session_notes = intervention_timestamps(step_order_module, transcripts, metrics_directory)
    return landed, notes + session_notes


def run_pass(options: argparse.Namespace, command: str) -> Pass:
    """The whole pass: read every signal, apply the rules each signal supports, write the report, and decide one outcome."""
    result = Pass()
    now_seconds = time.time()
    repository_root = Path(options.repository_root).resolve()
    metrics_directory = Path(os.path.expanduser(options.metrics_dir))
    report_path = Path(options.out)
    threshold = datetime.fromtimestamp(now_seconds, timezone.utc) - timedelta(days=options.window_days)
    try:
        report_module, registry_module = load_hook_report(repository_root)
        event_rows, event_malformed, run_rows, read_notes = read_window_rows(report_module, metrics_directory, threshold)
        result.notes.extend(read_notes)
        skill_items, purpose_notes = read_skill_items(repository_root)
        result.notes.extend(purpose_notes)
        hook_items, hooks, registry_thresholds = read_hook_items(
            registry_module, repository_root / "engine" / "hooks" / "hooks.toml"
        )
    except Unchecked as error:
        result.blockers.append(one_line(error))
        return finish_pass(result, options, report_path, repository_root, command)

    counts, unreadable_skill_runs = skill_use_counts(event_rows)
    result.notes.append(skill_use_basis(event_rows, counts))
    if unreadable_skill_runs:
        result.notes.append(f"{unreadable_skill_runs} skill-usage-log run(s) could not read their own input")
    measured = result.attempt(measured_skill_use, event_rows, metrics_directory)
    clusters = result.attempt(read_mine_clusters, Path(os.path.expanduser(options.state_dir)))
    structural = result.attempt(read_structural_wins, Path(options.structural_wins))
    cited = result.attempt(hook_citations, repository_root, [item.name for item in skill_items])
    interventions = result.attempt(
        read_interventions,
        metrics_directory,
        Path(options.transcripts_dir),
        options.window_days,
        now_seconds,
        options.max_sessions,
    )
    overlap = result.attempt(
        judge_overlap,
        repository_root,
        skill_items + hook_items,
        options.max_judge_pairs,
        options.judge_skip_pairs,
        report_path,
    )

    logs = step_log_rows(run_rows)
    thresholds = chosen_thresholds(registry_module, registry_thresholds, options)
    rules = report_module.build_event_report(event_rows, event_malformed, [], (hooks, thresholds))["rules"]
    result.rows.extend(rework_rows(logs, options.rework_min_runs, options.rework_override_rate, options.rework_min_skips))
    result.rows.extend(level_rows(rules, hooks))
    if None not in (measured, clusters, structural, cited):
        citations, citation_notes = cited
        result.notes.extend(citation_notes)
        result.rows.extend(
            retire_rows(
                skill_items,
                measured,
                clusters,
                citations,
                speaking_hooks(event_rows, run_rows),
                structural,
                options.window_days,
            )
        )
    if clusters is not None:
        result.rows.extend(coverage_gap_rows(clusters))
    if interventions is not None:
        landed, intervention_notes = interventions
        result.notes.extend(intervention_notes)
        late, late_notes = move_earlier_rows(logs, landed)
        result.notes.extend(late_notes)
        result.rows.extend(late)
    if overlap is not None:
        combine, capped = overlap
        result.rows.extend(combine)
        if capped:
            result.rows.append(
                Row(
                    CAPPED_CLASS,
                    "overlap pairs",
                    "pairs left unjudged",
                    capped,
                    0,
                    f"--max-judge-pairs {options.max_judge_pairs} after --judge-skip-pairs {options.judge_skip_pairs} "
                    f"judged the most word-sharing pairs first and left {capped} unjudged; raise the skip to walk the rest",
                )
            )
    return finish_pass(result, options, report_path, repository_root, command)


def finish_pass(
    result: Pass,
    options: argparse.Namespace,
    report_path: Path,
    repository_root: Path,
    command: str,
) -> Pass:
    """Write the report and the proposals a fully read window earned, and settle the one outcome."""
    for note in result.notes:
        result.rows.append(Row(NOTE_CLASS, "partly read", "notes", 1, 1, one_line(note)))
    for blocker in result.blockers:
        result.rows.append(Row(UNCHECKED_CLASS, "source", "blockers", 1, 1, one_line(blocker)))

    findings = [row for row in result.rows if row.finding_class in PROPOSAL_CLASSES]
    planned = {} if result.blockers else proposal_paths(findings, report_path.parent / PROPOSALS_DIRECTORY_NAME)
    try:
        write_report(result.rows, report_path, planned)
    except Unchecked as error:
        result.blockers.append(one_line(error))
        return blocked(result, one_line(error))

    if result.blockers:
        return blocked(result, result.blockers[0])

    if not findings:
        result.outcome = OUTCOME_CLEAN
        result.reason = f"no class fired over the last {options.window_days} day(s)"
        return result

    try:
        result.proposals = write_proposals(findings, planned, options.window_days, command)
    except Unchecked as error:
        result.blockers.append(one_line(error))
        return blocked(result, one_line(error))

    if options.open_prs:
        result.opened, failures = open_proposal_pull_requests(
            result.proposals, repository_root, options.base_branch, options.head_branch
        )
        if failures:
            result.blockers.extend(failures)
            return blocked(result, failures[0])

    result.outcome = OUTCOME_CHANGED
    result.reason = f"{len(result.proposals)} proposal(s): {', '.join(sorted(result.proposals))}"
    return result


def blocked(result: Pass, reason: str) -> Pass:
    """The pass as blocked, with the reason a reader sees first and no proposal written."""
    result.outcome = OUTCOME_BLOCKED
    result.reason = reason
    return result


def chosen_thresholds(registry_module, registry_thresholds, options: argparse.Namespace):
    """The promotion thresholds this run reads: the flag when given, otherwise the registry's own number."""
    return registry_module.Thresholds(
        min_closed_findings=pick(options.min_closed_findings, registry_thresholds.min_closed_findings),
        promote_max_ignore_rate=pick(options.promote_max_ignore_rate, registry_thresholds.promote_max_ignore_rate),
        demote_min_ignore_rate=pick(options.demote_min_ignore_rate, registry_thresholds.demote_min_ignore_rate),
        review_min_ignore_rate=pick(options.review_min_ignore_rate, registry_thresholds.review_min_ignore_rate),
        review_min_unchecked_rate=pick(options.review_min_unchecked_rate, registry_thresholds.review_min_unchecked_rate),
        followup_window_checks=registry_thresholds.followup_window_checks,
    )


def pick(given: object, fallback: object) -> object:
    """The flag's value when one was given, otherwise the registry's own."""
    return fallback if given is None else given


def format_pass(result: Pass, report_path: Path) -> str:
    """What the pass prints: the outcome with its reason, then every row it wrote."""
    lines = [f"lifecycle: outcome={result.outcome} reason={result.reason}"]
    for finding_class in PROPOSAL_CLASSES:
        found = [row for row in result.rows if row.finding_class == finding_class]
        if found:
            lines.append(f"  {finding_class}: {len(found)} subject(s)")
    for extra in (STRUCTURAL_WIN_CLASS, CAPPED_CLASS, NOTE_CLASS, UNCHECKED_CLASS):
        found = [row for row in result.rows if row.finding_class == extra]
        if found:
            lines.append(f"  {extra}: {len(found)} row(s)")
    for finding_class, path in sorted(result.proposals.items()):
        opened = result.opened.get(finding_class)
        lines.append(f"  proposal {finding_class} -> {path}{'' if opened is None else f' ({opened})'}")
    lines.append(f"  report -> {report_path}")
    lines.append(f"  rows {len(result.rows)}")
    for row in result.rows:
        lines.append(f"  {row.finding_class}\t{row.subject}\t{row.base_count}->{row.head_count}\t{row.evidence}")
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    """The command line: one report subcommand, with every threshold as its own flag."""
    parser = argparse.ArgumentParser(description=f"{__doc__}\n\n{USAGE}", formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command", required=True)
    report_parser = subparsers.add_parser("report", help="read the window, write the report, write one proposal per class")
    report_parser.add_argument("--window-days", type=int, default=DEFAULT_WINDOW_DAYS)
    report_parser.add_argument("--out", default=DEFAULT_REPORT_PATH)
    report_parser.add_argument("--state-dir", default=DEFAULT_STATE_DIRECTORY)
    report_parser.add_argument("--metrics-dir", default=DEFAULT_METRICS_DIRECTORY)
    report_parser.add_argument("--transcripts-dir", default=DEFAULT_TRANSCRIPTS_DIRECTORY)
    report_parser.add_argument("--repository-root", default=str(DEFAULT_REPOSITORY_ROOT))
    report_parser.add_argument("--structural-wins", default=str(DEFAULT_REPOSITORY_ROOT / DEFAULT_STRUCTURAL_WINS_PATH))
    report_parser.add_argument("--max-judge-pairs", type=int, default=DEFAULT_MAXIMUM_JUDGE_PAIRS)
    report_parser.add_argument("--judge-skip-pairs", type=int, default=0)
    report_parser.add_argument("--max-sessions", type=int, default=DEFAULT_MAXIMUM_SESSIONS)
    report_parser.add_argument("--rework-min-runs", type=int, default=DEFAULT_REWORK_MINIMUM_RUNS)
    report_parser.add_argument("--rework-override-rate", type=float, default=DEFAULT_REWORK_OVERRIDE_RATE)
    report_parser.add_argument("--rework-min-skips", type=int, default=DEFAULT_REWORK_MINIMUM_SKIPS)
    report_parser.add_argument("--min-closed-findings", type=int, default=None)
    report_parser.add_argument("--promote-max-ignore-rate", type=float, default=None)
    report_parser.add_argument("--demote-min-ignore-rate", type=float, default=None)
    report_parser.add_argument("--review-min-ignore-rate", type=float, default=None)
    report_parser.add_argument("--review-min-unchecked-rate", type=float, default=None)
    report_parser.add_argument("--open-prs", action="store_true")
    report_parser.add_argument("--base-branch", default="main")
    report_parser.add_argument("--head-branch", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one pass and print its single outcome."""
    arguments = sys.argv[1:] if argv is None else argv
    options = build_parser().parse_args(arguments)
    if options.open_prs and not options.head_branch:
        print("lifecycle: outcome=blocked reason=--open-prs needs --head-branch", file=sys.stderr)
        return EXIT_BLOCKED
    command = "python3 engine/skills/reflect/scripts/lifecycle.py " + " ".join(arguments)
    result = run_pass(options, command)
    print(format_pass(result, Path(options.out)), end="")
    if result.outcome == OUTCOME_BLOCKED:
        return EXIT_BLOCKED
    return EXIT_CHANGED if result.outcome == OUTCOME_CHANGED else EXIT_CLEAN


if __name__ == "__main__":
    raise SystemExit(main())
