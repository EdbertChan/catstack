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
    unchecked = False
    for text, expected in CASES:
        result = judge.ask(phrases.prompt(dictionary, text))
        if result.get("outcome") != "answered":
            print(f"unchecked\toutcome={result.get('outcome')}\t{text}")
            unchecked = True
            continue
        answer = result.get("answer")
        matched = isinstance(answer, dict) and answer.get("match") is True
        print(f"{text}\t{json.dumps(answer, sort_keys=True)}")
        if matched is not expected:
            ok = False
    if not ok:
        return 1
    return 2 if unchecked else 0


if __name__ == "__main__":
    raise SystemExit(main())
