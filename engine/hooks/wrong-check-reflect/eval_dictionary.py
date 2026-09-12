#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys

LLM_JUDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)

import judge  # noqa: E402
import phrases  # noqa: E402

HIT_TEXT = "Correction: the file I pointed you to earlier is not the one in use; the real one is src/b.py."
CASES = (
    (HIT_TEXT, True),
    ("You're right. Let's go with option B.", False),
    ("I double-checked my earlier count and it holds; nothing in it was wrong.", False),
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate the wrong-check-reflect phrase dictionary against the real llm-judge runner.",
        epilog="--runner-env note: set CATSTACK_LLM_JUDGE_RUNNERS to choose the model command; without it this calls a real model.",
    )
    parser.add_argument("--runner-env", action="store_true", help="print the runner environment note and exit")
    args = parser.parse_args(argv)
    if args.runner_env:
        print("Set CATSTACK_LLM_JUDGE_RUNNERS to choose the model command; without it this calls a real model.")
        return 0
    dictionary = phrases.load("wrong-check-reflect")
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
