"""hedge-runs-prove-it: a hedge about code or repo state is a prompt to verify.

"I think", "I believe", "probably", "should work", "presumably", or an
`UNVERIFIED:` prefix next to a code noun (a path, a backticked name, test,
CI, build, bug, fix, script, hook, PR, merge, branch, commit) means the
agent has a check it has not run. The reply passes only when the turn ran
a verification tool (Bash, Read, Grep, Glob) or the `UNVERIFIED:` clause
says why it cannot be verified ("cannot verify: no network"). Hedges about
things that are not code or state (a company's motive, a filing date)
are out of scope. Judgment stays with the model; this file matches
shapes and fails open.
"""
from __future__ import annotations

import json
import re

HEDGE_RE = re.compile(
    r"\bI think\b|\bI believe\b|\bprobably\b|\bshould work\b|\bpresumably\b|"
    r"\bI suspect\b|\bI'?d guess\b|\bmy guess is\b|\bUNVERIFIED:",
    re.IGNORECASE,
)
CODE_NOUN_RE = re.compile(
    r"`[^`\n]+`|\b[\w./-]+\.(?:py|ts|js|mjs|sh|json|yml|yaml|md|toml|mdc)\b|"
    r"\b(?:tests?|CI|build|bug|fix(?:ed|es)?|script|hook|PRs?|merge[ds]?|branch|commit|"
    r"worktree|tree|repo|function|module|config|install|deploy|pipeline|gate|suite|"
    r"error|exception|traceback|import|dependency|symlink|file)\b",
    re.IGNORECASE,
)
REASON_RE = re.compile(
    r"\b(?:cannot|can'?t|could not|couldn'?t|unable to|no way to|not possible to|"
    r"would need|requires|needs|without|not run|did not run|didn'?t run|no access|"
    r"no network|offline|not reachable|sandbox)\b",
    re.IGNORECASE,
)
PROXIMITY = 200
VERIFY_TOOLS = {"Bash", "Read", "Grep", "Glob", "Monitor", "WebFetch"}
QUOTED_BEFORE = ('"', "'", "`")

MESSAGE = (
    "hedge-runs-prove-it: this reply hedges about code or repo state ({hedge}) and "
    "the turn ran no verification (no Bash / Read / Grep). Run prove-it now: verify in "
    "this turn, or write `UNVERIFIED: <claim> -- cannot verify: <reason>`."
)


def _sentence_after(text: str, start: int) -> str:
    end = len(text)
    for stop in (".\n", "\n\n"):
        idx = text.find(stop, start)
        if idx != -1:
            end = min(end, idx)
    return text[start:end]


def code_hedges(text: str) -> list[str]:
    """Hedge phrases near a code noun that lack a cannot-verify reason."""
    hits: list[str] = []
    for match in HEDGE_RE.finditer(text or ""):
        if match.start() and text[match.start() - 1] in QUOTED_BEFORE:
            continue
        window = text[max(0, match.start() - PROXIMITY): match.end() + PROXIMITY]
        if not CODE_NOUN_RE.search(window):
            continue
        if match.group(0).upper().startswith("UNVERIFIED") and REASON_RE.search(_sentence_after(text, match.end())):
            continue
        hits.append(match.group(0))
    return hits


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    text = _text_content(data)
    return bool(text.strip()) and not text.lstrip().startswith("<")


def parse_lines(raw_lines) -> list[dict]:
    parsed: list[dict] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def verified_this_turn(lines: list[dict]) -> bool:
    turn_start = 0
    for i, data in enumerate(lines):
        if _is_human_user_line(data):
            turn_start = i
    for data in lines[turn_start:]:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in VERIFY_TOOLS:
                return True
    return False


def decide_from_lines(message: str, lines: list[dict]) -> str | None:
    hedges = code_hedges(message)
    if not hedges:
        return None
    if verified_this_turn(lines):
        return None
    return MESSAGE.format(hedge=", ".join(f'"{h}"' for h in hedges[:3]))


def decide(payload: dict) -> str | None:
    """Return blocking feedback for the Stop event, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not code_hedges(message):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    lines: list[dict] = []
    if transcript_path:
        try:
            with open(transcript_path, encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return None
    return decide_from_lines(message, lines)
