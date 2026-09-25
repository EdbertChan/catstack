"""Refuse a second subagent's publishing command in one session while a live
Invoker owner is reachable.

The predecessor, agent-routing-guard, classified the spawn prompt with
regexes over prose: "carrying commits" parsed as an action because the noun
test required a determiner, and deleting the word cleared the block without
changing what the subagent would do. This detector never reads prose. It
parses the command the tool is about to run, which is a typed field, and
decides from four facts: the act, the caller, whether another subagent in
the same session already published within the window, and whether Invoker
can take the work.

The incident behind this gate was eight subagents publishing in parallel
from one session. A single subagent that finishes its work and pushes is not
that incident, and blocking it only moved the push back to the parent
session, which this gate never covers. So the first publishing subagent in a
session goes through and is recorded; a different subagent publishing within
PARALLEL_WINDOW_SECONDS of it is refused.

Fail directions, one per read:
  - unparsable payload, non-shell tool, empty command, non-subagent caller,
    command that is not a publishing act: open, with the reason recorded.
  - Invoker liveness could not be determined: open, and the reason is
    printed, because a probe that cannot run must not hold up publishing
    when Invoker may itself be down.
  - no session id, or the publisher ledger could not be read: open, and the
    reason is printed.
  - Invoker reachable and a different subagent in this session published
    within the window: closed.
"""
from __future__ import annotations

import json
import hashlib
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from finding import Finding

INVOKER_CLI = "invoker-cli"
ROUTING_SKILL = "invoker-plan-to-invoker"
LIVENESS_TTL_SECONDS = 120
LIVENESS_TIMEOUT_SECONDS = 8
LIVENESS_CACHE_PATH = os.path.join(
    os.environ.get("TMPDIR", "/tmp"), "publish-act-guard-liveness.json"
)
DEBUG_ENV = "PUBLISH_ACT_GUARD_DEBUG"
PUBLISHERS_PATH = os.path.join(
    os.environ.get("TMPDIR", "/tmp"), "publish-act-guard-publishers.json"
)
PARALLEL_WINDOW_SECONDS = 30 * 60
SESSION_ID_KEYS = ("session_id", "sessionId")

SUBAGENT_ID_KEYS = ("subagent_id", "subagentId", "agent_id", "agentId", "sub_agent_id")

SHELL_LIKE_TOOL_NAMES = frozenset({
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
})

LIVE = "live"
DOWN = "down"
UNCHECKED = "unchecked"
RULE_HELPER_PUBLISH = "publish-act-guard.helper-publish"
RULE_LIVENESS_UNCHECKED = "publish-act-guard.liveness-unchecked"

BLOCK_MESSAGE = (
    "publish-act-guard: this subagent is about to run a publishing command "
    "({act}), and subagent {other} in the same session already published "
    "{minutes} min ago while a live Invoker owner is reachable.\n"
    "Several subagents publishing in parallel is work for Invoker: follow the "
    "installed {skill} skill, then submit the plan. Or finish without "
    "publishing and report the commit: the parent session is never gated and "
    "can publish it.\n"
    "This gate reads the command, never the prompt. It goes quiet on its own "
    "when no live owner answers or {window} min after the other publish."
)


@dataclass(frozen=True)
class Detection:
    rule_id: str
    subject: str
    message: str
    evidence: str
    unchecked: bool = False


def _silent(reason: str) -> None:
    if os.environ.get(DEBUG_ENV):
        sys.stderr.write(f"publish-act-guard: silent ({reason})\n")
    return None


def _silent_text(reason: str) -> str:
    _silent(reason)
    return ""


def _silent_state(reason: str) -> None:
    _silent(reason)
    return None


def _warn(reason: str) -> None:
    sys.stderr.write(f"publish-act-guard: {reason}\n")


def tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def command_text(payload: dict) -> str:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return _silent_text("tool_input is not an object")
    for key in ("command", "cmd", "script", "input"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def _first_string(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def in_subagent(payload: dict) -> bool:
    return bool(_first_string(payload, SUBAGENT_ID_KEYS))


def _words(command: str) -> list[str]:
    try:
        return [word for word in shlex.split(command) if word]
    except ValueError as exc:
        _warn(f"command did not lex ({exc}); falling back to whitespace split")
        return re.findall(r"[^\s'\"]+", command)


SHELL_SEPARATORS = frozenset({"&&", "||", "|", ";", "(", ")", "{", "}", "&"})
COMMAND_PREFIXES = frozenset({"sudo", "env", "time", "timeout", "nohup", "xargs", "command", "nice"})
DRY_RUN_FLAGS = frozenset({"--dry-run", "-n", "--dryrun"})


def _command_heads(words: list[str]) -> list[list[str]]:
    """Split argv into command invocations, skipping separators, env
    assignments, and wrapper prefixes, so only a real command head is
    matched. A filename passed to cat is never a command head."""
    commands: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if word in SHELL_SEPARATORS:
            if current:
                commands.append(current)
            current = []
            continue
        current.append(word)
    if current:
        commands.append(current)
    heads = []
    for command in commands:
        index = 0
        while index < len(command):
            word = command[index]
            if "=" in word and not word.startswith("-") and index == 0:
                index += 1
                continue
            if os.path.basename(word) in COMMAND_PREFIXES:
                index += 1
                while index < len(command) and command[index].startswith("-"):
                    index += 1
                continue
            break
        if index < len(command):
            heads.append(command[index:])
    return heads


def publishing_act(command: str) -> str | None:
    """Name the publishing act this command performs, or None.

    Parses argv at command position, so a mention of "push" in a message, a
    path, a grep pattern, or a file argument is silent by construction. A
    dry run publishes nothing and is silent too.
    """
    for argv in _command_heads(_words(command)):
        base = os.path.basename(argv[0])
        rest = argv[1:]
        if any(flag in DRY_RUN_FLAGS for flag in rest):
            continue
        heads = [item for item in rest if not item.startswith("-")]
        if base == "git" and heads[:1] == ["push"]:
            return "git push"
        if base == "gh" and heads[:2] in (["pr", "create"], ["pr", "merge"], ["pr", "ready"]):
            return f"gh {heads[0]} {heads[1]}"
        if base == "gh" and heads[:1] == ["api"] and _writes_pull_request(rest):
            return "gh api pull-request write"
        if base == "mergify" and heads[:2] == ["stack", "push"]:
            return "mergify stack push"
        if base in ("node", "npx") and heads[:1]:
            script = os.path.basename(heads[0])
            if script == "create-pr.mjs":
                return "create-pr.mjs"
            if script == "safe-stack-push.mjs" and "--execute" in rest:
                return "safe-stack-push.mjs"
        if base == "create-pr.mjs":
            return "create-pr.mjs"
        if base == "safe-stack-push.mjs" and "--execute" in rest:
            return "safe-stack-push.mjs"
    return None


def _writes_pull_request(rest: list[str]) -> bool:
    joined = " ".join(rest)
    mutating = any(flag in rest for flag in ("-X", "--method")) and re.search(
        r"(?i)\b(POST|PATCH|PUT)\b", joined
    )
    return bool(mutating and re.search(r"/pulls\b", joined))


def _cache_read(now: float) -> str | None:
    try:
        with open(LIVENESS_CACHE_PATH, encoding="utf-8") as handle:
            cached = json.load(handle)
    except FileNotFoundError:
        return _silent_state("no liveness cache yet")
    except (PermissionError, json.JSONDecodeError, OSError) as exc:
        _warn(f"liveness cache unreadable ({type(exc).__name__}: {exc}); probing again")
        return None
    stamp = cached.get("at")
    state = cached.get("state")
    if not isinstance(stamp, (int, float)) or state not in (LIVE, DOWN):
        _warn("liveness cache malformed; probing again")
        return None
    if now - stamp > LIVENESS_TTL_SECONDS:
        return None
    return state


def _cache_write(state: str, now: float) -> None:
    try:
        with open(LIVENESS_CACHE_PATH, "w", encoding="utf-8") as handle:
            json.dump({"state": state, "at": now}, handle)
    except (PermissionError, OSError) as exc:
        _warn(f"liveness cache not written ({type(exc).__name__}: {exc})")


def invoker_state(runner=None, now: float | None = None) -> tuple[str, str]:
    """LIVE / DOWN / UNCHECKED, plus the reason when the probe could not run."""
    stamp = time.time() if now is None else now
    if runner is None:
        cached = _cache_read(stamp)
        if cached is not None:
            return cached, ""
    run = runner or _probe
    try:
        code = run()
    except FileNotFoundError:
        return DOWN, ""
    except (OSError, subprocess.SubprocessError) as exc:
        return UNCHECKED, f"{type(exc).__name__}: {exc}"
    if code is None:
        return UNCHECKED, "liveness probe timed out"
    state = LIVE if code == 0 else DOWN
    if runner is None:
        _cache_write(state, stamp)
    return state, ""


def _probe() -> int | None:
    try:
        completed = subprocess.run(
            [INVOKER_CLI, "query", "capacity", "--output", "json"],
            capture_output=True,
            timeout=LIVENESS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        _warn("liveness probe timed out")
        return None
    return completed.returncode


def _ledger_read() -> tuple[dict | None, str]:
    try:
        with open(PUBLISHERS_PATH, encoding="utf-8") as handle:
            ledger = json.load(handle)
    except FileNotFoundError:
        return {}, ""
    except (PermissionError, json.JSONDecodeError, OSError) as exc:
        return None, f"publisher ledger unreadable ({type(exc).__name__}: {exc})"
    if not isinstance(ledger, dict):
        return None, "publisher ledger is not an object"
    return ledger, ""


def _ledger_record(ledger: dict, session: str, agent: str, now: float) -> None:
    fresh = {
        sid: {aid: stamp for aid, stamp in agents.items()
              if isinstance(stamp, (int, float)) and now - stamp <= PARALLEL_WINDOW_SECONDS}
        for sid, agents in ledger.items() if isinstance(agents, dict)
    }
    fresh.setdefault(session, {})[agent] = now
    fresh = {sid: agents for sid, agents in fresh.items() if agents}
    try:
        with open(PUBLISHERS_PATH, "w", encoding="utf-8") as handle:
            json.dump(fresh, handle)
    except (PermissionError, OSError) as exc:
        _warn(f"publisher ledger not written ({type(exc).__name__}: {exc})")


def other_recent_publisher(ledger: dict, session: str, agent: str, now: float) -> tuple[str, float] | None:
    agents = ledger.get(session, {})
    if not isinstance(agents, dict):
        _warn(f"publisher ledger entry for session {session} is not an object; treating it as empty")
        return None
    recent = [
        (aid, stamp) for aid, stamp in agents.items()
        if aid != agent and isinstance(stamp, (int, float)) and 0 <= now - stamp <= PARALLEL_WINDOW_SECONDS
    ]
    return max(recent, key=lambda item: item[1]) if recent else None


def detect(event: dict[str, object]) -> list[Finding]:
    decision = _evaluate(event)
    if decision is None:
        return []
    finding = Finding(
        rule_id=decision.rule_id,
        subject=decision.subject,
        message=decision.message,
        evidence=decision.evidence,
    )
    if decision.unchecked:
        _append_unchecked(event, finding)
        _append_stderr(event, decision.message)
        return []
    return [finding]


def decide(payload: dict, runner=None, now: float | None = None) -> str | None:
    """The refusal to print, or None to let the command run."""
    decision = _evaluate(payload, runner=runner, now=now)
    return decision.message if decision is not None else None


def _evaluate(payload: dict, runner=None, now: float | None = None) -> Detection | None:
    if not isinstance(payload, dict):
        return _silent("payload is not an object")
    if tool_name(payload) not in SHELL_LIKE_TOOL_NAMES:
        return _silent("tool is not shell-like")
    command = command_text(payload)
    if not command.strip():
        return _silent("no command string in tool_input")
    if not in_subagent(payload):
        return _silent("caller is the main session, not a subagent")
    act = publishing_act(command)
    if act is None:
        return _silent("command performs no publishing act")
    stamp = time.time() if now is None else now
    session = _first_string(payload, SESSION_ID_KEYS)
    agent = _first_string(payload, SUBAGENT_ID_KEYS)
    state, reason = invoker_state(runner=runner)
    if state == DOWN:
        return _silent(f"no live Invoker owner; {act} may proceed here")
    if state == UNCHECKED:
        message = (
            "publish-act-guard: UNCHECKED: could not tell whether a live Invoker owner "
            f"is reachable ({reason}); allowing {act}. Say so in the report."
        )
        return Detection(
            rule_id=RULE_LIVENESS_UNCHECKED,
            subject=_command_subject(command),
            message=message,
            evidence=f"act={act}; invoker_state={state}; reason={reason}",
            unchecked=True,
        )
    if not session:
        message = (
            f"publish-act-guard: UNCHECKED: the payload carries no session id, so parallel "
            f"publishers cannot be told apart; allowing {act}. Say so in the report."
        )
        return Detection(
            rule_id=RULE_LIVENESS_UNCHECKED,
            subject=_command_subject(command),
            message=message,
            evidence=f"act={act}; invoker_state={state}; reason=no session id",
            unchecked=True,
        )
    ledger, ledger_reason = _ledger_read()
    if ledger is None:
        message = (
            f"publish-act-guard: UNCHECKED: {ledger_reason}; allowing {act}. "
            f"Say so in the report."
        )
        return Detection(
            rule_id=RULE_LIVENESS_UNCHECKED,
            subject=_command_subject(command),
            message=message,
            evidence=f"act={act}; invoker_state={state}; reason={ledger_reason}",
            unchecked=True,
        )
    other = other_recent_publisher(ledger, session, agent, stamp)
    if other is not None:
        other_agent, other_stamp = other
        message = BLOCK_MESSAGE.format(
            act=act,
            other=other_agent,
            minutes=int((stamp - other_stamp) // 60),
            window=PARALLEL_WINDOW_SECONDS // 60,
            skill=ROUTING_SKILL,
        )
        return Detection(
            rule_id=RULE_HELPER_PUBLISH,
            subject=_command_subject(command),
            message=message,
            evidence=f"act={act}; invoker_state={state}; other={other_agent}",
        )
    _ledger_record(ledger, session, agent, stamp)
    return _silent(f"first publishing subagent in session {session}; {act} may proceed")


def _command_subject(command: str) -> str:
    return "command:" + hashlib.sha256(command.encode("utf-8")).hexdigest()


def _append_unchecked(event: dict[str, object], finding: Finding) -> None:
    raw = event.get("_catstack_unchecked_findings")
    if not isinstance(raw, list):
        raw = []
        event["_catstack_unchecked_findings"] = raw
    raw.append(finding)


def _append_stderr(event: dict[str, object], line: str) -> None:
    raw = event.get("_catstack_stderr_lines")
    if not isinstance(raw, list):
        raw = []
        event["_catstack_stderr_lines"] = raw
    raw.append(line)
