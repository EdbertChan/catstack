"""Block the second and later subagent launch in one turn when the launches
may publish and nothing routed them.

Typed inputs decide everything they can: the turn's earlier Agent launches,
and whether a routing script (cat-mode's route_execution.py or Invoker's
route-delegation.mjs) returned a route in this session. Two questions are
meaning, so the shared llm-judge answers them from phrase dictionaries:
does a launch's prompt grant publishing authority, and did the user
explicitly direct subagents or say to do it locally.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(HOOK_DIR)
LLM_JUDGE_DIR = os.path.join(HOOKS_DIR, "llm-judge")
sys.path.insert(0, os.path.join(HOOKS_DIR, "_sdk"))

import judge_channel  # noqa: E402
from finding import Finding  # noqa: E402
from judge_channel import CLEAN, HIT, UNCHECKED  # noqa: E402
from transcript_rows import (  # noqa: E402
    content_text as _content_text,
    is_user_prompt,
    read_lines,
    tool_results,
    tool_uses,
    user_prompts,
)

HOOK = "fanout-routing-guard"
RULE_ID = "fanout-routing-guard.unrouted-publishing-fanout"
PUSH_CHECKER = "fanout-routing-guard-push-authority"
DIRECTION_CHECKER = "fanout-routing-guard-user-direction"
AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})
ROUTING_SCRIPTS = ("route_execution.py", "route-delegation.mjs")
ROUTES = frozenset({"local", "delegate_invoker", "subagent_fanout", "subagent_worktree_per_unit"})
WAIT_ENV = "FANOUT_ROUTING_GUARD_WAIT_SECONDS"
STATE_ENV = "FANOUT_ROUTING_GUARD_STATE_DIR"
DEFAULT_WAIT_SECONDS = 40.0
PROMPT_BUDGET = 1500
FILE_BUDGET = 2400
MAX_FILES = 2
BRIEF_PATH_RE = re.compile(r"(/[^\s'\"`<>()]+\.(?:md|txt))")
CONFIG = judge_channel.ChannelConfig(
    hook=HOOK,
    id_prefix="frg",
    state_env=STATE_ENV,
    cache_dirname="catstack-fanout-routing-guard",
)

BLOCK_MESSAGE = (
    "fanout-routing-guard: this is subagent launch {n} in this turn, at least two of them may commit, "
    "push, or open PRs, and this session has no routing result. Run the routing table first, e.g. "
    "`python3 ~/.claude/skills/cat-mode/scripts/route_execution.py "
    "'{{\"tools\":[...],\"work_kind\":\"durable_parallel\",\"produces\":[\"commit\",\"pull_request\"],\"units\":{n}}}'` "
    "(or Invoker's route-delegation.mjs), and follow the route it prints: Invoker when its MCP tools are "
    "available. Subagents are fine once the route says so, or when the user explicitly directs subagents "
    "or says to do it locally."
)
UNCHECKED_SUFFIX = (
    " The judge could not decide whether these launches publish ({why}); a check that could not run is "
    "not a pass, so this launch is held until a routing result exists."
)
UNREADABLE_MESSAGE = "fanout-routing-guard: UNCHECKED, allowing the launch: {why}"


def prior_launch_prompts(rows: list[dict], current_id: str, current_prompt: str) -> list[str]:
    start = 0
    for index, row in enumerate(rows):
        if is_user_prompt(row):
            start = index + 1
    launches = []
    for row in rows[start:]:
        for use in tool_uses(row):
            if use.get("name") not in AGENT_TOOL_NAMES:
                continue
            tool_input = use.get("input") if isinstance(use.get("input"), dict) else {}
            launches.append((str(use.get("id") or ""), str(tool_input.get("prompt") or "")))
    if current_id:
        return [prompt for use_id, prompt in launches if use_id != current_id]
    for index in range(len(launches) - 1, -1, -1):
        if launches[index][1] == current_prompt:
            del launches[index]
            break
    return [prompt for _, prompt in launches]


def _result_has_route(block: dict) -> bool:
    if block.get("is_error"):
        return False
    for line in _content_text(block.get("content")).splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and data.get("route") in ROUTES:
            return True
    return False


def has_routing_result(rows: list[dict]) -> bool:
    routing_ids = set()
    for row in rows:
        for use in tool_uses(row):
            tool_input = use.get("input") if isinstance(use.get("input"), dict) else {}
            command = str(tool_input.get("command") or "")
            if any(script in command for script in ROUTING_SCRIPTS):
                routing_ids.add(str(use.get("id") or ""))
        for block in tool_results(row):
            if str(block.get("tool_use_id") or "") in routing_ids and _result_has_route(block):
                return True
    return False


def launch_text(prompt: str) -> str:
    parts = [prompt[:PROMPT_BUDGET]]
    seen = []
    for path in BRIEF_PATH_RE.findall(prompt):
        if path in seen or len(seen) >= MAX_FILES:
            continue
        seen.append(path)
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = handle.read(FILE_BUDGET)
        except OSError as exc:
            parts.append(f"\n[brief file {path} could not be read: {type(exc).__name__}]")
            continue
        parts.append(f"\n[brief file {path}]\n{body}")
    return "\n".join(parts)


def wait_seconds() -> float:
    return judge_channel.wait_seconds(WAIT_ENV, DEFAULT_WAIT_SECONDS)


def state_path(transcript: str) -> str:
    return judge_channel.state_path(CONFIG, transcript)


def decision(current: str | None, priors: list[str | None], direction: str | None) -> str | None:
    """"allow", "block", or None while a needed verdict is still out."""
    if current == CLEAN:
        return "allow"
    if priors and all(p == CLEAN for p in priors):
        return "allow"
    if direction == HIT:
        return "allow"
    if current is None or direction is None:
        return None
    if any(p in (HIT, UNCHECKED) for p in priors):
        return "block"
    return None


def resolve(transcript: str, prompt: str, priors: list[str], user_text: str, wait: float) -> tuple[str, list[str]]:
    verdicts = judge_channel.Verdicts(CONFIG, transcript, time.time())
    current_id = verdicts.request(PUSH_CHECKER, launch_text(prompt))
    if verdicts.outcome(current_id) == CLEAN:
        return "allow", []
    prior_ids = [verdicts.request(PUSH_CHECKER, launch_text(p)) for p in priors]
    direction_id = verdicts.request(DIRECTION_CHECKER, user_text or "(no user message)")
    needed = [current_id, *prior_ids, direction_id]

    def settle() -> str | None:
        return decision(
            verdicts.outcome(current_id),
            [verdicts.outcome(i) for i in prior_ids],
            verdicts.outcome(direction_id),
        )

    result = judge_channel.await_verdicts(verdicts, needed, settle, wait) or "block"
    verdicts.save()
    unchecked = [verdicts.reasons.get(j, "unchecked") for j in needed if verdicts.outcome(j) == UNCHECKED]
    return result, unchecked


def evaluate(event: dict, wait: float | None = None) -> tuple[str, str]:
    """(outcome, message): outcome is "allow", "block", or "unchecked"."""
    if not isinstance(event, dict) or event.get("tool_name") not in AGENT_TOOL_NAMES:
        return "allow", ""
    if event.get("agent_id"):
        return "allow", ""
    tool_input = event.get("tool_input")
    prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        return "allow", ""
    transcript = event.get("transcript_path")
    if not isinstance(transcript, str) or not transcript:
        return "unchecked", UNREADABLE_MESSAGE.format(why="the payload names no transcript")
    try:
        rows = read_lines(transcript)
    except OSError as exc:
        return "unchecked", UNREADABLE_MESSAGE.format(why=f"the transcript could not be read: {exc}")
    current_id = str(event.get("tool_use_id") or "")
    priors = prior_launch_prompts(rows, current_id, prompt)
    if not priors or has_routing_result(rows):
        return "allow", ""
    user_text = "\n---\n".join(user_prompts(rows))
    result, unchecked = resolve(transcript, prompt, priors, user_text, wait_seconds() if wait is None else wait)
    if result == "allow":
        return "allow", ""
    message = BLOCK_MESSAGE.format(n=len(priors) + 1)
    if unchecked:
        message += UNCHECKED_SUFFIX.format(why="; ".join(sorted(set(unchecked)))[:400])
    return "block", message


def detect(event: dict) -> list[Finding]:
    outcome, message = evaluate(event)
    if outcome == "unchecked":
        print(message, file=sys.stderr)
        return []
    if outcome != "block":
        return []
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    prompt = str(tool_input.get("prompt") or "")
    subject = str(event.get("tool_use_id") or f"agent-prompt:{judge_channel.sha(prompt)}")
    return [Finding(rule_id=RULE_ID, subject=subject, message=message, evidence=prompt[:2000])]
