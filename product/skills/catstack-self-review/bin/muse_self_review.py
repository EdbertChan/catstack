#!/usr/bin/env python3
"""Muse self-review adapter: run catstack's hook registry against the agent's own work.

Catstack hooks are written for Claude/Cursor/Codex harness events. This adapter
lets Muse (Meta's agent, which has no hook pipeline) run the *same detector
code* against its own drafts and planned tool calls. The agent is its own hook
runner: findings in a hook whose registry mode is "stop" mean do-not-send /
do-not-act, exactly as Stop/PreToolUse hooks behave on the other harnesses.

How it works:
  1. Loads the full hook registry (engine/hooks/hooks.toml) -- every hook,
     its mode (off/warn/stop), honoring CATSTACK_HOOK_MODE_<HOOK> overrides.
  2. For each hook, resolves its detect(event) function: <hook>/detect.py, or
     the module the harness wrappers (claude_*.py / cursor_*.py / codex_*.py)
     import detect from.
  3. Reads each hook's installed fragments (*.hook.json) to learn which events
     it subscribes to, and synthesizes the matching events from the review:
       Stop                -> {"last_assistant_message": draft}
       UserPromptSubmit    -> {"prompt": user_message}
       PreToolUse          -> per tool call {"tool_name", "tool_input"}
       PostToolUse(-Batch) -> one batch {"tool_calls": [{tool_use_id, tool_response}]}
  4. Applies each hook's effective mode to its findings. Exit 2 on any stop
     finding, 1 on warn-only, 0 when clean. A detector that crashes on the
     synthetic event is fail-open (reported as unchecked, never blocking).

Input: JSON on stdin or as argv[1]:
{
  "session_id": "muse-<chat-id>",     # keys hook state; throwaway ids for tests
  "user_message": "<latest user msg>",
  "draft": "<planned final message>",
  "tool_calls": [
    {"tool": "muse.exec", "id": "c1", "input": {...},
     "result": "<result text; prefix DENIED: for a refused call>"}
  ],
  "prior_user_turns": ["<earlier user msgs>"],   # optional, for scope transcript
  "cwd": "/home/hatch/workspace",
  "hooks": ["diu-stop", "scope-lock"],           # optional: subset to run
  "judge": true                                  # optional: also emit a
                                                 # diu-stop plain-words judge
                                                 # request for an isolated
                                                 # Muse subagent (SKILL.md)
}

Environment:
  CATSTACK_HOOKS_DIR               override for the catstack checkout
  CATSTACK_REFLECT_ENFORCEMENT=1   arm scope-lock et al for this run
                                   (default follows repo policy: off)
Every run appends one JSONL row to ~/.cache/catstack-muse-review/ledger.jsonl
for the drift watch.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time

CACHE = os.path.join(os.path.expanduser("~"), ".cache")
os.environ.setdefault("CATSTACK_HOOK_METRICS_DIR", os.path.join(CACHE, "catstack-hook-metrics-muse"))
os.environ.setdefault("CATSTACK_HOOK_REMINDER_STATE_DIR", os.path.join(CACHE, "catstack-hook-reminders-muse"))
os.environ.setdefault("SCOPE_LOCK_STATE_DIR", os.path.join(CACHE, "catstack-muse-scope-lock"))
os.environ.setdefault("REPEAT_DENY_STOP_STATE_DIR", os.path.join(CACHE, "catstack-muse-repeat-deny-stop"))
# diu-stop's plain-words check polls an LLM-judge queue that only exists on the
# Claude harness; without a drainer it would burn the full 40s deadline doing
# nothing. 0 keeps the deterministic checks (word count, unverified claims,
# marker problems) and skips the wait. Override upward if a judge is wired.
os.environ.setdefault("DIU_PLAIN_WORDS_WAIT_SECONDS", "0")
# This process is a judge context, not a hook on a CLI harness: never let
# llm-judge's enqueue() spawn its detached `judge.py run` child, which would
# shell out to claude/codex/cursor CLIs that do not exist here. The Muse
# judge protocol (see SKILL.md) builds the same prompt and hands it to an
# isolated Muse subagent instead.
os.environ.setdefault("CATSTACK_LLM_JUDGE_CHILD", "1")
LEDGER = os.path.join(CACHE, "catstack-muse-review", "ledger.jsonl")
JUDGE_REQUESTS = os.path.join(CACHE, "catstack-muse-review", "judge-requests")
JUDGE_REQUEST_TTL_SECONDS = 24 * 3600

HOOKS_DIR = os.environ.get(
    "CATSTACK_HOOKS_DIR",
    os.path.join(os.path.expanduser("~"), "workspace", "catstack", "engine", "hooks"),
)

SKIP_EVENTS = {"sessionend"}


def _load_module(name: str, path: str):
    """Exec a hook file with its own dir first on sys.path so sibling imports
    (e.g. `from state import ...`) resolve to that hook's files, not another
    hook's same-named module. Cleans up afterwards."""
    hook_dir = os.path.dirname(path)
    before = set(sys.modules)
    sys.path.insert(0, hook_dir)
    try:
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(hook_dir)
        for key in [k for k in sys.modules if k not in before and k != name]:
            mod = sys.modules[key]
            mod_file = getattr(mod, "__file__", "") or ""
            if mod_file.startswith(hook_dir + os.sep):
                del sys.modules[key]
    return module


def _resolve_detect(hook: str):
    """Return the hook's detect(event) callable, or None if not resolvable."""
    hook_dir = os.path.join(HOOKS_DIR, hook)
    if not os.path.isdir(hook_dir):
        return None
    direct = os.path.join(hook_dir, "detect.py")
    if os.path.isfile(direct):
        with open(direct, encoding="utf-8") as handle:
            if "def detect(" in handle.read():
                return _load_module(f"muse_hook_{hook}".replace("-", "_"), direct).detect
    for filename in sorted(os.listdir(hook_dir)):
        if not filename.endswith(".py"):
            continue
        if not filename.startswith(("claude_", "cursor_", "codex_")):
            continue
        path = os.path.join(hook_dir, filename)
        with open(path, encoding="utf-8") as handle:
            src = handle.read()
        match = re.search(r"from\s+(\w+)\s+import\s+[^\n]*\bdetect\b", src)
        if not match:
            continue
        target = os.path.join(hook_dir, match.group(1) + ".py")
        if os.path.isfile(target):
            with open(target, encoding="utf-8") as handle:
                if "def detect(" in handle.read():
                    return _load_module(
                        f"muse_hook_{hook}".replace("-", "_"), target
                    ).detect
    return None


def _subscribed_events(hook: str) -> set[str]:
    """Event types from the hook's installed fragments, normalized."""
    hook_dir = os.path.join(HOOKS_DIR, hook)
    types: set[str] = set()
    for filename in os.listdir(hook_dir):
        if not (filename.endswith(".hook.json") or filename.endswith(".hooks.json")):
            continue
        try:
            with open(os.path.join(hook_dir, filename), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            continue
        for key in data.get("hooks", {}):
            norm = key.lower()
            if norm in ("stop",):
                types.add("stop")
            elif norm in ("userpromptsubmit", "beforesubmitprompt"):
                types.add("prompt")
            elif norm in ("pretooluse",):
                types.add("pretool")
            elif norm in ("posttooluse", "posttoolbatch", "posttoolusefailure"):
                types.add("posttool")
    return types - SKIP_EVENTS


def _synth_transcript(review: dict) -> str:
    lines: list[str] = []
    for msg in review.get("prior_user_turns") or []:
        lines.append(json.dumps({"message": {"role": "user", "content": msg}}))
    for call in review.get("tool_calls") or []:
        lines.append(
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {
                                "type": "tool_use",
                                "name": call.get("tool", ""),
                                "input": call.get("input") or {},
                            }
                        ],
                    }
                }
            )
        )
    if review.get("user_message"):
        lines.append(
            json.dumps({"message": {"role": "user", "content": review["user_message"]}})
        )
    handle = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", prefix="muse-review-", delete=False, encoding="utf-8"
    )
    handle.write("\n".join(lines) + "\n")
    handle.close()
    return handle.name


def _deny_text(result: str) -> str:
    if result.startswith("DENIED:"):
        return "The user doesn't want to proceed with this tool use. " + result[len("DENIED:"):].strip()
    return result


def _call_id(call: dict, i: int) -> str:
    if call.get("id"):
        return str(call["id"])
    digest = hashlib.sha256(
        json.dumps(call.get("input") or {}, sort_keys=True, default=str).encode()
    ).hexdigest()[:12]
    return f"call-{i}-{digest}"


def _gc_judge_requests() -> None:
    """Drop judge-request files older than the TTL; a verdict that never came
    back is stale, not pending."""
    try:
        names = os.listdir(JUDGE_REQUESTS)
    except OSError:
        return
    cutoff = time.time() - JUDGE_REQUEST_TTL_SECONDS
    for name in names:
        if not name.endswith(".json") or name.endswith(".verdict.json"):
            continue
        path = os.path.join(JUDGE_REQUESTS, name)
        try:
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
        except OSError:
            pass


def _emit_judge_request(review: dict, transcript_path: str, session_id: str) -> str | None:
    """Build diu-stop's plain-words LLM-judge job for this review and write it
    as a judge-request file for the agent to hand to an isolated Muse
    subagent (see SKILL.md "Isolated Muse judge"). Returns the request path,
    or None when no judge job applies. The prompt is byte-identical to what
    the Claude harness would send its CLI judges."""
    draft = review.get("draft") or ""
    if not draft.strip():
        return None
    hook_dir = os.path.join(HOOKS_DIR, "diu-stop")
    mod_path = os.path.join(hook_dir, "plain_words.py")
    if not os.path.isfile(mod_path):
        return None
    plain_words = _load_module("muse_hook_diu_stop_plain_words", mod_path)
    job = plain_words.job(
        {"last_assistant_message": draft, "transcript_path": transcript_path}
    )
    if not job:
        return None
    os.makedirs(JUDGE_REQUESTS, exist_ok=True)
    _gc_judge_requests()
    request = {
        "id": job["id"],
        "hook": job.get("hook", "diu-plain-words"),
        "prompt": job["prompt"],
        "hit_if_all_true": job.get("hit_if_all_true", ["match"]),
        "on_hit": job.get(
            "on_hit",
            "diu: the last reply used wording the user has had to ask about; "
            "say it in everyday words.",
        ),
        "reply": draft,
        "created_ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session_id": session_id,
        "judge_system_prompt": (
            "You are a classifier. Answer with exactly one line of JSON and "
            "nothing else."
        ),
    }
    path = os.path.join(JUDGE_REQUESTS, f"{job['id']}.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(request, handle, ensure_ascii=False, indent=2)
    return path


def main() -> int:
    raw = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    review = json.loads(raw)

    for sub in ("_sdk", "_flags", "_markers"):
        path = os.path.join(HOOKS_DIR, sub)
        if path not in sys.path:
            sys.path.insert(0, path)
    # NOTE: hook dirs are NOT added to sys.path globally -- sibling modules
    # with the same name in different hooks (state.py, detect.py) would
    # collide. _load_module scopes each hook's dir during its own import.

    from modes import effective_mode  # noqa: E402
    from registry import load_registry  # noqa: E402

    registry, _ = load_registry()
    wanted = set(review.get("hooks") or [])
    hooks = sorted(n for n in registry if not wanted or n in wanted)

    transcript_path = _synth_transcript(review)
    session_id = review.get("session_id") or "muse-self-review"
    cwd = review.get("cwd") or os.getcwd()
    base = {
        "session_id": session_id,
        "cwd": cwd,
        "transcript_path": transcript_path,
        "_catstack_harness": "muse",
    }

    tool_calls = review.get("tool_calls") or []
    stop_findings: list[str] = []
    warn_findings: list[str] = []
    ran: list[str] = []
    skipped: list[str] = []
    started = time.time()

    for hook in hooks:
        detect = _resolve_detect(hook)
        if detect is None:
            skipped.append(f"{hook} (no detect resolvable)")
            continue
        events: list[tuple[str, dict]] = []
        subs = _subscribed_events(hook)
        if "stop" in subs and review.get("draft"):
            events.append(("Stop", {**base, "hook_event_name": "Stop",
                                    "last_assistant_message": review["draft"]}))
        if "prompt" in subs and review.get("user_message"):
            events.append(("UserPromptSubmit", {**base, "hook_event_name": "UserPromptSubmit",
                                                "prompt": review["user_message"]}))
        if "pretool" in subs:
            for i, call in enumerate(tool_calls):
                events.append(("PreToolUse", {
                    **base, "hook_event_name": "PreToolUse",
                    "tool_name": call.get("tool", ""),
                    "tool_input": call.get("input") or {},
                    "tool_call_id": _call_id(call, i),
                }))
        if "posttool" in subs and tool_calls:
            events.append(("PostToolUse", {
                **base, "hook_event_name": "PostToolUse",
                "tool_calls": [
                    {"tool_use_id": _call_id(call, i),
                     "tool_response": _deny_text(str(call.get("result", "")))}
                    for i, call in enumerate(tool_calls)
                ],
            }))
        if not events:
            skipped.append(f"{hook} (no synthesizable event)")
            continue
        try:
            mode, source = effective_mode(hook, base)
        except Exception as exc:
            skipped.append(f"{hook} (registry error: {exc})")
            continue
        if mode == "off":
            skipped.append(f"{hook} (mode=off)")
            continue
        for event_name, event in events:
            try:
                findings = detect(event) or []
            except Exception as exc:
                print(f"[{hook}/{event_name}] detector crashed ({exc}); unchecked",
                      file=sys.stderr)
                continue
            ran.append(f"{hook}/{event_name} (mode={mode} via {source})")
            for finding in findings:
                first = str(finding.message).strip().splitlines()
                line = f"[{hook}/{event_name}] {finding.rule_id}: {first[0][:400] if first else ''}"
                (stop_findings if mode == "stop" else warn_findings).append(line)

    duration_ms = int((time.time() - started) * 1000)
    judge_request = None
    if review.get("judge"):
        try:
            judge_request = _emit_judge_request(review, transcript_path, session_id)
        except Exception as exc:
            print(f"[judge] request build failed ({exc}); unchecked",
                  file=sys.stderr)
    print(f"catstack self-review ({session_id}) -- {len(ran)} checks, "
          f"{len(skipped)} skipped, {duration_ms}ms")
    if judge_request:
        print(f"JUDGE_REQUEST {judge_request}")
    for line in warn_findings:
        print(f"  WARN {line}")
    for line in stop_findings:
        print(f"  STOP {line}")
    if stop_findings:
        print("STOP -- do not send the draft / do not run the tool calls. "
              "Fix every flagged item and re-run (max 3 attempts); if still "
              "stopped, surface the findings to the user instead of acting.")
        code = 2
    elif warn_findings:
        code = 1
    else:
        print("clean: no findings.")
        code = 0

    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "session_id": session_id,
            "checks": len(ran),
            "stops": len(stop_findings),
            "warns": len(warn_findings),
            "exit": code,
            "ms": duration_ms,
        }) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
