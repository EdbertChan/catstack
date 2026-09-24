#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HOOK_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(HOOK_DIR), "llm-judge"))

import detect  # noqa: E402
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
    ok = True
    dictionary = phrases.load(detect.CHECKER)
    for text, expected in CASES:
        result = judge.ask(phrases.prompt(dictionary, text))
        answer = result.get("answer") if result.get("outcome") == "answered" else None
        matched = isinstance(answer, dict) and answer.get("match") is True
        if answer is None:
            verdict = "UNCHECKED"
            ok = False
        else:
            verdict = "ok" if matched is expected else "WRONG"
            ok = ok and matched is expected
        print(f"{verdict}\texpected={expected}\t{text!r}\t{json.dumps(answer, sort_keys=True)}\t{result.get('outcome')}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
