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


def last_turn(transcript_path: str) -> tuple[str, str]:
    last_human = ""
    last_assistant = ""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(data, dict):
                    continue
                text = _turn_text(data)
                if not text.strip():
                    continue
                role = _turn_role(data)
                if role == "user":
                    last_human = text
                elif role == "assistant":
                    last_assistant = text
    except OSError as exc:
        judge.log(f"inbox: could not read {transcript_path} for its last turn: {exc}")
    return last_human, last_assistant


def judge_prompt(rule_text: str, transcript_path: str) -> str:
    human, assistant = last_turn(transcript_path)
    return judge.build_prompt(rule_text, assistant, human)


def is_subagent_event(payload: dict) -> bool:
    if not isinstance(payload, dict):
        return False
    if judge.subagent_flags(payload):
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
    job.update(judge.subagent_flags(payload))
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
