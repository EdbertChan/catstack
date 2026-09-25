"""serial-option-guard: block a recommended serial plan for many publishing units.

PreToolUse on AskUserQuestion. The fixed "(Recommended)" label marker and the
transcript's tool calls are parsed as machine formats. Whether the recommended
option means "work many PR stacks one at a time in this chat" is a meaning
decision, so it goes to the llm-judge phrase dictionary
engine/hooks/llm-judge/phrases/serial-option-guard.json. The hook waits for
that one verdict so a hit blocks the menu before the user sees it; a verdict
that arrives late still reaches the agent through the llm-judge inbox.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(HOOK_DIR)
LLM_JUDGE_DIR = os.path.join(HOOKS_DIR, "llm-judge")
sys.path.insert(0, os.path.join(HOOKS_DIR, "_sdk"))

from finding import Finding  # noqa: E402

HOOK = "serial-option-guard"
TOOL_NAME = "AskUserQuestion"
RULE_ID = "serial-option-guard.serial-recommended"
WAIT_ENV = "SERIAL_OPTION_GUARD_WAIT_SECONDS"
DEFAULT_WAIT_SECONDS = 40.0
POLL_SECONDS = 0.25

RECOMMENDED_RE = re.compile(r"\(recommended\)", re.IGNORECASE)
ROUTING_SCRIPT = "route_execution"
UNITS_RE = re.compile(r"""\bunits["']?\s*[:=]\s*\d+""")
ROUTE_RESULT_RE = re.compile(r"\b(?:delegate_invoker|subagent_worktree_per_unit|subagent_fanout|local)\b")

UNCHECKED = (
    "serial-option-guard: unchecked, letting this menu through: {why}. If the (Recommended) option "
    "works several PR stacks one at a time here, run cat-mode's route_execution.py with units=N first."
)


def _llm_judge():
    if LLM_JUDGE_DIR not in sys.path:
        sys.path.insert(0, LLM_JUDGE_DIR)
    import judge
    import phrases

    return judge, phrases


def recommended_options(tool_input: object) -> list[str]:
    found: list[str] = []
    if not isinstance(tool_input, dict):
        return found
    for question in tool_input.get("questions") or []:
        if not isinstance(question, dict):
            continue
        for option in question.get("options") or []:
            if not isinstance(option, dict):
                continue
            label = option.get("label")
            if not isinstance(label, str) or not RECOMMENDED_RE.search(label):
                continue
            found.append(
                f"Question: {question.get('question') or ''}\n"
                f"Recommended option: {label}\n"
                f"Description: {option.get('description') or ''}"
            )
    return found


def _content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    return json.dumps(content or "")


def routing_ran(lines: list[dict]) -> bool:
    calls: dict[str, str] = {}
    for data in lines:
        content = _content(data)
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("name") == "Bash":
                command = str((block.get("input") or {}).get("command") or "")
                if ROUTING_SCRIPT in command and UNITS_RE.search(command):
                    calls[str(block.get("id"))] = command
            elif block.get("type") == "tool_result" and str(block.get("tool_use_id")) in calls:
                if not block.get("is_error") and ROUTE_RESULT_RE.search(_result_text(block)):
                    return True
    return False


def read_lines(path: str) -> list[dict]:
    lines: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            if isinstance(data, dict):
                lines.append(data)
    return lines


def wait_seconds() -> float:
    raw = os.environ.get(WAIT_ENV)
    if raw is None:
        return DEFAULT_WAIT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        sys.stderr.write(f"serial-option-guard: {WAIT_ENV}={raw!r} is not a number; waiting {DEFAULT_WAIT_SECONDS}s\n")
        return DEFAULT_WAIT_SECONDS


def take_verdict(judge, transcript: str, job_id: str) -> dict | None:
    path = os.path.join(judge.verdict_dir(transcript), f"{job_id}.json")
    taken = f"{path}.{os.getpid()}.taken"
    try:
        os.rename(path, taken)
    except FileNotFoundError:
        return None
    try:
        with open(taken, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (OSError, ValueError) as exc:
        loaded = {"id": job_id, "outcome": "unchecked", "reason": f"unreadable verdict file: {exc}"}
    finally:
        try:
            os.remove(taken)
        except OSError as exc:
            sys.stderr.write(f"serial-option-guard: could not remove {taken}: {exc}\n")
    return loaded if isinstance(loaded, dict) else {"id": job_id, "outcome": "unchecked", "reason": "verdict is not an object"}


def judge_options(transcript: str, options: list[str]) -> tuple[str, str]:
    judge, phrases = _llm_judge()
    dictionary = phrases.load(HOOK)
    job = phrases.job(dictionary, transcript, "\n\n".join(options))
    job["id"] = uuid.uuid4().hex
    if judge.enqueue(job) is None:
        return "skipped", ""
    deadline = time.monotonic() + wait_seconds()
    while True:
        verdict = take_verdict(judge, transcript, job["id"])
        if verdict is not None:
            outcome = str(verdict.get("outcome") or "unchecked")
            return outcome, str(verdict.get("reason") or "")
        if time.monotonic() >= deadline:
            return "unchecked", "the judge gave no answer in time; a late verdict arrives through the llm-judge inbox"
        time.sleep(POLL_SECONDS)


def detect(event: dict) -> list[Finding]:
    if not isinstance(event, dict) or event.get("agent_id"):
        return []
    if str(event.get("tool_name") or "") != TOOL_NAME:
        return []
    options = recommended_options(event.get("tool_input"))
    if not options:
        return []
    transcript = event.get("transcript_path") or event.get("transcriptPath")
    if not isinstance(transcript, str) or not transcript:
        sys.stderr.write(UNCHECKED.format(why="the payload names no transcript") + "\n")
        return []
    try:
        lines = read_lines(transcript)
    except OSError as exc:
        sys.stderr.write(UNCHECKED.format(why=f"the transcript could not be read ({exc!r})") + "\n")
        return []
    if routing_ran(lines):
        return []
    outcome, reason = judge_options(transcript, options)
    if outcome == "hit":
        _, phrases = _llm_judge()
        message = phrases.load(HOOK)["on_hit"]
        return [Finding(rule_id=RULE_ID, subject=options[0], message=message, evidence="\n\n".join(options))]
    if outcome == "unchecked":
        sys.stderr.write(UNCHECKED.format(why=reason or "the judge could not answer") + "\n")
    return []
