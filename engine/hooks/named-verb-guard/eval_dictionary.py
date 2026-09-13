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

SEP = detect.MESSAGE_SEPARATOR

CASES = (
    (detect.PROOF_DEMAND, "Did you actually deploy it, or just say so?" + SEP + "You said that before. Actually show me it's live this time.", True),
    (detect.PROOF_DEMAND, "Update the changelog." + SEP + "Are you sure that's the right version number?", False),
    (detect.PROVE_REQUEST, "before touching the code, reproduce the timeout on your machine", True),
    (detect.PROVE_REQUEST, "the integration tests take forever on CI", False),
    (detect.SHOW_REQUEST, "pull up the latest logs from the worker for me", True),
    (detect.SHOW_REQUEST, "that command showed nothing interesting last time", False),
    (detect.SHOW_REQUEST, "can you re-run the flaky test one more time", False),
    (detect.PROVE_REQUEST, "can you re-run the flaky test one more time", True),
    (detect.DELETE_REQUEST, "nuke the stale feature branches", True),
    (detect.DELETE_REQUEST, "is it safe to remove that file later?", False),
    (detect.STOP_REQUEST, "whoa whoa, cut it out, stop changing files", True),
    (detect.STOP_REQUEST, "it keeps going until the queue is empty, which is fine", False),
)


def main() -> int:
    ok = True
    for checker, text, expected in CASES:
        dictionary = phrases.load(checker)
        result = judge.ask(phrases.prompt(dictionary, text))
        answer = result.get("answer") if result.get("outcome") == "answered" else None
        matched = isinstance(answer, dict) and answer.get("match") is True
        verdict = "ok" if matched is expected else "WRONG"
        print(f"{verdict}\t{checker}\texpected={expected}\t{text!r}\t{json.dumps(answer, sort_keys=True)}")
        if matched is not expected:
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
