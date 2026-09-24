#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

LLM_JUDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)

import judge  # noqa: E402
import phrases  # noqa: E402

CASES = (
    ("ok ran it on my laptop: $ make migrate\nApplying 0042_add_index... OK", True),
    ("I went ahead and edited the Dockerfile myself to pin node 20, rebuild now", True),
    ("found it on the docs site, the env var is DATABASE_URL not DB_URL", True),
    ("can you run make migrate and tell me what it prints?", False),
    ("I entered the 2FA code on my phone, go ahead", False),
    ("the migration printed an error last week, not sure why", False),
)


def main() -> int:
    dictionary = phrases.load("user-did-it")
    ok = True
    unchecked = False
    for text, expected in CASES:
        result = judge.ask(phrases.prompt(dictionary, text))
        if result.get("outcome") != "answered":
            print(f"unchecked\texpected={expected}\toutcome={result.get('outcome')}\t{text!r}")
            unchecked = True
            continue
        answer = result.get("answer")
        matched = isinstance(answer, dict) and answer.get("match") is True
        verdict = "ok" if matched is expected else "WRONG"
        print(f"{verdict}\texpected={expected}\t{text!r}\t{json.dumps(answer, sort_keys=True)}")
        if matched is not expected:
            ok = False
    if not ok:
        return 1
    return 2 if unchecked else 0


if __name__ == "__main__":
    raise SystemExit(main())
