"""Per-session scope-correction detector and tool gate.

The first correction requires an explicit, one-line scope contract before
side-effecting or external tools. A second correction in the same class hard
stops every tool until the user explicitly invokes both /reflect and
automate-me. State is keyed to the harness session, not the repository.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from typing import Any

STATE_DIR = os.environ.get(
    "SCOPE_LOCK_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-scope-lock"),
)

EXPANSION_RE = re.compile(
    r"(?i)\b(?:expand|broaden|extend)\s+(?:the\s+)?scope\b|"
    r"\b(?:also|additionally)\s+(?:add|include|handle|do|cover)\b|"
    r"\binclude\s+.+\s+(?:too|as well)\b"
)

SCOPE_CORRECTION_PATTERNS = (
    re.compile(r"(?i)\bwhat (?:the hell |the fuck )?are (?:we|you) doing\b"),
    re.compile(r"(?i)\bwhy did you (?:expand|drift|switch|change|start)\b"),
    re.compile(r"(?i)\b(?:you(?:'re| are)|we(?:'re| are)) (?:repeatedly )?drifting\b"),
    re.compile(r"(?i)\bstop (?:the )?(?:scope )?drift(?:ing)?\b"),
    re.compile(r"(?i)\bthat(?:'s| is) not what i (?:asked|said|wanted)\b"),
    re.compile(r"(?i)\ball i(?:'m| am) asking\b|\ball i(?:'ve| have) (?:ever )?asked\b"),
    re.compile(r"(?i)\bi (?:only|just) asked (?:you )?to\b"),
    re.compile(r"(?i)\bjust (?:fix|do|change|implement|run|land|merge) (?:it|this|that) locally\b"),
    re.compile(r"(?i)\bdo (?:it|this|that) locally\b"),
    re.compile(r"(?i)\bdon't use invoker\b|\bdo not use invoker\b"),
)

# Slash optional: a harness's own CLI can intercept a leading "/reflect" as
# an unrecognized command before it ever reaches this hook (observed: Codex
# CLI prints "Unrecognized command '/reflect'" and never runs the hook),
# permanently stranding a hard_stop session that has no other exit. Bare
# "reflect" still requires AUTOMATE_RE alongside it, so the false-positive
# rate stays low even without the slash anchor.
REFLECT_RE = re.compile(r"(?i)(?:^|\s)/?reflect\b")
AUTOMATE_RE = re.compile(r"(?i)(?:^|\s)/?automate-me\b|\bautomate me\b")
CONTRACT_RE = re.compile(r"(?m)^SCOPE CONTRACT: ([^\r\n]{3,500})$")

# An automated task/subagent-completion notification is relayed into the
# same UserPromptSubmit pipeline as a "user" turn, but no human typed it --
# it can quote arbitrary prior text verbatim, including a past scope
# correction or this hook's own gate copy. Never let it drive state.
AUTOMATED_NOTIFICATION_RE = re.compile(r"^\s*<task-notification>")

# A genuine live correction is always near the edges of what a human just
# typed. A long message is usually a paste (a log, a transcript) with the
# real instruction at the very start or end, not buried in the middle --
# and the paste can itself quote a *different* session's own trigger
# phrases verbatim. Observed on a real session: a pasted Codex transcript
# contained "do not use Invoker" as quoted dialogue 689 chars from the end
# of a 101,873-char message, which this hook matched as if it were a live
# directive. Bound the scan to the tail so a big paste's quoted noise
# can't reach it; short interactive messages are unaffected.
CORRECTION_SCAN_TAIL_CHARS = 400

# Bash is intentionally not in this allowlist: even a command that looks
# read-only can contain redirects, substitutions, or a second mutation.
LOCAL_READ_ONLY_TOOLS = {
    "read",
    "grep",
    "glob",
    "ls",
    "view",
    "viewimage",
    "view_image",
    "listfiles",
}

FIRST_GATE = (
    "Scope correction recorded. Before mutating or external tools, write exactly one "
    "standalone line: `SCOPE CONTRACT: <the requested outcome and explicit non-goals>`, "
    "then end this turn with no further tool calls. The check re-reads it from a prior "
    "completed turn, so writing it and calling a tool in the same turn will not clear "
    "this gate. An apology or plain restatement does not clear this gate either."
)
HARD_GATE = (
    "Second scope correction in this session: all tools are stopped. Do not continue the "
    "task or clear this with an apology/restatement. The user must explicitly invoke both "
    "`/reflect` and `automate-me`; then address the drift before resuming."
)


def extract_prompt_text(payload: dict[str, Any]) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    return ""


def correction_class(text: str) -> str | None:
    """Return the stable correction class, excluding explicit expansions."""
    if not text or AUTOMATED_NOTIFICATION_RE.match(text):
        return None
    window = text[-CORRECTION_SCAN_TAIL_CHARS:]
    if EXPANSION_RE.search(window):
        return None
    if any(pattern.search(window) for pattern in SCOPE_CORRECTION_PATTERNS):
        return "scope"
    return None


def reflection_invoked(text: str) -> bool:
    if not text or AUTOMATED_NOTIFICATION_RE.match(text):
        return False
    return bool(REFLECT_RE.search(text) and AUTOMATE_RE.search(text))


def _session_identity(payload: dict[str, Any]) -> str:
    for key in (
        "session_id",
        "sessionId",
        "conversation_id",
        "conversationId",
        "transcript_path",
        "transcriptPath",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return f"{key}:{value.strip()}"
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip():
        return f"cwd:{cwd.strip()}"
    return ""


def state_path(payload: dict[str, Any]) -> str:
    identity = _session_identity(payload)
    if not identity:
        return ""
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return os.path.join(STATE_DIR, f"{digest}.json")


def load_state(payload: dict[str, Any]) -> dict[str, Any]:
    path = state_path(payload)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(payload: dict[str, Any], state: dict[str, Any]) -> None:
    path = state_path(payload)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix="scope-lock-", dir=os.path.dirname(path))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
    except OSError:
        try:
            os.unlink(temp_path)
        except (OSError, UnboundLocalError):
            pass


def _transcript_path(payload: dict[str, Any]) -> str:
    value = payload.get("transcript_path") or payload.get("transcriptPath")
    return value if isinstance(value, str) else ""


def _line_count(path: str) -> int:
    try:
        with open(path, encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except OSError:
        return 0


def _assistant_text(data: dict[str, Any]) -> str:
    if data.get("type") != "assistant":
        return ""
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text") or "")
            for block in content
            if isinstance(block, dict) and block.get("type") in {"text", "output_text"}
        )
    return ""


def recorded_contract(payload: dict[str, Any], after_line: int) -> str:
    path = _transcript_path(payload)
    if not path:
        return ""
    try:
        with open(path, encoding="utf-8") as handle:
            for index, line in enumerate(handle, start=1):
                if index <= after_line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict):
                    continue
                match = CONTRACT_RE.search(_assistant_text(data))
                if match:
                    return match.group(1).strip()
    except OSError:
        return ""
    return ""


def process_prompt(payload: dict[str, Any]) -> dict[str, Any]:
    """Record a prompt and return the resulting state. Fail-open without identity."""
    prompt = extract_prompt_text(payload)
    state = load_state(payload)
    if not state_path(payload):
        return state

    if state.get("phase") == "hard_stop" and reflection_invoked(prompt):
        state["phase"] = "reflection_acknowledged"
        state["reflection_prompt"] = prompt
        save_state(payload, state)
        return state

    correction = correction_class(prompt)
    if not correction:
        return state

    counts = dict(state.get("correction_counts") or {})
    counts[correction] = int(counts.get(correction) or 0) + 1
    state.update({
        "correction_counts": counts,
        "last_correction": prompt,
        "last_correction_class": correction,
        "correction_line": _line_count(_transcript_path(payload)),
    })
    state["phase"] = "hard_stop" if counts[correction] >= 2 else "contract_required"
    save_state(payload, state)
    return state


def prompt_instruction(state: dict[str, Any]) -> str:
    phase = state.get("phase")
    if phase == "contract_required":
        return FIRST_GATE
    if phase == "hard_stop":
        return HARD_GATE
    if phase == "reflection_acknowledged":
        return "Scope hard-stop acknowledged: run /reflect and automate-me before resuming the task."
    return ""


def _tool_name(payload: dict[str, Any]) -> str:
    value = payload.get("tool_name") or payload.get("toolName") or payload.get("tool")
    return str(value or "")


def tool_block_reason(payload: dict[str, Any]) -> tuple[bool, str]:
    """Return whether this tool is blocked and the deterministic reason."""
    state = load_state(payload)
    phase = state.get("phase")
    if phase == "hard_stop":
        return True, HARD_GATE
    if phase != "contract_required":
        return False, ""

    contract = recorded_contract(payload, int(state.get("correction_line") or 0))
    if contract:
        state["phase"] = "locked"
        state["contract"] = contract
        save_state(payload, state)
        return False, ""

    tool = re.sub(r"[^a-z_]", "", _tool_name(payload).lower())
    if tool in LOCAL_READ_ONLY_TOOLS:
        return False, ""
    return True, FIRST_GATE
