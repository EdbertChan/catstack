#!/usr/bin/env python3
"""Apply an isolated Muse judge's verdict to a diu-stop plain-words request.

Usage:
  muse_judge_apply.py <request-path> [<verdict-json-or-raw-text>]

<request-path> is the JUDGE_REQUEST file emitted by muse_self_review.py.
The verdict is the isolated judge subagent's output: ideally one line of
JSON like {"match": true, "category": "...", "closest": "..."}; raw text is
also accepted and the last JSON object on a line is extracted, exactly the
way llm-judge/judge.py reads runner output.

Semantics are identical to the Claude harness: judge.verdict() decides hit /
clean from hit_if_all_true, and plain_words.message_for() renders the diu
message. Exit 2 on hit (revise the draft, then re-run the review), 0 on
clean or unchecked (fail open, like the harness). Writes <request>.verdict.json,
deletes the handled request, and appends a drift-watch-compatible ledger row.
"""
from __future__ import annotations

import json
import os
import sys
import time

CACHE = os.path.join(os.path.expanduser("~"), ".cache")
LEDGER = os.path.join(CACHE, "catstack-muse-review", "ledger.jsonl")
HOOKS_DIR = os.environ.get(
    "CATSTACK_HOOKS_DIR",
    os.path.join(os.path.expanduser("~"), "workspace", "catstack", "engine", "hooks"),
)
JUDGE_DIR = os.path.join(HOOKS_DIR, "llm-judge")
DIU_STOP_DIR = os.path.join(HOOKS_DIR, "diu-stop")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    request_path = sys.argv[1]
    raw = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()

    with open(request_path, encoding="utf-8") as handle:
        request = json.load(handle)

    if JUDGE_DIR not in sys.path:
        sys.path.insert(0, JUDGE_DIR)
    if DIU_STOP_DIR not in sys.path:
        sys.path.insert(0, DIU_STOP_DIR)
    import judge  # noqa: E402
    import plain_words  # noqa: E402

    started = time.time()
    answer = judge.last_json_object(raw or "")
    if isinstance(answer, dict):
        result = {
            "outcome": "answered",
            "runner": "muse-judge",
            "answer": answer,
            "attempts": [],
        }
    else:
        result = {
            "outcome": "unanswered",
            "runner": "muse-judge",
            "answer": None,
            "attempts": [{"runner": "muse-judge",
                          "reason": "no JSON object in judge output"}],
        }
    job = {
        "id": request["id"],
        "hook": request.get("hook", "diu-plain-words"),
        "transcript": request.get("transcript", ""),
        "hit_if_all_true": request.get("hit_if_all_true", ["match"]),
        "on_hit": request.get("on_hit", ""),
    }
    verdict = judge.verdict(job, result)
    verdict["raw_output"] = (raw or "")[:2000]
    outcome = verdict.get("outcome")

    verdict_path = request_path + ".verdict.json"
    with open(verdict_path, "w", encoding="utf-8") as handle:
        json.dump(verdict, handle, ensure_ascii=False, indent=2)
    try:
        os.remove(request_path)
    except OSError:
        pass

    session_id = request.get("session_id", "muse-self-review")
    ms = int((time.time() - started) * 1000)
    if outcome == "hit":
        message = plain_words.message_for(verdict, request.get("reply", ""))
        print(f"judge verdict: HIT ({verdict.get('reason')})")
        if message:
            print(message)
        code, stops = 2, 1
    elif outcome == "clean":
        print(f"judge verdict: clean ({verdict.get('reason')})")
        code, stops = 0, 0
    else:
        print(f"judge verdict: {outcome} ({verdict.get('reason')}); unchecked")
        code, stops = 0, 0

    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": session_id,
            "event": "judge_verdict",
            "hook": job["hook"],
            "outcome": outcome,
            "checks": 1,
            "stops": stops,
            "warns": 0,
            "exit": code,
            "ms": ms,
        }) + "\n")
    if code == 2:
        print("STOP -- reword the flagged wording in everyday words, then "
              "re-run the review.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
