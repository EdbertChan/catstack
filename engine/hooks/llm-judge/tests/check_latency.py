#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import time

LIB_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, LIB_DIR)

import inbox  # noqa: E402


HISTORY_ROWS = 400_000
INVOCATIONS = 4
BUDGET_SECONDS = 5.0


def main() -> int:
    with tempfile.TemporaryDirectory() as work:
        transcript = os.path.join(work, "session.jsonl")
        with open(transcript, "w", encoding="utf-8") as handle:
            for index in range(HISTORY_ROWS):
                handle.write(json.dumps({
                    "type": "assistant",
                    "message": {"role": "assistant", "content": f"historical reply {index}"},
                }) + "\n")
            handle.write(json.dumps({
                "type": "user",
                "message": {"role": "user", "content": "current request"},
            }) + "\n")
            handle.write(json.dumps({
                "type": "assistant",
                "message": {"role": "assistant", "content": "probably done"},
            }) + "\n")

        started = time.perf_counter()
        for invocation in range(1, INVOCATIONS + 1):
            invocation_started = time.perf_counter()
            result = inbox.last_turn(transcript)
            elapsed = time.perf_counter() - invocation_started
            print(f"llm-judge.last_turn[{invocation}] elapsed={elapsed:.3f}s")
            if result != ("current request", "probably done") or elapsed >= BUDGET_SECONDS:
                return 1
        total = time.perf_counter() - started
        print(f"cat-mode hook latency total elapsed={total:.3f}s budget={BUDGET_SECONDS:.1f}s")
        return 0 if total < BUDGET_SECONDS else 1


if __name__ == "__main__":
    raise SystemExit(main())
