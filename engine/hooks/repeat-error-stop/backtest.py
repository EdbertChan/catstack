#!/usr/bin/env python3
"""Replay Claude Code transcripts through the repeat-error-stop state machine.

For every session it reports each point where the hook would have fired
(3rd identical failure signature since the last human prompt; a failure is a
tool_result with is_error, matching Claude Code's PostToolUseFailure event) and what actually
happened afterwards in the real session:

  saved     identical errors that came after the block point (the thrash the
            hook would have cut off)
  next_try  outcome of the next real run of a command that produced the error:
            "ok" means the retry succeeded, so the block was premature;
            "same" means it failed the same way again; "none" = never re-run

Usage: backtest.py [--json OUT] <transcript.jsonl|dir> ...
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import detect  # noqa: E402


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _is_human_prompt(obj: dict) -> bool:
    if obj.get("type") != "user" or obj.get("isMeta") or obj.get("isSidechain"):
        return False
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
        return False
    text = _text(content).strip()
    if not text or text.startswith("<") or text.startswith("[Request interrupted"):
        return False
    return not detect.is_automated_prompt(text)


def replay(path: str, threshold: int = detect.THRESHOLD) -> dict:
    pending: dict[str, dict] = {}
    counts: dict[str, dict] = {}
    events: list[dict] = []
    open_blocks: list[dict] = []
    n_tool = 0
    n_err = 0
    n_prompts = 0
    edit_epoch = 0
    with open(path, errors="ignore") as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _is_human_prompt(obj):
                n_prompts += 1
                counts = {}
                open_blocks = []
                edit_epoch = 0
                continue
            msg = obj.get("message") or {}
            if obj.get("type") == "assistant":
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        pending[b.get("id")] = {"name": b.get("name"), "input": b.get("input") or {}, "ts": obj.get("timestamp")}
            elif obj.get("type") == "user":
                for b in msg.get("content") or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_result"):
                        continue
                    call = pending.pop(b.get("tool_use_id"), None)
                    if not call:
                        continue
                    n_tool += 1
                    text = _text(b.get("content"))
                    if b.get("is_error"):
                        payload = {"hook_event_name": "PostToolUseFailure", "tool_name": call["name"], "tool_input": call["input"], "error": text or "tool failed"}
                    else:
                        payload = {"hook_event_name": "PostToolUse", "tool_name": call["name"], "tool_input": call["input"], "tool_response": text}
                    cmd = detect.command_signature(payload)
                    failure = detect.failure_text(payload)
                    sig = detect.error_signature(failure, cmd) if failure is not None else None
                    for blk in open_blocks:
                        if cmd and cmd in blk["commands"] and blk["next_try"] == "none":
                            blk["next_try"] = "same" if (sig and sig[0] == blk["sig"]) else "ok"
                        if sig and sig[0] == blk["sig"]:
                            blk["saved"] += 1
                    if sig is None:
                        if detect.RESET_ON_EDIT and call["name"] in detect.EDIT_TOOLS and not b.get("is_error"):
                            edit_epoch += 1
                        continue
                    n_err += 1
                    digest, sample = sig
                    entry = counts.setdefault(digest, {"count": 0, "commands": set(), "epoch": edit_epoch})
                    if entry["epoch"] != edit_epoch:
                        entry["count"] = 0
                        entry["commands"] = set()
                        entry["epoch"] = edit_epoch
                    entry["count"] += 1
                    if cmd:
                        entry["commands"].add(cmd)
                    if entry["count"] == threshold:
                        blk = {"ts": call["ts"], "tool": call["name"], "sig": digest, "sample": sample[:200],
                               "command": str(call["input"].get("command") or "")[:160], "commands": set(entry["commands"]),
                               "saved": 0, "next_try": "none"}
                        open_blocks.append(blk)
                        events.append(blk)
    for e in events:
        e["commands"] = sorted(e["commands"])[:5]
    return {"file": os.path.basename(path), "tool_results": n_tool, "error_results": n_err, "human_prompts": n_prompts, "blocks": events}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--json", dest="json_out")
    ap.add_argument("--threshold", type=int, default=detect.THRESHOLD)
    args = ap.parse_args(argv)
    files: list[str] = []
    for p in args.paths:
        files.extend(sorted(glob.glob(os.path.join(p, "*.jsonl"))) if os.path.isdir(p) else [p])
    reports = [replay(f, args.threshold) for f in files]
    blocks = [b for r in reports for b in r["blocks"]]
    saved = sum(b["saved"] for b in blocks)
    premature = [b for b in blocks if b["next_try"] == "ok"]
    print(f"sessions={len(reports)} tool_results={sum(r['tool_results'] for r in reports)} "
          f"error_results={sum(r['error_results'] for r in reports)} blocks={len(blocks)} "
          f"later_identical_errors_saved={saved} premature(next retry succeeded)={len(premature)}")
    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump(reports, f, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
