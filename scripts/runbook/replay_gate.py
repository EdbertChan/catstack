#!/usr/bin/env python3
"""Replay the runbook gate over the last 90 days of local transcripts and count fired, would-block and false-fire stops."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GATE_DIRECTORY = REPOSITORY_ROOT / "engine" / "hooks" / "runbook-gate"
HOOK_SDK_DIRECTORY = REPOSITORY_ROOT / "engine" / "hooks" / "_sdk"
REFLECT_SCRIPTS_DIRECTORY = REPOSITORY_ROOT / "engine" / "skills" / "reflect" / "scripts"
DEFAULT_PROJECTS_DIRECTORY = Path("~/.claude/projects")
DEFAULT_WINDOW_DAYS = 90
SECONDS_PER_DAY = 86400
SUBAGENT_DIRECTORY_NAME = "subagents"
INJECTION_MARKER = "Playbook:"
TRANSCRIPT_GLOB = "**/*.jsonl"
HARNESS = "claude"
FALSE_FIRE_CEILING_PERCENT = 10.0
SESSION_NAME_WIDTH = 44
EXIT_CLEAN = 0
EXIT_NOTHING = 1
EXIT_UNCHECKED = 2
USAGE = (
    "Each turn-ending assistant reply is replayed as one Stop: the transcript is cut to that reply, the gate's "
    "own decision function is called on the cut, and its playbook injection is read the way the live hook reads "
    "it. A session carrying no injection marker anywhere skips the gate, because the gate returns nothing when "
    "no playbook was injected. fired counts the stops where the gate measured a step, would-block counts the stops where it returned "
    "its unproven-hard-step block, and false-fire counts a would-block that no classified human intervention "
    "followed, as token_audit classifies interventions. A would-block at a session's last stop has no later "
    "message to classify, so it counts as a false fire and is also counted on its own line. The printed rate is "
    f"what decision D4 reads: a hard gate stays hard only under {FALSE_FIRE_CEILING_PERCENT:.0f} percent. "
    "Exit 0 replayed, exit 1 found no "
    "transcript to replay, and exit 2 is unchecked: the gate or every transcript could not be read, which is "
    "never reported as a pass."
)


class Unchecked(Exception):
    """Raised when the gate or the transcript set cannot be read, so no stop is reported clean.

    The caller prints the reason and exits 2.
    """


@dataclass
class SessionReplay:
    """One session's replay: how many stops it had, and what the gate did at each."""

    path: Path
    stops: int = 0
    injected: bool = True
    fired: int = 0
    would_block: int = 0
    false_fire: int = 0
    blocked_then_intervened: int = 0
    final_stop_blocks: int = 0
    unchecked_stops: int = 0
    unchecked: list[str] = field(default_factory=list)


def load_gate():
    """Import the runbook gate's own decision function, or refuse rather than replay a stand-in."""
    for directory in (str(GATE_DIRECTORY), str(HOOK_SDK_DIRECTORY)):
        if directory not in sys.path:
            sys.path.insert(0, directory)
    path = GATE_DIRECTORY / "detect.py"
    specification = importlib.util.spec_from_file_location("runbook_gate_replay_detect", path)
    if specification is None or specification.loader is None:
        raise Unchecked(f"{path}: the gate's decision function could not be loaded; no stop could be replayed")
    module = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = module
    try:
        specification.loader.exec_module(module)
    except Exception as error:
        raise Unchecked(f"{path}: the gate's decision function could not be imported ({type(error).__name__}: {error})") from error
    return module


def load_interventions():
    """Import the reflect miner that classifies human interventions, or refuse rather than count none."""
    if str(REFLECT_SCRIPTS_DIRECTORY) not in sys.path:
        sys.path.insert(0, str(REFLECT_SCRIPTS_DIRECTORY))
    try:
        import step_order
        import token_audit
    except ImportError as error:
        raise Unchecked(
            f"{REFLECT_SCRIPTS_DIRECTORY}: the intervention classifier could not be imported ({error}); "
            "a block with no intervention after it could not be told from a true fire"
        ) from error
    return step_order, token_audit


def discover_transcripts(projects_directory: Path, window_days: int, now_seconds: float) -> tuple[list[Path], list[str]]:
    """Every own-session transcript modified inside the window, and what was skipped."""
    root = Path(os.path.expanduser(str(projects_directory)))
    if not root.is_dir():
        raise Unchecked(f"{root}: no transcript directory; the window could not be read")
    opens = now_seconds - window_days * SECONDS_PER_DAY
    kept: list[Path] = []
    skipped_old = 0
    skipped_subagent = 0
    unreadable: list[str] = []
    for path in sorted(root.glob(TRANSCRIPT_GLOB)):
        if SUBAGENT_DIRECTORY_NAME in path.parts:
            skipped_subagent += 1
            continue
        try:
            modified = path.stat().st_mtime
        except OSError as error:
            unreadable.append(f"{path}: modification time unreadable ({error}); the window could not place it")
            continue
        if modified < opens:
            skipped_old += 1
            continue
        kept.append(path)
    notes = [
        f"skipped {skipped_subagent} subagent transcript(s): they are the parent session's delegated work",
        f"skipped {skipped_old} transcript(s) older than the {window_days}-day window",
    ]
    return kept, notes + unreadable


def read_rows(path: Path) -> tuple[list[dict[str, object]], int]:
    """One transcript's rows, indexed the way the intervention classifier indexes them, and the unparsable count."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as error:
        raise Unchecked(f"{path}: transcript unreadable ({error})") from error
    rows: list[dict[str, object]] = []
    malformed = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            row = json.loads(stripped)
        except ValueError:
            malformed += 1
            continue
        rows.append(row if isinstance(row, dict) else {})
    return rows, malformed


def row_strings(node: object) -> list[str]:
    """Every string anywhere inside one transcript row."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [found for value in node.values() for found in row_strings(value)]
    if isinstance(node, list):
        return [found for value in node for found in row_strings(value)]
    return []


def assistant_text(row: dict[str, object]) -> str:
    """The text the agent itself wrote in one transcript row."""
    if row.get("type") != "assistant":
        return ""
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else row.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "\n".join(parts)


def stop_points(rows: list[dict[str, object]], human_indices: set[int]) -> list[tuple[int, str]]:
    """Every turn-ending assistant reply, as the index and text of the reply a Stop would carry."""
    stops: list[tuple[int, str]] = []
    held: tuple[int, str] | None = None
    for index, row in enumerate(rows):
        if index in human_indices and held is not None:
            stops.append(held)
            held = None
        text = assistant_text(row)
        if text.strip():
            held = (index, text)
    if held is not None:
        stops.append(held)
    return stops


def human_message_indices(token_audit, rows: list[dict[str, object]], path: Path) -> set[int]:
    """The rows a person typed, as the reflect classifier reads them."""
    messages, _review_indices = token_audit._claude_frustration_messages(rows, str(path))
    return {index for index, _stamp, _text in messages}


def intervention_indices(step_order, token_audit, path: Path) -> tuple[list[int], list[str]]:
    """The rows carrying a classified human intervention, and any reason the classification was partial."""
    steps, unchecked = step_order.intervention_steps(str(path))
    indices = [
        step["index"] for step in steps
        if set(str(step["id"]).split("+")) & token_audit.INTERVENTION_KINDS
    ]
    return sorted(indices), list(unchecked)


def replay_stop(gate, path: Path, rows: list[dict[str, object]], stop_index: int, reply: str, directory: Path) -> tuple[list[object], list[object]]:
    """Call the gate on the transcript cut to one stop, and hand back its block and its measured rows."""
    cut = directory / f"{path.stem}-stop-{stop_index}.jsonl"
    cut.write_text("".join(json.dumps(row) + "\n" for row in rows[: stop_index + 1]), encoding="utf-8")
    event: dict[str, object] = {
        "transcript_path": str(cut),
        "session_id": f"{path.name}#stop{stop_index}",
        "last_assistant_message": reply,
        "_catstack_harness": HARNESS,
    }
    findings = gate.detect(event)
    return findings, event.get("_catstack_silent_findings") or []


def replay_session(gate, step_order, token_audit, path: Path, directory: Path) -> SessionReplay:
    """Replay every stop in one session and count what the gate did at each."""
    replay = SessionReplay(path=path)
    try:
        rows, malformed = read_rows(path)
    except Unchecked as unchecked:
        replay.unchecked.append(str(unchecked))
        return replay
    if malformed:
        replay.unchecked.append(f"{path}: {malformed} line(s) were not readable rows, so their stops were not replayed")
    interventions, intervention_unchecked = intervention_indices(step_order, token_audit, path)
    replay.unchecked.extend(intervention_unchecked)
    stops = stop_points(rows, human_message_indices(token_audit, rows, path))
    replay.stops = len(stops)
    replay.injected = any(INJECTION_MARKER in text for row in rows for text in row_strings(row))
    if not replay.injected:
        return replay
    for stop_index, reply in stops:
        findings, measured = replay_stop(gate, path, rows, stop_index, reply, directory)
        rule_ids = [finding.rule_id for finding in findings]
        if measured:
            replay.fired += 1
        if gate.RULE_UNCHECKED in rule_ids:
            replay.unchecked_stops += 1
        if gate.RULE_UNPROVEN in rule_ids:
            replay.would_block += 1
            if stop_index == stops[-1][0]:
                replay.final_stop_blocks += 1
            if any(index > stop_index for index in interventions):
                replay.blocked_then_intervened += 1
            else:
                replay.false_fire += 1
    return replay


def session_label(path: Path) -> str:
    """One session named the way a person reading the table would name it."""
    name = f"{path.parent.name}/{path.name}"
    if len(name) <= SESSION_NAME_WIDTH:
        return name
    return "…" + name[-(SESSION_NAME_WIDTH - 1):]


def listed(replays: list[SessionReplay], show_all: bool) -> list[SessionReplay]:
    """The sessions the table lists: every one, or only those the gate did something in."""
    if show_all:
        return replays
    return [replay for replay in replays if replay.fired or replay.would_block or replay.unchecked_stops]


def render_table(replays: list[SessionReplay], show_all: bool = True) -> str:
    """The replay table, in the markdown shape a pull request body carries."""
    lines = [
        "| session | stops | fired | would-block | false-fire | block then intervention | unchecked stops |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for replay in listed(replays, show_all):
        lines.append(
            f"| {session_label(replay.path)} | {replay.stops} | {replay.fired} | {replay.would_block} | "
            f"{replay.false_fire} | {replay.blocked_then_intervened} | {replay.unchecked_stops} |"
        )
    totals = totals_of(replays)
    lines.append(
        f"| totals ({len(replays)} session(s)) | {totals['stops']} | {totals['fired']} | {totals['would_block']} | "
        f"{totals['false_fire']} | {totals['blocked_then_intervened']} | {totals['unchecked_stops']} |"
    )
    return "\n".join(lines)


def totals_of(replays: list[SessionReplay]) -> dict[str, int]:
    """Every replay count added up across the sessions."""
    return {
        "stops": sum(replay.stops for replay in replays),
        "fired": sum(replay.fired for replay in replays),
        "would_block": sum(replay.would_block for replay in replays),
        "false_fire": sum(replay.false_fire for replay in replays),
        "blocked_then_intervened": sum(replay.blocked_then_intervened for replay in replays),
        "final_stop_blocks": sum(replay.final_stop_blocks for replay in replays),
        "sessions_without_injection": sum(1 for replay in replays if not replay.injected),
        "unchecked_stops": sum(replay.unchecked_stops for replay in replays),
        "partly_checked_sessions": sum(1 for replay in replays if replay.unchecked),
    }


def false_fire_percent(totals: dict[str, int]) -> float | None:
    """The share of would-block stops no human intervention followed, or None when nothing blocked."""
    if not totals["would_block"]:
        return None
    return 100.0 * totals["false_fire"] / totals["would_block"]


def render_verdict(totals: dict[str, int]) -> list[str]:
    """The measured false-fire rate and what decision D4 reads from it."""
    ceiling = f"{FALSE_FIRE_CEILING_PERCENT:.0f}"
    percent = false_fire_percent(totals)
    if percent is None:
        return [
            f"false-fire rate: unchecked, no would-block fired across {totals['stops']} replayed stop(s)",
            f"decision D4: unchecked; a hard gate stays hard only under {ceiling} percent, and this replay measured no rate",
        ]
    verdict = "under the ceiling, so the hard gate may stay hard" if percent < FALSE_FIRE_CEILING_PERCENT else "over the ceiling, so the hard gate may not stay hard"
    return [
        f"false-fire rate: {totals['false_fire']} of {totals['would_block']} would-block(s) = {percent:.1f} percent",
        f"decision D4: {percent:.1f} percent against a {ceiling} percent ceiling is {verdict}",
        f"of those would-block(s), {totals['final_stop_blocks']} sat at a session's last stop, where no later "
        "message exists to classify, so each one counts as a false fire by this definition",
    ]


def expand_paths(paths: list[Path]) -> list[Path]:
    """Every transcript named on the command line, directories included."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(sorted(path.glob("*.jsonl")))
        else:
            found.append(path)
    return found


def report_unchecked(replays: list[SessionReplay]) -> None:
    """Name every session whose replay was partial, so a partial sweep never reads as a full one."""
    partial = [replay for replay in replays if replay.unchecked or replay.unchecked_stops]
    if not partial:
        print(f"every one of the {len(replays)} replayed session(s) was fully checked")
        return
    grouped: dict[str, int] = {}
    for replay in partial:
        if replay.unchecked_stops:
            grouped["the gate reported an unchecked stop"] = grouped.get("the gate reported an unchecked stop", 0) + 1
        for reason in replay.unchecked:
            grouped[reason] = grouped.get(reason, 0) + 1
    print(
        f"{len(partial)} of {len(replays)} session(s) replayed only partly, so the rate above may be "
        "over-counted or under-counted:",
        file=sys.stderr,
    )
    for reason, count in sorted(grouped.items(), key=lambda item: (-item[1], item[0])):
        print(f"  {count} session(s): {reason}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, epilog=USAGE)
    parser.add_argument("paths", nargs="*", type=Path, help="transcripts or directories of *.jsonl; overrides discovery")
    parser.add_argument("--days", type=int, default=DEFAULT_WINDOW_DAYS, help="how far back discovery reaches")
    parser.add_argument("--projects-dir", type=Path, default=DEFAULT_PROJECTS_DIRECTORY)
    parser.add_argument("--now", default=None, help="ISO timestamp the window ends on; default is now")
    parser.add_argument("--json", dest="json_out", type=Path, default=None, help="write the counts as JSON")
    parser.add_argument("--all-sessions", action="store_true", help="list every session, not only the ones the gate acted in")
    return parser


def window_now(declared: str | None) -> float:
    """The epoch second the window ends on, declared or current."""
    if not declared:
        return datetime.now(timezone.utc).timestamp()
    try:
        return datetime.fromisoformat(declared.replace("Z", "+00:00")).timestamp()
    except ValueError as error:
        raise Unchecked(f"--now {declared!r} is not an ISO timestamp ({error}); the window could not be placed") from error


def replay(arguments: argparse.Namespace) -> int:
    """Replay every discovered session's stops through the gate and print the table."""
    gate = load_gate()
    step_order, token_audit = load_interventions()
    if arguments.paths:
        transcripts = expand_paths(arguments.paths)
        notes = [f"replayed {len(transcripts)} transcript(s) named on the command line, so the {arguments.days}-day window was not applied"]
    else:
        transcripts, notes = discover_transcripts(arguments.projects_dir, arguments.days, window_now(arguments.now))
    for note in notes:
        print(note)
    if not transcripts:
        print("no transcript to replay in this window", file=sys.stderr)
        return EXIT_NOTHING
    with tempfile.TemporaryDirectory(prefix="catstack-replay-gate-") as workspace:
        os.environ[gate.progress.STATE_DIR_ENV] = os.path.join(workspace, "notes")
        replays = [
            replay_session(gate, step_order, token_audit, path, Path(workspace))
            for path in transcripts
        ]
    totals = totals_of(replays)
    print(
        f"{totals['sessions_without_injection']} of {len(replays)} session(s) carried no playbook injection "
        "anywhere, so no stop in them could have fired and their stops went to the gate uncalled"
    )
    print(render_table(replays, arguments.all_sessions))
    folded = len(replays) - len(listed(replays, arguments.all_sessions))
    if folded:
        print(f"folded {folded} session(s) the gate did nothing in into the totals row; pass --all-sessions to list them")
    for line in render_verdict(totals):
        print(line)
    report_unchecked(replays)
    if arguments.json_out:
        arguments.json_out.parent.mkdir(parents=True, exist_ok=True)
        arguments.json_out.write_text(json.dumps({
            "totals": totals,
            "false_fire_percent": false_fire_percent(totals),
            "sessions": [
                {
                    "path": str(item.path),
                    "stops": item.stops,
                    "fired": item.fired,
                    "would_block": item.would_block,
                    "false_fire": item.false_fire,
                    "blocked_then_intervened": item.blocked_then_intervened,
                    "final_stop_blocks": item.final_stop_blocks,
                    "injected": item.injected,
                    "unchecked_stops": item.unchecked_stops,
                    "unchecked": item.unchecked,
                }
                for item in replays
            ],
        }, indent=1), encoding="utf-8")
        print(f"wrote {arguments.json_out}")
    if all(replay_item.unchecked and replay_item.stops == 0 for replay_item in replays):
        print(f"unchecked: no stop was replayed in any of the {len(replays)} session(s)", file=sys.stderr)
        return EXIT_UNCHECKED
    return EXIT_CLEAN


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    try:
        return replay(arguments)
    except Unchecked as unchecked:
        print(f"unchecked: {unchecked}", file=sys.stderr)
        return EXIT_UNCHECKED


if __name__ == "__main__":
    raise SystemExit(main())
