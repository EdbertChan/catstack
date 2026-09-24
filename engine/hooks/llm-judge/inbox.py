#!/usr/bin/env python3
from __future__ import annotations

import json
import os

import judge

NO_TRANSCRIPT = "llm-judge: {harness} payload has no transcript path, so finished verdicts were not checked"
REPORT_LIMIT = 600


def resolve_transcript(payload: dict) -> str:
    direct = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
    )
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        conv = conv.strip()
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            projects = os.listdir(root)
        except OSError as exc:
            judge.log(f"inbox: could not list {root} to find conversation {conv}: {exc}")
            return ""
        for project in projects:
            candidate = os.path.join(root, project, "agent-transcripts", conv, f"{conv}.jsonl")
            if os.path.isfile(candidate):
                return candidate
    return ""


def _turn_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _turn_role(data: dict) -> str:
    message = data.get("message")
    role = message.get("role") if isinstance(message, dict) else None
    return role or data.get("type") or ""


def _is_tool_result_row(data: dict) -> bool:
    """True for a user-shaped row that is only a tool's output.

    Claude Code files every tool result as `type: "user"` with neither
    `isMeta` nor `isSidechain` on it; what it does carry is a `tool_result`
    content block plus a `toolUseResult` field beside the message. Reading
    that is the same move `engine/hooks/agent-relay-attribution/detect.py:76`
    and `engine/hooks/wrong-check-reflect/detect.py:80` make.
    """
    if data.get("toolUseResult") is not None:
        return True
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _is_harness_row(data: dict) -> bool:
    """True for a row that is not the person or the main agent speaking.

    The harness files its own injections as ordinary `user` or `assistant`
    rows: hook feedback, a skill body, a helper agent's own turns, a tool
    result. Each carries a record saying so -- `isMeta`, `isSidechain`, or an
    agent id -- so the judge prompt reads that record instead of quoting hook
    text back as the last human message or a helper agent's line as the last
    assistant reply.
    """
    if data.get("isMeta") or data.get("isSidechain") or data.get("is_sidechain"):
        return True
    if data.get("agentId") or data.get("agent_id"):
        return True
    return _is_tool_result_row(data)


def _reverse_lines(path: str):
    size = os.path.getsize(path)
    remainder = b""
    with open(path, "rb") as handle:
        position = size
        while position > 0:
            step = min(1024 * 1024, position)
            position -= step
            handle.seek(position)
            lines = (handle.read(step) + remainder).split(b"\n")
            remainder = lines.pop(0)
            yield from reversed(lines)
        if remainder:
            yield remainder


def last_turn(transcript_path: str) -> tuple[str, str]:
    last_human = ""
    last_assistant = ""
    try:
        for raw in _reverse_lines(transcript_path):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if not isinstance(data, dict) or _is_harness_row(data):
                continue
            text = _turn_text(data)
            if not text.strip():
                continue
            role = _turn_role(data)
            if role == "user" and not last_human:
                last_human = text
            elif role == "assistant" and not last_assistant:
                last_assistant = text
            if last_human and last_assistant:
                break
    except OSError as exc:
        judge.log(f"inbox: could not read {transcript_path} for its last turn: {exc}")
    return last_human, last_assistant


def judge_prompt(rule_text: str, transcript_path: str) -> str:
    human, assistant = last_turn(transcript_path)
    return judge.build_prompt(rule_text, assistant, human)


def is_subagent_event(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("agent_id") or payload.get("isSidechain") or payload.get("is_sidechain"):
        return True
    return judge.is_subagent_transcript(resolve_transcript(payload))


def enqueue_judge(job_fields: dict, payload: dict) -> str | None:
    if is_subagent_event(payload):
        return None
    transcript = resolve_transcript(payload)
    if not transcript:
        return None
    job = dict(job_fields)
    rule_text = job.pop("rule_text", "")
    job["transcript"] = transcript
    job["prompt"] = judge_prompt(rule_text, transcript)
    return judge.enqueue(job)


def unchecked_message(item: dict) -> str:
    hook = item.get("hook") or "unknown hook"
    attempts = item.get("attempts") or []
    tried = "; ".join(f"{a.get('runner')}: {a.get('reason')}" for a in attempts if isinstance(a, dict))
    return f"llm-judge: {hook} could not judge the last reply: {tried or item.get('reason') or 'no reason recorded'}"


def messages(transcript: str) -> list[str]:
    out = []
    for item in judge.drain(transcript):
        outcome = item.get("outcome")
        if outcome == "clean":
            continue
        if outcome == "hit":
            text = item.get("on_hit")
            if not isinstance(text, str) or not text.strip():
                text = f"llm-judge: {item.get('hook') or 'unknown hook'} flagged the last reply: {item.get('reason')}"
            answer = item.get("answer")
            if isinstance(answer, dict):
                report = answer.get("report")
                if isinstance(report, str) and report.strip():
                    text = f"{text} {report.strip()[:REPORT_LIMIT]}"
            out.append(text)
            continue
        out.append(unchecked_message(item))
    return out
