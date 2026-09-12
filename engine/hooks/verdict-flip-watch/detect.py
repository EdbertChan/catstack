"""Backstop layer: a check that passed earlier and failed later makes any claim
made off the earlier run stale -- whether or not the model noticed.

Three layers guard self-correction, weakest dependency last:

1. `wrong-check-reflect` matches the SHAPE of a retraction in the outgoing
   text. It only fires once the model has already decided to admit something.
2. `principle-flag-your-own-corrections` carries the judgment no regex can
   enumerate. It still requires the model to realise a claim went stale.
3. This hook requires neither. It reads the transcript's own command results.
   If `scripts/x.py` printed ok at one point and failed later, the earlier
   "green" was wrong as a matter of record, and the only question is whether
   this message says so.

That third property is the point: it catches the silent switch to the
corrected value, which `principle-flag-your-own-corrections` names as the real
failure -- the user cannot tell a silent correction from consistency.

Advisory: stderr plus exit 0. A gate can legitimately start failing because
the turn broke something on purpose, so this informs rather than blocks.
Fail-open on any parse or IO error.

VERIFIER_RE is what counts as a command worth tracking: a checker, test runner,
or build. Tracking every `ls` and `git status` would make a flip meaningless.

ACKNOWLEDGED_RE is the outgoing message already owning the flip: a correction
marker, or the word stale/vacuous near the verdict. It reuses the
wrong-check-reflect vocabulary.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_flags"))

from flags import enforcement_gate  # noqa: E402

STATE_DIR = os.environ.get(
    "VERDICT_FLIP_WATCH_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-verdict-flip-watch"),
)

VERIFIER_RE = re.compile(
    r"(?:^|[\s/])(?:check_|test_|run_)|"
    r"\b(?:pytest|unittest|npm\s+(?:test|run\s+\w*test\w*)|pnpm\s+(?:test|run)|"
    r"cargo\s+test|go\s+test|make\s+(?:test|check)|tox|jest|vitest|preflight)\b",
    re.IGNORECASE,
)
SCRIPTISH_RE = re.compile(r"[\w./-]+\.(?:py|sh|mjs|js|ts)\b")

FAIL_RE = re.compile(
    r"(?:^|\n)\s*(?:fail|FAILED|ERROR)\b|\bTraceback\b|\bFAILED\s*\(|"
    r"\bexit(?:\s*code)?[\s=:]+[1-9]\b|\bassertionerror\b",
    re.IGNORECASE,
)
PASS_RE = re.compile(
    r"(?:^|\n)\s*ok\b|\bOK\s*$|\bpassed\b|\ball\s+\d+\s+\w+\s+(?:passed|ok)\b|"
    r"\bexit(?:\s*code)?[\s=:]+0\b",
    re.IGNORECASE | re.MULTILINE,
)

ACKNOWLEDGED_RE = re.compile(
    r"(?i)\b(?:wrong|incorrect|vacuous|stale|retract(?:ing|ed)?|mistaken|"
    r"misread|premature|no\s+longer\s+(?:true|holds)|"
    r"does(?:n'?t|\s+not)\s+hold|now\s+fails|started\s+failing|"
    r"earlier\s+(?:run|pass|result|claim))\b"
)

MESSAGE = (
    "verdict-flip-watch: `{target}` passed earlier in this session and failed "
    "later, and this message does not mention it. Any status reported off the "
    "earlier run is stale. Say which claim is affected and what changed, then "
    "follow principle-flag-your-own-corrections (the admission is a reflect "
    "trigger, not just a sentence). If the flip is expected because this turn "
    "broke it on purpose, say that instead."
)


def _blocks(data: dict) -> list:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []


def normalize_target(command: str) -> str | None:
    """The thing being verified, so two runs of it can be compared."""
    if not VERIFIER_RE.search(command or ""):
        return None
    script = SCRIPTISH_RE.search(command)
    if script:
        return script.group(0)
    words = (command or "").split()
    return " ".join(words[:2]) if words else None


def classify(output: str) -> str:
    """'fail' wins over 'pass': a run can print ok lines and still fail."""
    if FAIL_RE.search(output or ""):
        return "fail"
    if PASS_RE.search(output or ""):
        return "pass"
    return "unknown"


def result_text(data: dict) -> str:
    out: list[str] = []
    for block in _blocks(data):
        if not isinstance(block, dict) or block.get("type") != "tool_result":
            continue
        content = block.get("content")
        if isinstance(content, str):
            out.append(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and isinstance(part.get("text"), str):
                    out.append(part["text"])
    return "\n".join(out)


def verdicts(transcript_path: str) -> list[tuple[str, str]]:
    """(target, 'pass'|'fail') in transcript order. [] when unreadable."""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return []
    pending: list[str] = []
    found: list[tuple[str, str]] = []
    for raw in lines:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        if data.get("type") == "assistant":
            for block in _blocks(data):
                if (
                    isinstance(block, dict)
                    and block.get("type") == "tool_use"
                    and block.get("name") == "Bash"
                ):
                    command = (block.get("input") or {}).get("command")
                    target = normalize_target(command) if isinstance(command, str) else None
                    if target:
                        pending.append(target)
            continue
        text = result_text(data)
        if not text or not pending:
            continue
        verdict = classify(text)
        target = pending.pop(0)
        if verdict != "unknown":
            found.append((target, verdict))
    return found


def find_flip(transcript_path: str) -> str | None:
    """A target that passed and then later failed, else None."""
    passed: set[str] = set()
    for target, verdict in verdicts(transcript_path):
        if verdict == "pass":
            passed.add(target)
        elif verdict == "fail" and target in passed:
            return target
    return None


def _state_file(transcript_path: str, target: str) -> str:
    key = f"{os.path.abspath(transcript_path or 'none')}::{target}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return os.path.join(STATE_DIR, f"{digest}.noted")


def already_noted(transcript_path: str, target: str) -> bool:
    return os.path.isfile(_state_file(transcript_path, target))


def mark_noted(transcript_path: str, target: str) -> None:
    path = _state_file(transcript_path, target)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(target + "\n")
    except OSError:
        pass


def decide(payload: dict) -> str | None:
    if not enforcement_gate("verdict-flip-watch", payload.get("cwd")):
        return None
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if ACKNOWLEDGED_RE.search(message):
        return None
    transcript_path = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
        or ""
    )
    if not transcript_path:
        return None
    try:
        target = find_flip(transcript_path)
    except Exception:
        return None
    if not target or already_noted(transcript_path, target):
        return None
    mark_noted(transcript_path, target)
    return MESSAGE.format(target=target)
