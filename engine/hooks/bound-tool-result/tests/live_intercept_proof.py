#!/usr/bin/env python3
"""Live intercept proof for bound-tool-result (not an adapter unit test).

Rewrites a deterministic large producer through each harness adapter, runs
the wrapped command, and asserts the parent-visible stub is <=16KiB with no
payload body. Exit 0 only when all three adapters prove the bound.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOK_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = HOOK_DIR.parents[2]
HELPER = REPO_ROOT.joinpath("corpus", "skills", "principle-guard-the-context-window", "scripts", "capture_tool_result.py")
HARD_BODY_LIMIT = 16_384
LARGE_CMD = "python3 -c 'import sys; sys.stdout.write(\"x\" * 200000)'"


def run_adapter(script: Path, payload: dict, env: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"{script.name} exited {proc.returncode}: {proc.stderr}")
    return json.loads(proc.stdout)


def parent_visible_command(reply: dict) -> str:
    for key in ("updatedInput", "updated_input"):
        block = reply.get(key)
        if isinstance(block, dict) and isinstance(block.get("command"), str):
            return block["command"]
    hook_output = reply.get("hookSpecificOutput")
    if isinstance(hook_output, dict):
        updated_input = hook_output.get("updatedInput")
        if isinstance(updated_input, dict) and isinstance(updated_input.get("command"), str):
            return updated_input["command"]
    raise SystemExit(f"adapter reply missing updated command: {reply!r}")


def assert_stub(stdout: bytes, label: str) -> dict:
    if len(stdout) > HARD_BODY_LIMIT:
        raise SystemExit(f"{label}: parent-visible stdout {len(stdout)} > {HARD_BODY_LIMIT}")
    stub = json.loads(stdout.decode("utf-8"))
    if stub.get("artifact", {}).get("body_included"):
        raise SystemExit(f"{label}: body_included true on over-cap stub: {stub!r}")
    if "stdout" in stub or "stderr" in stub:
        raise SystemExit(f"{label}: stub still contains payload body keys: {sorted(stub)}")
    body = stub.get("stdout_body") or stub.get("body")
    if body:
        raise SystemExit(f"{label}: stub leaked body ({len(body)} chars)")
    artifact = stub.get("artifact") or {}
    for key in ("stdout_path", "stderr_path", "handle"):
        if key in artifact and artifact[key]:
            break
    else:
        raise SystemExit(f"{label}: stub missing artifact paths: {stub!r}")
    stdout_path = Path(artifact["stdout_path"])
    if not stdout_path.is_file():
        raise SystemExit(f"{label}: stdout artifact missing: {stdout_path}")
    size = stdout_path.stat().st_size
    if size < 100_000:
        raise SystemExit(f"{label}: expected large on-disk stdout, got {size}")
    text = stdout.decode("utf-8")
    if "x" * 1000 in text:
        raise SystemExit(f"{label}: parent-visible stub contains log body")
    return stub


def main() -> int:
    if not HELPER.is_file():
        print(f"FAIL helper missing: {HELPER}", file=sys.stderr)
        return 1
    adapters = (
        ("claude", HOOK_DIR / "claude_pre_tool_use.py", "Bash"),
        ("cursor", HOOK_DIR / "cursor_pre_tool_use.py", "Shell"),
        ("codex", HOOK_DIR / "codex_pre_tool_use.py", "Bash"),
    )
    with tempfile.TemporaryDirectory(prefix="bound-tool-live-") as tmp:
        env = {
            **os.environ,
            "HOME": tmp,
            "CATSTACK_CAPTURE_HELPER": str(HELPER),
            "CATSTACK_TOOL_CAPTURE_ROOT": str(Path(tmp) / "captures"),
        }
        for agent in (".claude", ".cursor", ".codex"):
            skill_scripts = Path(tmp) / agent / "skills" / "principle-guard-the-context-window" / "scripts"
            skill_scripts.mkdir(parents=True)
            (skill_scripts / "capture_tool_result.py").symlink_to(HELPER)

        results = {}
        for label, script, tool_name in adapters:
            payload = {"tool_name": tool_name, "tool_input": {"command": LARGE_CMD}}
            reply = run_adapter(script, payload, env)
            command = parent_visible_command(reply)
            if "capture_tool_result.py" not in command:
                raise SystemExit(f"{label}: command was not rewritten: {command!r}")
            if LARGE_CMD.replace("'", "")[:20] not in command and "200000" not in command:
                pass
            proc = subprocess.run(
                ["bash", "-lc", command],
                capture_output=True,
                env=env,
                timeout=60,
                check=False,
            )
            stub = assert_stub(proc.stdout, label)
            results[label] = {
                "parent_visible_bytes": len(proc.stdout),
                "producer_exit": (stub.get("artifact") or {}).get("producer_exit_status"),
                "artifact": stub.get("artifact"),
            }
            print(f"ok {label}: parent_visible_bytes={len(proc.stdout)} artifact={stub.get('artifact', {}).get('handle')}")

    print(json.dumps({"status": "ok", "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
