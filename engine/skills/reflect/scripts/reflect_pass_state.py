#!/usr/bin/env python3
"""Remember how far a reflect pass got so the next pass in the same session reads only the new turns.

Step 4 of reflect writes `<session-dir>/reflect-pass.json` after synthesis:

    {"ts": ..., "last_turn_index": N, "findings_path": ..., "lenses": [...]}

Step 1 of the next pass reads it. Turns are counted the way token_audit.py
counts them, by distinct assistant message id, so `last_turn_index` is the
number of assistant turns the earlier pass covered. The state file sits
beside the transcript, under the session's own directory next to its
`subagents/`, never inside a git checkout.

Three outcomes, because a check that could not run is not a pass:

    none       no state file; the pass is a full pass
    <state>    a readable state file; the pass covers only the delta
    unchecked  a state file exists but cannot be trusted; the pass is a full
               pass and says why

An unreadable state file never turns into a silent skip, and the saved
findings list is handed back by path so it is reused, never merged.

    python3 reflect_pass_state.py read <session.jsonl>
    python3 reflect_pass_state.py write <session.jsonl> --last-turn-index N --findings <path> --lenses Judgment Cost
    python3 reflect_pass_state.py delta <session.jsonl>
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

STATE_FILE_NAME = "reflect-pass.json"
STATE_KEYS = ("ts", "last_turn_index", "findings_path", "lenses")

NONE = "none"
STATE = "state"
UNCHECKED = "unchecked"
DELTA = "delta"
FULL = "full"

READ_EXIT = {NONE: 0, STATE: 0, UNCHECKED: 2}
DELTA_EXIT = {DELTA: 0, FULL: 1, UNCHECKED: 2}


def session_dir(transcript_path):
    """The session's own directory, the one that holds `subagents/`, for a session or subagent transcript."""
    absolute = os.path.abspath(transcript_path)
    parent = os.path.dirname(absolute)
    if os.path.basename(parent) == "subagents":
        return os.path.dirname(parent)
    return os.path.splitext(absolute)[0]


def state_path(transcript_path):
    """Where this session's pass state lives."""
    return os.path.join(session_dir(transcript_path), STATE_FILE_NAME)


def count_turns(transcript_path):
    """Distinct assistant message ids in first-seen order, with the last line each one touched.

    Returns the ordered ids, a map from id to the 1-indexed number of the last
    line carrying it, and every line that would not parse. An unparsed line
    makes the count a floor, so callers report unchecked rather than a delta.
    """
    ordered_ids = []
    last_line_by_id = {}
    unparsed_lines = []
    with open(transcript_path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError as error:
                unparsed_lines.append(f"line {number}: {error.msg}")
                continue
            if not isinstance(row, dict) or row.get("type") != "assistant":
                continue
            message = row.get("message")
            if not isinstance(message, dict):
                continue
            message_id = message.get("id")
            if message_id not in last_line_by_id:
                ordered_ids.append(message_id)
            last_line_by_id[message_id] = number
    return {
        "ids": ordered_ids,
        "last_line_by_id": last_line_by_id,
        "unparsed_lines": unparsed_lines,
    }


def read_state(transcript_path):
    """Outcome, parsed state or None, and the reason when the state cannot be trusted."""
    path = state_path(transcript_path)
    if not os.path.exists(path):
        return NONE, None, f"no state file at {path}"
    try:
        with open(path, encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        return UNCHECKED, None, f"{path} unreadable ({error.__class__.__name__}: {error})"
    if not isinstance(state, dict):
        return UNCHECKED, None, f"{path} is not a JSON object"
    missing = [key for key in STATE_KEYS if key not in state]
    if missing:
        return UNCHECKED, None, f"{path} is missing {', '.join(missing)}"
    if not isinstance(state["last_turn_index"], int) or state["last_turn_index"] < 0:
        return UNCHECKED, None, f"{path} last_turn_index must be a non-negative integer"
    if not isinstance(state["lenses"], list) or not all(isinstance(lens, str) for lens in state["lenses"]):
        return UNCHECKED, None, f"{path} lenses must be a list of names"
    if not isinstance(state["findings_path"], str) or not state["findings_path"]:
        return UNCHECKED, None, f"{path} findings_path must be a path"
    if not os.path.isfile(state["findings_path"]):
        return UNCHECKED, None, f"saved findings missing at {state['findings_path']}"
    return STATE, state, ""


def write_state(transcript_path, last_turn_index, findings_path, lenses, now=None):
    """Write the pass state beside the transcript and return its path."""
    if last_turn_index < 0:
        raise ValueError("--last-turn-index must be a non-negative integer")
    if not lenses:
        raise ValueError("--lenses needs at least one lens name")
    stamp = (now or datetime.datetime.now(datetime.timezone.utc)).isoformat(timespec="seconds")
    state = {
        "ts": stamp,
        "last_turn_index": last_turn_index,
        "findings_path": os.path.abspath(findings_path),
        "lenses": list(lenses),
    }
    path = state_path(transcript_path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return path


def delta(transcript_path):
    """Outcome plus the range the next pass reads.

    `delta` carries the first uncovered 1-indexed line, the new turn count, and
    the saved findings path. `full` carries the whole transcript's turn count
    because no state exists. `unchecked` names why the state could not be
    trusted; the transcript is read in full and that word is reported.
    """
    outcome, state, reason = read_state(transcript_path)
    try:
        counted = count_turns(transcript_path)
    except OSError as error:
        return UNCHECKED, {"reason": f"transcript unreadable ({error.__class__.__name__}: {error})"}
    total_turns = len(counted["ids"])
    if counted["unparsed_lines"]:
        unreadable = "; ".join(counted["unparsed_lines"])
        return UNCHECKED, {"reason": f"transcript has {len(counted['unparsed_lines'])} unreadable line(s): {unreadable}"}
    if outcome == UNCHECKED:
        return UNCHECKED, {"reason": reason}
    if outcome == NONE:
        return FULL, {"turns": total_turns, "reason": reason}
    covered = state["last_turn_index"]
    if covered > total_turns:
        return UNCHECKED, {
            "reason": f"state covers {covered} turns but the transcript has only {total_turns}",
        }
    if covered == 0:
        first_line = 1
    else:
        first_line = counted["last_line_by_id"][counted["ids"][covered - 1]] + 1
    return DELTA, {
        "first_line": first_line,
        "new_turns": total_turns - covered,
        "covered_turns": covered,
        "total_turns": total_turns,
        "findings_path": state["findings_path"],
        "lenses": state["lenses"],
        "ts": state["ts"],
    }


def render_read(outcome, state, reason):
    """One line for step 1: `pass-state: none`, `pass-state: <json>`, or `pass-state: unchecked <reason>`."""
    if outcome == NONE:
        return "pass-state: none"
    if outcome == UNCHECKED:
        return f"pass-state: unchecked {reason}"
    return f"pass-state: {json.dumps(state, sort_keys=True)}"


def render_delta(outcome, detail):
    """One line for step 1 naming the range the lenses read."""
    if outcome == DELTA:
        return (f"delta  first uncovered line {detail['first_line']}, {detail['new_turns']} new turn(s) "
                f"after {detail['covered_turns']} covered, findings {detail['findings_path']}, "
                f"lenses {' '.join(detail['lenses'])}")
    if outcome == FULL:
        return f"full  {detail['turns']} turn(s), {detail['reason']}"
    return f"full  unchecked {detail['reason']}"


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    read_parser = commands.add_parser("read", help="print the saved pass state for a session")
    read_parser.add_argument("transcript")
    write_parser = commands.add_parser("write", help="save the pass state after synthesis")
    write_parser.add_argument("transcript")
    write_parser.add_argument("--last-turn-index", type=int, required=True)
    write_parser.add_argument("--findings", required=True)
    write_parser.add_argument("--lenses", nargs="+", required=True)
    delta_parser = commands.add_parser("delta", help="print the uncovered range for the next pass")
    delta_parser.add_argument("transcript")
    for sub_parser in (read_parser, write_parser, delta_parser):
        sub_parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    if args.command == "read":
        outcome, state, reason = read_state(args.transcript)
        if args.json:
            print(json.dumps({"outcome": outcome, "state": state, "reason": reason}, sort_keys=True))
        else:
            print(render_read(outcome, state, reason))
        return READ_EXIT[outcome]

    if args.command == "write":
        try:
            path = write_state(args.transcript, args.last_turn_index, args.findings, args.lenses)
        except ValueError as error:
            print(f"pass-state: not written: {error}", file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps({"outcome": "written", "path": path}, sort_keys=True))
        else:
            print(f"pass-state: written {path}")
        return 0

    outcome, detail = delta(args.transcript)
    if args.json:
        print(json.dumps({"outcome": outcome, **detail}, sort_keys=True))
    else:
        print(render_delta(outcome, detail))
    return DELTA_EXIT[outcome]


if __name__ == "__main__":
    sys.exit(main())
