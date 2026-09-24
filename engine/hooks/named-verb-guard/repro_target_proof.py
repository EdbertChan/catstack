#!/usr/bin/env python3
"""Repro: does named-verb-guard ask the judge about target/outcome proof?

Each fixture in tests/fixtures/target_proof/ is one turn: the user's message,
the tool calls with their results, and the reply. It is written to a real
transcript file, read back with detect.read_transcript, and passed to
detect.pending_requests. A `fire` fixture passes when the target-proof request
is sent to the judge; a `clean` fixture passes when it is not.

Run: python3 engine/hooks/named-verb-guard/repro_target_proof.py
Exit 0 only when every fixture passes. No model is called.
"""
from __future__ import annotations

import glob
import json
import os
import sys
import tempfile

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURES = os.path.join(HOOK_DIR, "tests", "fixtures", "target_proof")
sys.path.insert(0, HOOK_DIR)

import detect  # noqa: E402


def write_transcript(folder: str, fixture: dict) -> str:
    path = os.path.join(folder, "session.jsonl")
    with open(path, "w", encoding="utf-8") as handle:
        for text in fixture["user"]:
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": text}}) + "\n")
        for index, step in enumerate(fixture["turn"]):
            tool_id = f"toolu_{index}"
            handle.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                {"type": "tool_use", "id": tool_id, "name": step["tool"], "input": step["input"]}]}}) + "\n")
            handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": step["result"]}]}}) + "\n")
    return path


def run(path: str) -> tuple[bool, str]:
    with open(path, encoding="utf-8") as handle:
        fixture = json.load(handle)
    with tempfile.TemporaryDirectory() as folder:
        humans, tool_uses = detect.read_transcript(write_transcript(folder, fixture))
    sent = [checker for checker, _ in detect.pending_requests(fixture["reply"], humans, tool_uses)]
    checker = getattr(detect, "TARGET_PROOF_REQUEST", None)
    fired = checker is not None and checker in sent
    ok = fired is (fixture["expect"] == "fire")
    gaps = detect.target_proof_gaps(fixture["reply"], tool_uses) if hasattr(detect, "target_proof_gaps") else []
    detail = f"expect={fixture['expect']} fired={fired} sent={sent} gaps={gaps}"
    return ok, detail


def main() -> int:
    paths = sorted(glob.glob(os.path.join(FIXTURES, "*.json")))
    if not paths:
        print(f"UNCHECKED no fixtures under {FIXTURES}")
        return 2
    failed = 0
    for path in paths:
        ok, detail = run(path)
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}\t{os.path.basename(path)}\t{detail}")
    print(f"{len(paths) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
