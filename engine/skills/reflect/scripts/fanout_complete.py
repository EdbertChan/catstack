#!/usr/bin/env python3
"""Decide whether a reflect fan-out returned enough to apply its findings.

Step 5 of reflect applies Accepted findings. It may start only when every
reviewer lens from step 3 reported. A lens that died -- rate limit, crashed
worktree, killed agent -- is not a lens that passed, so a pass missing one is
partial and says so rather than applying what the survivors happened to find.

Three outcomes, because a check that could not run is not a pass:

    complete    every expected lens returned; apply is allowed
    incomplete  at least one expected lens did not return; apply is refused
    unchecked   the expected set is unknown, so completeness cannot be judged

`unchecked` is not `complete`. It exits non-zero like `incomplete`, because a
fan-out nobody can account for is exactly the case this exists to catch.

Each lens also carries a turn target taken from measured passes and an output
cap, held in `LENS_TURN_TARGETS` and `LENS_OUTPUT_WORD_CAP`. `--targets`
records the target for every lens in the expected set, and `--turns
<Lens>=<agent jsonl>` counts that lens's real assistant turns so the step-7
cost line reads target against actual. A lens over its target is reported,
never cut off, and never changes the exit code: completeness is the only thing
this module gates on.

    python3 fanout_complete.py --expected a b c --returned a b
    python3 fanout_complete.py --manifest run.json
    python3 fanout_complete.py --expected a b --returned a b --json
    python3 fanout_complete.py --expected Cost --returned Cost --targets
    python3 fanout_complete.py --expected Cost --returned Cost --turns Cost=agent-1.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys

COMPLETE = "complete"
INCOMPLETE = "incomplete"
UNCHECKED = "unchecked"

EXIT = {COMPLETE: 0, INCOMPLETE: 1, UNCHECKED: 2}

ALL_LENSES = ("Judgment", "Tooling", "Cost", "History", "Divergent", "Frustration")
REQUIRED_LENSES = ("Judgment", "Cost", "Frustration")

LENS_TURN_TARGETS = {
    "Judgment": 10,
    "Tooling": 10,
    "Cost": 6,
    "History": 12,
    "Divergent": 8,
    "Frustration": 8,
}

LENS_OUTPUT_WORD_CAP = 400

TARGET_MET = "ok"
TARGET_OVER = "over"


def lens_plan(session_tokens, budget=None):
    """Return the deterministic step-3 lens plan for a measured session.

    ``budget=None`` is the feature-disabled state and deliberately returns the
    historical full fan-out. A reduced plan is complete when its returned
    expected set is recorded with this module's ``verdict`` function.
    """
    if budget is None or session_tokens <= budget:
        return {
            "expected": list(ALL_LENSES),
            "omitted": [],
            "reduced": False,
        }
    return {
        "expected": list(REQUIRED_LENSES),
        "omitted": [lens for lens in ALL_LENSES if lens not in REQUIRED_LENSES],
        "reduced": True,
    }


def lens_plan_from_env(session_tokens, environ=None):
    """Read the optional token budget and select the step-3 lens plan."""
    value = (environ or os.environ).get("CATSTACK_REFLECT_LENS_BUDGET")
    if value is None:
        return lens_plan(session_tokens)
    try:
        budget = int(value)
    except ValueError as exc:
        raise ValueError("CATSTACK_REFLECT_LENS_BUDGET must be an integer") from exc
    if budget <= 0:
        raise ValueError("CATSTACK_REFLECT_LENS_BUDGET must be positive")
    return lens_plan(session_tokens, budget)


def reduced_status(session_tokens, budget, plan):
    """Name every omitted lens for the step-4 synthesis prompt."""
    if not plan["reduced"]:
        return ""
    ran = ", ".join(plan["expected"])
    omitted = ", ".join(plan["omitted"])
    return f"reduced reflect: ran {ran}, omitted {omitted} (session {session_tokens} tokens over budget {budget})"


def verdict(expected, returned):
    """Outcome plus the lenses missing from this fan-out.

    An empty or absent expected set is `unchecked`: nothing pins what the pass
    was supposed to cover, so a returned set cannot be called complete. A
    returned lens outside the expected set does not make the pass complete and
    is reported so a mislabelled lens is visible rather than silently counted.
    """
    if not expected:
        return UNCHECKED, [], []
    missing = sorted(set(expected) - set(returned))
    unexpected = sorted(set(returned) - set(expected))
    return (COMPLETE if not missing else INCOMPLETE), missing, unexpected


def count_assistant_turns(agent_transcript_path):
    """Count one agent transcript's assistant turns by distinct message id.

    Returns the count plus every line that would not parse, named with its
    number and the decoder's reason. A line nobody could read means the count
    is a floor, so the caller reports the lens as unchecked instead of as a
    lens that met its target.
    """
    message_ids = set()
    unparsed_lines = []
    with open(agent_transcript_path, encoding="utf-8") as handle:
        for number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if stripped:
                try:
                    row = json.loads(stripped)
                except json.JSONDecodeError as error:
                    unparsed_lines.append(f"line {number}: {error.msg}")
                    row = None
                is_assistant = isinstance(row, dict) and row.get("type") == "assistant"
                message = row.get("message") if is_assistant else None
                if isinstance(message, dict):
                    message_ids.add(message.get("id"))
    return {"turns": len(message_ids), "unparsed_lines": unparsed_lines}


def lens_turn_report(expected, transcripts=None):
    """Turn target against measured turns for every lens in the expected set.

    Three outcomes per lens, because a lens whose transcript could not be read
    is not a lens that met its target: `ok`, `over`, `unchecked`. An overrun is
    reported and never cut off, and neither an overrun nor an `unchecked` lens
    moves this module's exit code, which answers only to completeness.
    """
    transcripts = transcripts or {}
    rows = []
    for lens in dict.fromkeys(expected):
        target = LENS_TURN_TARGETS.get(lens)
        transcript_path = transcripts.get(lens)
        actual = None
        unchecked = None
        if transcript_path is None:
            unchecked = f"no agent transcript given for {lens}"
        else:
            try:
                counted = count_assistant_turns(transcript_path)
            except OSError as error:
                unchecked = f"{lens} transcript unreadable ({error.__class__.__name__}: {error})"
            else:
                actual = counted["turns"]
                if counted["unparsed_lines"]:
                    unchecked = (f"{lens} transcript has {len(counted['unparsed_lines'])} "
                                 f"unreadable line(s), so {actual} turns is a floor: "
                                 f"{'; '.join(counted['unparsed_lines'])}")
        if target is None:
            unchecked = f"no measured turn target for {lens}"
        if unchecked:
            status = UNCHECKED
        elif actual > target:
            status = TARGET_OVER
        else:
            status = TARGET_MET
        rows.append({
            "lens": lens, "target": target, "actual": actual,
            "status": status, "unchecked": unchecked,
            "transcript": transcript_path,
        })
    return rows


def render_turn_targets(rows):
    """Render the target-against-actual line that sits beside the step-7 cost line.

    With no lens transcript supplied this is the step-3 recording form: the
    target each launched lens was given. With transcripts it is the step-7
    form: actual turns against that target, per lens.
    """
    if not rows:
        return ("Lens turn targets: unchecked  no expected lens set given; "
                "record the launched lenses with --expected")
    if not any(row["transcript"] for row in rows):
        recorded = ", ".join(
            f"{row['lens']} {row['target']}" if row["target"] is not None
            else f"{row['lens']} unchecked ({row['unchecked']})"
            for row in rows
        )
        return (f"Lens turn targets recorded (output cap ~{LENS_OUTPUT_WORD_CAP} "
                f"words each): {recorded}")
    parts = []
    for row in rows:
        if row["status"] == UNCHECKED:
            parts.append(f"{row['lens']} unchecked ({row['unchecked']})")
        else:
            parts.append(f"{row['lens']} {row['actual']}/{row['target']} {row['status']}")
    return (f"Lens turn targets, actual/target (output cap ~{LENS_OUTPUT_WORD_CAP} "
            f"words each): {', '.join(parts)}")


def parse_turn_arguments(values):
    """Map each `--turns <Lens>=<path>` pair to that lens's agent transcript."""
    transcripts = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"--turns takes <Lens>=<path> pairs, got {value!r}")
        lens, transcript_path = value.split("=", 1)
        transcripts[lens] = transcript_path
    return transcripts


def _from_manifest(path):
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("manifest must be a JSON object")
    return data.get("expected") or [], data.get("returned") or []


def render(outcome, missing, unexpected):
    lines = []
    if outcome == COMPLETE:
        lines.append("complete  every expected lens returned; apply may proceed")
    elif outcome == INCOMPLETE:
        lines.append(f"incomplete  {len(missing)} lens(es) did not return: {', '.join(missing)}")
        lines.append("            re-run them, or report the pass as partial and name them.")
    else:
        lines.append("unchecked  no expected lens set given; completeness cannot be judged")
        lines.append("            name the lenses step 3 launched, then re-run this.")
    if unexpected:
        lines.append(f"            returned but not expected: {', '.join(unexpected)}")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--expected", nargs="*", default=None, help="lens names step 3 launched")
    ap.add_argument("--returned", nargs="*", default=None, help="lens names that reported")
    ap.add_argument("--manifest", help="JSON object with 'expected' and 'returned' lists")
    ap.add_argument("--json", action="store_true", help="machine-readable verdict")
    ap.add_argument("--targets", action="store_true", help="record each expected lens's turn target")
    ap.add_argument("--turns", nargs="*", default=None, help="<Lens>=<agent jsonl> pairs to count actual turns")
    args = ap.parse_args(argv)

    if args.manifest:
        expected, returned = _from_manifest(args.manifest)
    else:
        expected, returned = args.expected or [], args.returned or []

    outcome, missing, unexpected = verdict(expected, returned)
    show_targets = args.targets or bool(args.turns)
    turn_rows = lens_turn_report(expected, parse_turn_arguments(args.turns)) if show_targets else []
    if args.json:
        payload = {
            "outcome": outcome, "missing": missing,
            "unexpected": unexpected, "expected": sorted(set(expected)),
            "returned": sorted(set(returned)),
        }
        if show_targets:
            payload["turn_targets"] = turn_rows
        print(json.dumps(payload, indent=2))
    else:
        print(render(outcome, missing, unexpected))
        if show_targets:
            print(render_turn_targets(turn_rows))
    return EXIT[outcome]


if __name__ == "__main__":
    sys.exit(main())
