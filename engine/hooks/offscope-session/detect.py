"""offscope-session: the new prompt has left this session's running scope.

A session that pivots to a genuinely unrelated task keeps re-sending the
finished work's context on every later turn, where it is paid for again and
competes for attention. Whether a new prompt is that pivot is a meaning, not
a word, so the shared llm-judge decides it from the `offscope-session` phrase
dictionary: the running scope (the human messages and each turn's final reply,
newest-first inside a size budget) goes in one side, the new prompt the other.

The judge runs in the background, so the verdict arrives on the next human
prompt, never in the turn that asked. Three outcomes: drift-hit, on-scope,
and unchecked. A verdict that is neither a clean hit nor a clean miss --
malformed JSON, a missing key, an errored job, no model command installed --
is unchecked and is never coerced to on-scope. Fails open on any error.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import sys
import uuid

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(HOOK_DIR)
LLM_JUDGE_DIR = os.path.join(HOOKS_DIR, "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

try:
    from events import is_human_prompt
    from finding import Finding
except ImportError:
    from pathlib import Path

    SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
    sys.path.insert(0, str(SDK_DIR))
    from events import is_human_prompt
    from finding import Finding

HOOK = "offscope-session"
CHECKER = "offscope-session"
ANSWER_KEY = "offscope"
REQUEST_KEY = "offscope_request"

RULE_DRIFT_HIT = "offscope-session.drift-hit"
RULE_ON_SCOPE = "offscope-session.on-scope"
RULE_UNCHECKED = "offscope-session.unchecked"

PROMPT_EVENTS = frozenset({"UserPromptSubmit", "user_prompt_submit", "beforeSubmitPrompt"})

SCOPE_BUDGET_CHARS = 24_000
REQUEST_BUDGET_CHARS = 8_000
"""How much of the conversation, and of the new prompt, the judge is shown.

Both are character counts. The judge hands its whole prompt to a runner as one
command-line argument, which stops working somewhere near 128 KB on Linux and
comes back `unchecked`, so the two budgets together stay far under that: a long
session or a pasted log can never cost the answer.
"""
WHY_CLIP = 300
REASON_CLIP = 300

ON_SCOPE_MESSAGE = (
    "offscope-session: the last prompt is still the same work (a follow-up, a correction, a "
    "narrowing, a test, or the next step). Nothing to do."
)
UNCHECKED_MESSAGE = (
    "offscope-session: the judge could not decide whether the last prompt left this session's "
    "running scope, so that prompt is unchecked, not on scope. Reason: {reason}"
)
DEFAULT_ON_HIT = (
    "offscope-session: this prompt starts work with nothing left in common with the work so far. "
    "Suggest a /clear or a fresh session before starting it."
)


def channel(transcript: str) -> str:
    """The judge inbox this hook owns.

    Verdicts are addressed by transcript, and `drain` deletes what it reads, so
    draining the bare transcript path would swallow the llm-judge inbox's
    messages for every other hook in the same session. The suffix keeps this
    hook's verdicts in a folder only this hook drains.
    """
    return f"{transcript}#{HOOK}"


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


def prompt_text(event: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return ""


def transcript_path(event: dict) -> str:
    for key in ("transcript_path", "transcriptPath"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _message_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    return "\n".join(
        str(block.get("text") or "")
        for block in content
        if isinstance(block, dict) and block.get("type") in {"text", "input_text", "output_text"}
    )


def _role(data: dict) -> str:
    entry_type = data.get("type")
    if entry_type in {"user", "assistant"}:
        return str(entry_type)
    message = data.get("message")
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(data.get("role") or "")


def turns(transcript: str) -> list[list[str]]:
    """`[human message, that turn's final assistant reply]` pairs, oldest first.

    Only what a person typed opens a turn: a task notification, a slash-command
    expansion, and a system block are not scope. Tool calls and tool results
    carry no prose worth judging, so only the turn's last text reply is kept.
    """
    collected: list[list[str]] = []
    try:
        with open(transcript, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                role = _role(data)
                text = _message_text(data)
                if not text.strip():
                    continue
                if role == "user":
                    if is_human_prompt({"prompt": text}):
                        collected.append([text, ""])
                elif role == "assistant" and collected:
                    collected[-1][1] = text
    except (OSError, UnicodeError) as exc:
        print(f"catstack-hook-error {HOOK}: could not read transcript {transcript}: {exc}", file=sys.stderr)
        return []
    return collected


def _block(human: str, reply: str) -> str:
    lines = [f"USER: {human.strip()}"]
    if reply.strip():
        lines.append(f"ASSISTANT: {reply.strip()}")
    return "\n".join(lines)


def running_scope(transcript: str, current_prompt: str = "") -> str:
    """The work so far, newest-first inside `SCOPE_BUDGET_CHARS`, rendered oldest first.

    The window is filled from the newest turn backwards, so what falls off the
    end is always the oldest context: scope moves forward, and the turn the new
    prompt has to be compared against is the most recent one, not the first.
    """
    collected = turns(transcript)
    if (
        collected
        and current_prompt.strip()
        and collected[-1][0].strip() == current_prompt.strip()
        and not collected[-1][1].strip()
    ):
        collected.pop()
    kept: list[str] = []
    used = 0
    for human, reply in reversed(collected):
        block = _block(human, reply)
        room = SCOPE_BUDGET_CHARS - used
        if len(block) > room:
            if not kept and room > 0:
                kept.append(block[-room:])
            break
        kept.append(block)
        used += len(block)
    kept.reverse()
    return "\n\n".join(kept)


def judge_prompt(dictionary: dict, scope: str, request: str) -> str:
    """One line of JSON, and the on-scope/off-scope distinction said out loud."""
    return "\n".join(
        [
            f'Return exactly one line of JSON: {{"{ANSWER_KEY}": true|false, "why": "<one short sentence>"}}',
            f"Question: {dictionary['meaning']}",
            f'Answer "{ANSWER_KEY}": false when THE NEW REQUEST is a follow-up, a correction, a '
            "narrowing, a test of the same work, a write-up of the work just done, or a natural "
            "next step of the same work. Terse, blunt, or abrupt wording does not make it off scope.",
            f'Answer "{ANSWER_KEY}": true only when THE NEW REQUEST is a genuinely unrelated task: '
            "a different incident, a different deliverable, nothing left in common with what came "
            "before.",
            f"Off-scope examples: {json.dumps(dictionary['match'], ensure_ascii=False)}",
            f"On-scope examples: {json.dumps(dictionary['not_match'], ensure_ascii=False)}",
            "The examples are examples of the meaning, not a checklist of exact words.",
            "THE WORK SO FAR (oldest first; older turns may have been cut):",
            scope,
            "THE NEW REQUEST:",
            str(request)[-REQUEST_BUDGET_CHARS:],
        ]
    )


def build_job(event: dict) -> dict | None:
    """Enqueue one off-scope question about this human prompt; return the job.

    Returns None, and judges nothing, when the prompt is not a person's, when
    there is no transcript to compare against, or when the session has no
    running scope yet (the first message cannot leave a scope that does not
    exist).

    The job carries the request verbatim under `REQUEST_KEY`, so whatever acts
    on a hit later seeds the new session from what the person actually typed
    instead of deriving it a second time from a transcript that has moved on.
    """
    if not isinstance(event, dict) or not is_human_prompt(event):
        return None
    prompt = prompt_text(event)
    transcript = transcript_path(event)
    if not prompt or not transcript:
        print(
            f"catstack-hook-unchecked {HOOK}: payload has no prompt text or transcript path, "
            "so this prompt was not judged",
            file=sys.stderr,
        )
        return None
    judge = _judge()
    if judge.is_subagent_payload(event):
        return None
    scope = running_scope(transcript, prompt)
    if not scope.strip():
        return None
    dictionary = _phrases().load(CHECKER)
    job = {
        "id": uuid.uuid4().hex,
        "hook": HOOK,
        "rule_id": RULE_DRIFT_HIT,
        "transcript": channel(transcript),
        "prompt": judge_prompt(dictionary, scope, prompt),
        "hit_if_all_true": [ANSWER_KEY],
        "on_hit": dictionary["on_hit"],
        REQUEST_KEY: prompt,
    }
    if judge.enqueue(job) is None:
        print(
            f"catstack-hook-unchecked {HOOK}: the judge refused the job (running inside a judge "
            "or a subagent), so this prompt was not judged",
            file=sys.stderr,
        )
    return job


def _unchecked(subject: str, reason: str) -> Finding:
    detail = (reason or "the judge gave no reason").strip()[:REASON_CLIP]
    message = UNCHECKED_MESSAGE.format(reason=detail)
    return Finding(rule_id=RULE_UNCHECKED, subject=subject, message=message, evidence=detail)


def verdict_finding(verdict: dict) -> Finding:
    """One drained verdict as exactly one finding. Anything unclear is unchecked."""
    subject = f"job:{verdict.get('id') or 'unknown'}"
    outcome = verdict.get("outcome")
    answer = verdict.get("answer")
    reason = str(verdict.get("reason") or "")
    if outcome == "unchecked":
        return _unchecked(subject, reason)
    if not isinstance(answer, dict) or not isinstance(answer.get(ANSWER_KEY), bool):
        return _unchecked(subject, f"the judge's answer carried no {ANSWER_KEY} true/false: {answer!r}")
    if outcome == "hit" and answer[ANSWER_KEY] is True:
        message = str(verdict.get("on_hit") or DEFAULT_ON_HIT)
        why = answer.get("why")
        if isinstance(why, str) and why.strip():
            message = f"{message} The judge's reason: {why.strip()[:WHY_CLIP]}"
        return Finding(rule_id=RULE_DRIFT_HIT, subject=subject, message=message, evidence=reason)
    if outcome == "clean" and answer[ANSWER_KEY] is False:
        return Finding(rule_id=RULE_ON_SCOPE, subject=subject, message=ON_SCOPE_MESSAGE, evidence=reason)
    return _unchecked(subject, f"outcome {outcome!r} does not match {ANSWER_KEY} {answer.get(ANSWER_KEY)!r}")


def report(event: dict) -> list[Finding]:
    """Every verdict waiting for this transcript, as findings. One turn late."""
    if not isinstance(event, dict) or not is_human_prompt(event):
        return []
    transcript = transcript_path(event)
    if not transcript:
        print(
            f"catstack-hook-unchecked {HOOK}: payload has no transcript path, so no verdict was "
            "collected",
            file=sys.stderr,
        )
        return []
    return [verdict_finding(verdict) for verdict in _judge().drain(channel(transcript))]


def _is_prompt_event(event: dict) -> bool:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value in PROMPT_EVENTS
    return True


def detect(event: dict[str, object]) -> list[Finding]:
    """Report the previous prompt's verdict, then ask about this one.

    Both halves fail open on their own: a judge that cannot be loaded, a
    transcript that cannot be read, or a verdict folder that cannot be claimed
    is named on stderr and costs nothing but this one check.
    """
    if not isinstance(event, dict) or not _is_prompt_event(event):
        return []
    findings: list[Finding] = []
    try:
        findings = report(event)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: verdict report failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        build_job(event)
    except Exception as exc:
        print(f"catstack-hook-error {HOOK}: judge job failed: {type(exc).__name__}: {exc}", file=sys.stderr)
    return findings
