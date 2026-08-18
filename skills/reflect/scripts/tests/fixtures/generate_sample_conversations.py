#!/usr/bin/env python3
"""Regenerate sample Claude Code conversation JSONL fixtures.

Run from repo root:
    python3 skills/reflect/scripts/tests/fixtures/generate_sample_conversations.py
"""
import json
import os

OUT = os.path.dirname(os.path.abspath(__file__))


def usage(inp=100, out=50, cr=5000, cc=0):
    return {
        "input_tokens": inp,
        "output_tokens": out,
        "cache_read_input_tokens": cr,
        "cache_creation_input_tokens": cc,
    }


def user_text(text, uid):
    return {"type": "user", "uuid": uid, "message": {"role": "user", "content": text}}


def assistant_blocks(mid, uuid, blocks, u, model="claude-sonnet-5"):
    """One JSONL line per content block, same message.id (real Claude Code shape)."""
    lines = []
    for i, block in enumerate(blocks):
        lines.append({
            "type": "assistant",
            "uuid": f"{uuid}-{i}",
            "message": {"id": mid, "model": model, "usage": u, "content": [block]},
        })
    return lines


def tool_result(tid, content, is_error=False):
    return {
        "type": "user",
        "uuid": f"tr-{tid}",
        "message": {
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tid,
                "is_error": is_error,
                "content": content,
            }],
        },
    }


def write(name, lines):
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        for d in lines:
            f.write(json.dumps(d) + "\n")
    print(f"wrote {path} ({len(lines)} lines)")


def build_clean():
    clean = []
    clean.append(user_text("Fix the off-by-one in parse_args.", "u0"))
    # Single turn: Read + Edit together so it is not a lookup-only (model-tier) turn.
    u1 = usage(inp=200, out=80, cr=40_000, cc=2_000)
    clean += assistant_blocks("msg_clean_1", "a1", [
        {"type": "thinking", "thinking": "Need to read parse_args and fix the bound."},
        {"type": "text", "text": "I'll read the helper and patch the bound check."},
        {"type": "tool_use", "id": "t_read1", "name": "Read",
         "input": {"file_path": "/repo/src/parse_args.py", "offset": 1, "limit": 80}},
        {"type": "tool_use", "id": "t_edit1", "name": "Edit",
         "input": {"file_path": "/repo/src/parse_args.py",
                   "old_string": "return argv[1]", "new_string": "return argv[1:]"}},
    ], u1)
    clean.append(tool_result("t_read1", "def parse_args(argv):\n    return argv[1]\n"))
    clean.append(tool_result("t_edit1", "ok"))
    u3 = usage(inp=230, out=40, cr=43_000, cc=0)
    clean += assistant_blocks("msg_clean_3", "a3", [
        {"type": "tool_use", "id": "t_test1", "name": "Bash",
         "input": {"command": "pytest -q tests/test_parse_args.py"}},
    ], u3)
    clean.append(tool_result("t_test1", "1 passed"))
    clean += assistant_blocks("msg_clean_4", "a4", [
        {"type": "text", "text": "Fixed. pytest passes."},
    ], usage(inp=240, out=20, cr=44_000, cc=0))
    write("clean_efficient_session.jsonl", clean)


def build_thrash():
    thrash = []
    thrash.append(user_text("The login test is flaky — keep fixing until green.", "u0"))
    # A thrashing session frustrates its user — the frustration-signals flag
    # must fire on this fixture (allcaps + told-you + ??? + a verbatim repeat).
    thrash.append(user_text("THE LOGIN TEST IS STILL BROKEN. I TOLD YOU TO FIX IT. WHY IS THIS STILL FAILING???", "u1"))
    thrash.append(user_text("fix the login test now please", "u2"))
    thrash.append(user_text("fix the login test now please", "u3"))
    for i, cc in enumerate([1000, 1200, 1100]):
        thrash += assistant_blocks(f"msg_warm_{i}", f"warm{i}", [
            {"type": "text", "text": f"Warming context {i}."},
        ], usage(inp=50, out=10, cr=100, cc=cc))
    thrash += assistant_blocks("msg_spike", "spike", [
        {"type": "text", "text": "Context rebuilt after compaction."},
    ], usage(inp=50, out=10, cr=0, cc=100_000))
    thrash += assistant_blocks("msg_lookup_1", "lk1", [
        {"type": "tool_use", "id": "t_grep1", "name": "Grep",
         "input": {"pattern": "login", "path": "/repo"}},
    ], usage(inp=100, out=200, cr=5_000, cc=0))
    thrash.append(tool_result("t_grep1", "src/auth.py:12: def login"))
    thrash += assistant_blocks("msg_lookup_2", "lk2", [
        {"type": "tool_use", "id": "t_read_a", "name": "Read",
         "input": {"file_path": "/repo/src/auth.py", "offset": 1, "limit": 40}},
    ], usage(inp=120, out=180, cr=6_000, cc=0))
    thrash.append(tool_result("t_read_a", "def login(): ..."))
    thrash += assistant_blocks("msg_reread", "rr1", [
        {"type": "tool_use", "id": "t_read_b", "name": "Read",
         "input": {"file_path": "/repo/src/auth.py", "offset": 1, "limit": 40}},
    ], usage(inp=130, out=50, cr=7_000, cc=0))
    thrash.append(tool_result("t_read_b", "def login(): ..."))
    for i in range(1, 4):
        tid = f"t_fail_{i}"
        thrash += assistant_blocks(f"msg_fail_{i}", f"fail{i}", [
            {"type": "tool_use", "id": tid, "name": "Bash",
             "input": {"command": f"pytest tests/test_login.py -k attempt{i}"}},
        ], usage(inp=140, out=30, cr=8_000, cc=0))
        thrash.append(tool_result(
            tid, "ModuleNotFoundError: No module named 'authlib'", is_error=True,
        ))
    for i in range(1, 5):
        tid = f"t_edit_{i}"
        thrash += assistant_blocks(f"msg_edit_{i}", f"ed{i}", [
            {"type": "tool_use", "id": tid, "name": "Edit",
             "input": {"file_path": "/repo/src/auth.py",
                       "old_string": f"v{i}", "new_string": f"v{i+1}"}},
        ], usage(inp=150, out=40, cr=9_000, cc=0))
        thrash.append(tool_result(tid, "ok"))
    write("token_thrash_session.jsonl", thrash)


def build_lookup():
    lookup = []
    lookup.append(user_text("Where is the rate limiter defined?", "u0"))
    for i, (name, inp) in enumerate([
        ("Grep", {"pattern": "rate.?limit", "path": "/repo"}),
        ("Glob", {"pattern": "**/*limit*"}),
        ("Read", {"file_path": "/repo/src/limits.py", "offset": 1, "limit": 60}),
    ], start=1):
        tid = f"t_lk_{i}"
        lookup += assistant_blocks(f"msg_lk_{i}", f"lka{i}", [
            {"type": "thinking", "thinking": f"Searching for rate limiter step {i}."},
            {"type": "tool_use", "id": tid, "name": name, "input": inp},
        ], usage(inp=80 + i * 10, out=500, cr=20_000, cc=500 if i == 1 else 0))
        lookup.append(tool_result(tid, f"hit for {name}"))
    lookup += assistant_blocks("msg_lk_done", "lkdone", [
        {"type": "text", "text": "Rate limiter is in src/limits.py."},
    ], usage(inp=200, out=40, cr=22_000, cc=0))
    write("lookup_heavy_session.jsonl", lookup)


if __name__ == "__main__":
    build_clean()
    build_thrash()
    build_lookup()
