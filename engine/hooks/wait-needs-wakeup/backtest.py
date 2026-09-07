#!/usr/bin/env python3
"""Replay the wait-needs-wakeup rules over a Claude Code transcript.

    python3 engine/hooks/wait-needs-wakeup/backtest.py TRANSCRIPT.jsonl
    python3 engine/hooks/wait-needs-wakeup/backtest.py --fixtures

Transcript mode prints how many Bash commands were foreground polls the
PreToolUse half would have blocked, and how many end-of-turn replies the
Stop half would have blocked (wait language with no ETA or no wakeup).
Fixture mode replays tests/fixtures/*.json and prints blocked/total per
file; the *_fires files are the incident, the *_silent files are the
corrected forms and must come out 0.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import detect  # noqa: E402


def _final_reply_indexes(lines: list[dict]) -> list[int]:
    """Assistant text lines that end a response: the next user/assistant
    line is not a tool_result and not another assistant block."""
    out: list[int] = []
    for i, data in enumerate(lines):
        if data.get("type") != "assistant" or not detect._text_content(data).strip():
            continue
        nxt = next((d for d in lines[i + 1:] if d.get("type") in ("user", "assistant")), None)
        if nxt is None:
            out.append(i)
            continue
        if nxt.get("type") == "assistant":
            continue
        content = (nxt.get("message") or {}).get("content")
        if isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            continue
        out.append(i)
    return out


def run_transcript(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        lines = detect.parse_lines(handle)
    report = {
        "path": path, "bash_commands": 0, "poll_blocked": 0, "poll_details": [],
        "final_replies": 0, "wait_replies": 0, "reply_blocked": 0, "reply_details": [],
    }
    for i, data in enumerate(lines):
        for block in detect._tool_uses(data):
            if block.get("name") != "Bash":
                continue
            inp = block.get("input") or {}
            command = inp.get("command")
            if not isinstance(command, str):
                continue
            report["bash_commands"] += 1
            reason = detect.classify_command(command, bool(inp.get("run_in_background")))
            if reason:
                report["poll_blocked"] += 1
                report["poll_details"].append((i, reason, command.strip().splitlines()[0][:90]))
    seen: set[str] = set()
    for i in _final_reply_indexes(lines):
        text = detect._text_content(lines[i])
        if text in seen:
            continue
        seen.add(text)
        report["final_replies"] += 1
        if not detect.is_wait_reply(text):
            continue
        report["wait_replies"] += 1
        verdict = detect.decide_stop_from_lines(text, lines[: i + 1])
        if verdict:
            report["reply_blocked"] += 1
            report["reply_details"].append((i, text.strip().replace("\n", " ")[:110]))
    return report


def run_fixtures(fixtures_dir: str) -> dict:
    counts: dict = {}
    for name in sorted(os.listdir(fixtures_dir)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(fixtures_dir, name), encoding="utf-8") as handle:
            cases = json.load(handle)
        blocked = 0
        for case in cases:
            if "command" in case:
                hit = detect.classify_command(case["command"], case.get("run_in_background", False))
            else:
                lines = detect.parse_lines(json.dumps(line) for line in case.get("transcript", []))
                hit = detect.decide_stop_from_lines(case["reply"], lines)
            blocked += 1 if hit else 0
        counts[name] = {"total": len(cases), "blocked": blocked}
    return counts


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 2
    if argv[0] == "--fixtures":
        counts = run_fixtures(os.path.join(HERE, "tests", "fixtures"))
        for name, c in counts.items():
            print(f"{name}: {c['blocked']}/{c['total']} would block")
        return 0
    report = run_transcript(argv[0])
    print(f"wait-needs-wakeup backtest: {report['path']}")
    print(f"bash commands scanned: {report['bash_commands']}")
    print(f"  poll commands that would block (PreToolUse): {report['poll_blocked']}")
    for line, reason, head in report["poll_details"]:
        print(f"    line {line}: {reason}: {head}")
    print(f"final assistant replies scanned: {report['final_replies']}")
    print(f"  replies with wait language: {report['wait_replies']}")
    print(f"  replies that would block (Stop): {report['reply_blocked']}")
    for line, head in report["reply_details"]:
        print(f"    line {line}: {head}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
