"""named-verb-guard: when the user asked for a verb, the reply must show it happened.

Whether the user asked (repro/test/prove, run/show, delete/revert, stop, or a
repeated demand for proof) is judged by the background model from one phrase
dictionary per request type. Whether the reply already carries that type's
evidence is shape only and stays here: a closed fenced block, a `path:line`,
a URL, a markdown table row, a delete/revert command, or no mutating tool call
after the message. A request whose evidence is already present is never sent
to the judge.

Never blocks. A hit arrives on a later turn through the llm-judge inbox.
Fail-open on any read/parse error; `stop_hook_active` skips.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
import time
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")
SDK_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_markers"))

import markers  # noqa: E402
from events import write_events  # noqa: E402
from finding import Finding  # noqa: E402
from modes import effective_mode  # noqa: E402

HOOK = "named-verb-guard"
PROOF_DEMAND = "named-verb-guard-proof-demand"
PROVE_REQUEST = "named-verb-guard-prove-request"
SHOW_REQUEST = "named-verb-guard-show-request"
DELETE_REQUEST = "named-verb-guard-delete-request"
STOP_REQUEST = "named-verb-guard-stop-request"
CHECKERS = (PROOF_DEMAND, PROVE_REQUEST, SHOW_REQUEST, DELETE_REQUEST, STOP_REQUEST)
RULE_IDS = {
    PROOF_DEMAND: "named-verb-guard.proof-demand",
    PROVE_REQUEST: "named-verb-guard.prove-request",
    SHOW_REQUEST: "named-verb-guard.show-request",
    DELETE_REQUEST: "named-verb-guard.delete-request",
    STOP_REQUEST: "named-verb-guard.stop-request",
}
WAIT_ENV = "CATSTACK_NAMED_VERB_GUARD_WAIT_SECONDS"
DEFAULT_WAIT_SECONDS = 40.0
POLL_SECONDS = 0.1
UNCHECKED_MESSAGE = (
    "named-verb-guard: unchecked, letting this reply through: {why}. "
    "A late verdict will still arrive through the llm-judge inbox."
)

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
FILE_LINE_RE = re.compile(r"\b[\w./-]+\.[A-Za-z]{1,5}:\d+\b")
URL_RE = re.compile(r"https?://\S+")
TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
DESTRUCTIVE_CMD_RE = re.compile(
    r"(?:^|\s|\||&&|;)(?:rm|unlink|trash|git\s+(?:rm|revert|reset|restore|checkout|clean|stash))\b",
    re.IGNORECASE,
)
MUTATING_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
MESSAGE_SEPARATOR = "\n\n--- next user message ---\n\n"

SYSTEM_INJECTED_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "<user-prompt-submit-hook",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
    "Stop hook feedback:",
    "PreToolUse hook",
    "PostToolUse hook",
    "UserPromptSubmit hook",
)


def _text_of(data: dict) -> str | None:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return None


def _is_human_line(data: dict) -> str | None:
    if not isinstance(data, dict) or data.get("type") != "user":
        return None
    text = _text_of(data)
    if not text or not text.strip():
        return None
    if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
        return None
    if "[Request interrupted by user" in text:
        return None
    return text


def read_transcript(transcript_path: str) -> tuple[list[str], list[dict]]:
    """(all human messages in order, tool_use blocks after the last one)."""
    humans: list[str] = []
    tool_uses: list[dict] = []
    with open(transcript_path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _is_human_line(data)
            if text is not None:
                humans.append(text)
                tool_uses = []
                continue
            if not isinstance(data, dict) or data.get("type") != "assistant":
                continue
            message = data.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tool_uses.append(block)
    return humans, tool_uses


def has_output_evidence(message: str) -> bool:
    return bool(FENCE_RE.search(message) or FILE_LINE_RE.search(message))


def has_link_evidence(message: str) -> bool:
    return bool(URL_RE.search(message) or TABLE_ROW_RE.search(message))


def bash_commands(tool_uses: list[dict]) -> list[str]:
    out = []
    for block in tool_uses:
        if block.get("name") == "Bash":
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                out.append(command)
    return out


def has_destructive_evidence(message: str, tool_uses: list[dict]) -> bool:
    if any(DESTRUCTIVE_CMD_RE.search(c) for c in bash_commands(tool_uses)):
        return True
    return any(DESTRUCTIVE_CMD_RE.search(c) for c in re.findall(r"`([^`]+)`", message))


def mutating_calls(tool_uses: list[dict]) -> list[str]:
    return [b.get("name") for b in tool_uses if b.get("name") in MUTATING_TOOLS]


def pending_requests(message: str, humans: list[str], tool_uses: list[dict]) -> list[tuple[str, str]]:
    """(checker, text to judge) for each request type whose evidence the reply lacks."""
    if not humans or not humans[-1].strip():
        return []
    if markers.well_formed_tags(message) or message.rstrip().endswith("?"):
        return []
    last = humans[-1]
    output_ok = has_output_evidence(message)
    link_ok = output_ok or has_link_evidence(message)
    pending: list[tuple[str, str]] = []
    if not link_ok and len(humans) >= 2:
        pending.append((PROOF_DEMAND, MESSAGE_SEPARATOR.join(humans)))
    if not output_ok:
        pending.append((PROVE_REQUEST, last))
    if not link_ok:
        pending.append((SHOW_REQUEST, last))
    if not has_destructive_evidence(message, tool_uses):
        pending.append((DELETE_REQUEST, last))
    if mutating_calls(tool_uses):
        pending.append((STOP_REQUEST, last))
    return pending


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def enqueue_judge(payload: dict) -> list[str]:
    """Enqueue one judge job per request type whose evidence is missing; return job ids."""
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return []
    message = payload.get("last_assistant_message") or ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not message or not transcript_path or not os.path.isfile(transcript_path):
        return []
    humans, tool_uses = read_transcript(transcript_path)
    job_ids: list[str] = []
    for checker, text in pending_requests(message, humans, tool_uses):
        dictionary = _phrases().load(checker)
        job = _phrases().job(dictionary, transcript_path, text)
        job["id"] = uuid.uuid4().hex
        job_ids.append(_judge().enqueue(job))
    return job_ids


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error named-verb-guard: {type(exc).__name__}: {exc}", file=sys.stderr)
        return


def detect(event: dict[str, object]) -> list[Finding]:
    if not isinstance(event, dict):
        return []
    try:
        mode, mode_source = effective_mode(HOOK, event)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: mode unchecked ({type(exc).__name__}: {exc})", file=sys.stderr)
        return []
    if mode == "off":
        return []
    try:
        check = _check_reply(event)
        if check is None:
            return []
        message, transcript_path, pending = check
        seconds = wait_seconds()
        jobs: list[tuple[str, str, dict, str]] = []
        for checker, text in pending:
            dictionary = _phrases().load(checker)
            job = _phrases().job(dictionary, transcript_path, text)
            job["id"] = uuid.uuid4().hex
            job["hook"] = HOOK
            job["rule_id"] = RULE_IDS[checker]
            job["timeout_seconds"] = seconds
            job_id = _judge().enqueue(job)
            if job_id is not None:
                jobs.append((checker, text, dictionary, job_id))
        findings: list[Finding] = []
        for checker, text, dictionary, outcome, verdict in wait_for_verdicts(transcript_path, jobs, seconds):
            if outcome == "hit":
                findings.append(_finding(checker, text, dictionary, verdict))
            elif outcome == "unchecked":
                reason = str(verdict.get("reason") or "the judge gave no answer in time")
                _record_unchecked(event, checker, text, reason, mode, mode_source)
                print(UNCHECKED_MESSAGE.format(why=reason), file=sys.stderr)
        return findings
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return []


def _check_reply(payload: dict[str, object]) -> tuple[str, str, list[tuple[str, str]]] | None:
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not isinstance(message, str) or not isinstance(transcript_path, str):
        return None
    if not message or not transcript_path or not os.path.isfile(transcript_path):
        return None
    humans, tool_uses = read_transcript(transcript_path)
    pending = pending_requests(message, humans, tool_uses)
    if not pending:
        return None
    return message, transcript_path, pending


def wait_seconds() -> float:
    raw = os.environ.get(WAIT_ENV)
    if raw is None:
        return DEFAULT_WAIT_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        print(f"{HOOK}: {WAIT_ENV}={raw!r} is not a number; waiting {DEFAULT_WAIT_SECONDS}s", file=sys.stderr)
        return DEFAULT_WAIT_SECONDS


def wait_for_verdict(transcript: str, job_id: str, seconds: float) -> tuple[str, dict]:
    deadline = time.monotonic() + seconds
    while True:
        verdict = take_verdict(transcript, job_id)
        if verdict is not None:
            return str(verdict.get("outcome") or "unchecked"), verdict
        if time.monotonic() >= deadline:
            return "unchecked", {
                "id": job_id,
                "outcome": "unchecked",
                "reason": "the judge gave no answer in time",
            }
        time.sleep(POLL_SECONDS)


def wait_for_verdicts(
    transcript: str,
    jobs: list[tuple[str, str, dict, str]],
    seconds: float,
) -> list[tuple[str, str, dict, str, dict]]:
    deadline = time.monotonic() + seconds
    pending = list(jobs)
    verdicts: list[tuple[str, str, dict, str, dict]] = []
    while pending:
        next_pending = []
        for checker, text, dictionary, job_id in pending:
            verdict = take_verdict(transcript, job_id)
            if verdict is None:
                next_pending.append((checker, text, dictionary, job_id))
                continue
            verdicts.append((checker, text, dictionary, str(verdict.get("outcome") or "unchecked"), verdict))
        pending = next_pending
        if not pending:
            break
        if time.monotonic() >= deadline:
            for checker, text, dictionary, job_id in pending:
                verdicts.append((
                    checker,
                    text,
                    dictionary,
                    "unchecked",
                    {
                        "id": job_id,
                        "outcome": "unchecked",
                        "reason": "the judge gave no answer in time",
                    },
                ))
            break
        time.sleep(POLL_SECONDS)
    return verdicts


def take_verdict(transcript: str, job_id: str) -> dict | None:
    judge = _judge()
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
            print(f"{HOOK}: could not remove {taken}: {exc}", file=sys.stderr)
    return loaded if isinstance(loaded, dict) else {"id": job_id, "outcome": "unchecked", "reason": "verdict is not an object"}


def _finding(checker: str, text: str, dictionary: dict, verdict: dict) -> Finding:
    answer = verdict.get("answer") if isinstance(verdict, dict) else None
    evidence = json.dumps(answer, sort_keys=True) if isinstance(answer, dict) else str(verdict.get("reason") or "")
    return Finding(
        rule_id=RULE_IDS[checker],
        subject=_subject(text),
        message=dictionary["on_hit"],
        evidence=evidence,
    )


def _record_unchecked(
    event: dict[str, object],
    checker: str,
    text: str,
    reason: str,
    mode: str,
    mode_source: str,
) -> None:
    finding = Finding(
        rule_id=RULE_IDS[checker],
        subject=_subject(text),
        message=UNCHECKED_MESSAGE.format(why=reason),
        evidence=reason,
    )
    write_events(HOOK, "claude", event, [finding], mode, mode_source, 0, action="unchecked")


def _subject(text: str) -> str:
    return "request:" + uuid.uuid5(uuid.NAMESPACE_URL, text).hex
