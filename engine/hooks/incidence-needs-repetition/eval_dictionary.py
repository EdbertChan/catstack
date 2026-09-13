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
    ("The test passes on every attempt now; it never fails anymore.", True),
    ("Understood. I'll re-check the lint output every time you push a commit.", False),
)


def main() -> int:
    dictionary = phrases.load("incidence-needs-repetition")
    ok = True
    for text, expected in CASES:
        result = judge.ask(phrases.prompt(dictionary, text))
        answer = result.get("answer") if result.get("outcome") == "answered" else None
        matched = isinstance(answer, dict) and answer.get("match") is True
        print(f"{text}\t{json.dumps(answer, sort_keys=True)}")
        if matched is not expected:
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
