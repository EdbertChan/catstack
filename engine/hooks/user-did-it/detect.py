"""user-did-it: the user did by hand a step the agent could have done.

Whether the user's new message reports such a step (ran a command in their
own terminal and pasted the output, edited a file, pasted a fix) is meaning,
so the background judge decides it from the `user-did-it` phrase dictionary.
What stays here is shape only: which prompts are the person at all.

Never blocks. A hit arrives on a later turn through the llm-judge inbox.
Off unless CATSTACK_REFLECT_ENFORCEMENT is on. A payload with no readable
prompt is reported on stderr as unchecked, never treated as clean.
"""
from __future__ import annotations

import functools
import importlib.util
import os
import sys
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_flags"))

from flags import enforcement_gate  # noqa: E402

CHECKER = "user-did-it"

SYSTEM_INJECTED_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "<user-prompt-submit-hook",
    "[SYSTEM NOTIFICATION",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
    "Stop hook feedback:",
    "PreToolUse hook",
    "PostToolUse hook",
    "UserPromptSubmit hook",
)


def is_person(prompt: str) -> bool:
    text = prompt.lstrip()
    if not text:
        return False
    return not text.startswith(SYSTEM_INJECTED_PREFIXES)


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


def enqueue_judge(payload: dict, stderr=None) -> str | None:
    """Enqueue one judge job for the user's new message; return its id."""
    payload = payload if isinstance(payload, dict) else {}
    if not enforcement_gate(CHECKER, payload.get("cwd")):
        return None
    prompt = payload.get("prompt")
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not isinstance(prompt, str) or not transcript_path:
        (stderr or sys.stderr).write(
            f"catstack-hook-unchecked {CHECKER}: payload has no prompt text or transcript path\n"
        )
        return None
    if not is_person(prompt):
        return None
    dictionary = _phrases().load(CHECKER)
    job = _phrases().job(dictionary, transcript_path, prompt)
    job["id"] = uuid.uuid4().hex
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error {CHECKER}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
