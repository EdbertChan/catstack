"""reflect-quiet-output: a reflect pass answers in chat with one sentence.

The reflect skill writes its Accepted / Backlog / Route-to-automate-me /
Rejected list, the cost audit, the feedback-loop line and any open question
into the PR body (reflect SKILL.md step 7). The chat window gets exactly one
sentence: a PR was opened, with its link, plus "one question in the PR" when a
finding needs a human decision. A findings list in the main window is the
thing the rule exists to stop, and a rule with no detector drifts.

Stop: when the current turn shows a reflect invocation, block a reply that
has more than one sentence or that carries a findings label at the start of a
line. A reflect invocation is one of three shapes seen in this turn (from the
person's last own message onward): the typed slash command's
``<command-name>/reflect</command-name>`` envelope, a ``Skill`` tool call for
``reflect``, or a read of ``skills/reflect/SKILL.md`` (Read, a shell read, or
an Agent prompt naming it). Text that only quotes those shapes does not count:
a tool result, a harness-injected row, or a task notification is never the
person's own message. A turn that edits a file under ``skills/reflect/`` is
authoring the skill, not running it, so the skill-read shape is ignored there;
the slash command and the Skill tool still count.

Three outcomes: hit (block, exit 2), clean (silent), unchecked (no readable
transcript or no reply text: a ``catstack-hook-unchecked`` line on stderr and
no block, because the hook cannot know whether reflect ran). Fail-open on the
unchecked path. ``stop_hook_active`` skips so the rewrite turn can finish.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402

HOOK = "reflect-quiet-output"
RULE_MULTI_SENTENCE = "reflect-quiet-output.multi-sentence-reply"
RULE_FINDINGS_IN_CHAT = "reflect-quiet-output.findings-in-chat"

REFLECT_COMMAND_RE = re.compile(
    r"(?i)<command-name>\s*/?reflect\b|<command-message>\s*reflect\s*</command-message>"
)
REFLECT_SKILL_PATH_RE = re.compile(r"skills/reflect/SKILL\.md\b")
SHELL_READ_RE = re.compile(
    r"\b(?:cat|sed|head|tail|nl|less|more|bat)\b[^;|&\n]*?skills/reflect/SKILL\.md\b"
)
REFLECT_SKILL_DIR_RE = re.compile(r"skills/reflect/")
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SHELL_TOOLS = frozenset({"Bash", "bash", "Shell", "shell", "Exec", "exec", "exec_command"})
SEARCH_TOOLS = frozenset({"Grep", "Glob", "TodoWrite", "WebSearch", "WebFetch"})
META_USER_PREFIXES = ("<local-command", "<task-notification", "<system", "Stop hook feedback")

LABEL_RE = re.compile(
    r"(?im)^[ \t]*(?:[-*+>]|\d+[.)]|#{1,6})?[ \t]*[*_`]*"
    r"(accepted|backlog(?:ged)?|rejected|dropped|route(?:d)?[ -]to[ -]`?automate-me|"
    r"cost audit|feedback-loop(?: check)?|edits applied|open question)\b"
)
LINK_RE = re.compile(r"\[[^\]\n]*\]\([^)\n]*\)|https?://\S+?(?=[.,;:!?)\]]*(?:\s|$))|`[^`\n]*`")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
LETTER_RE = re.compile(r"[A-Za-z]")

MESSAGE = (
    "reflect-quiet-output: this turn ran reflect and the reply {deficit}. "
    "Put the Accepted / Backlog / Route-to-automate-me / Rejected list, the cost "
    "audit, the feedback-loop line and any open question into the PR body "
    "(reflect SKILL.md step 7), then reply with exactly one sentence: that a PR "
    "was opened, with its link, plus 'one question in the PR' when a finding "
    "needs a human decision."
)


def _message_content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def _text(data: dict) -> str:
    content = _message_content(data)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text") or ""
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _is_tool_result(data: dict) -> bool:
    if data.get("toolUseResult") is not None or data.get("toolDenialKind") is not None:
        return True
    content = _message_content(data)
    return isinstance(content, list) and any(
        isinstance(block, dict) and block.get("type") == "tool_result" for block in content
    )


def _role(data: dict) -> str:
    message = data.get("message")
    role = message.get("role") if isinstance(message, dict) else None
    return str(role or data.get("type") or "")


def is_human_turn_start(data: dict) -> bool:
    """The person's own message: not a tool result, not a harness injection,
    not a subagent row, not a task notification or hook feedback."""
    if _role(data) != "user" or _is_tool_result(data):
        return False
    if data.get("isMeta") or data.get("isSidechain") or data.get("agentId") or data.get("agent_id"):
        return False
    text = _text(data).lstrip()
    return bool(text) and not text.startswith(META_USER_PREFIXES)


def _tool_uses(data: dict):
    if _role(data) != "assistant":
        return
    content = _message_content(data)
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block


def _strings(node) -> list[str]:
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in _strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in _strings(value)]
    return []


def _skill_name(inp) -> str:
    skill = inp.get("skill") if isinstance(inp, dict) else None
    return str(skill or "").strip().split(":")[-1]


def _edits_reflect_skill(block: dict) -> bool:
    if block.get("name") not in EDIT_TOOLS:
        return False
    return any(REFLECT_SKILL_DIR_RE.search(text) for text in _strings(block.get("input")))


def _reads_reflect_skill(block: dict) -> bool:
    name = str(block.get("name") or "")
    if name in EDIT_TOOLS or name in SEARCH_TOOLS:
        return False
    texts = _strings(block.get("input"))
    if name in SHELL_TOOLS:
        return any(SHELL_READ_RE.search(text) for text in texts)
    return any(REFLECT_SKILL_PATH_RE.search(text) for text in texts)


def turn_rows(rows: list[dict]) -> list[dict]:
    """Rows from the person's last own message to the end, that message included."""
    start = 0
    for index in range(len(rows) - 1, -1, -1):
        if is_human_turn_start(rows[index]):
            start = index
            break
    return rows[start:]


def reflect_invoked(rows: list[dict]) -> str | None:
    """Which shape shows reflect ran this turn, or None."""
    turn = turn_rows(rows)
    authoring = any(_edits_reflect_skill(block) for data in turn for block in _tool_uses(data))
    skill_read = None
    for data in turn:
        if is_human_turn_start(data) and REFLECT_COMMAND_RE.search(_text(data)):
            return "the /reflect command"
        for block in _tool_uses(data):
            if block.get("name") == "Skill" and _skill_name(block.get("input")) == "reflect":
                return "the Skill tool loading reflect"
            if skill_read is None and _reads_reflect_skill(block):
                skill_read = f"{block.get('name')} of skills/reflect/SKILL.md"
    if skill_read and not authoring:
        return skill_read
    return None


def sentence_count(message: str) -> int:
    text = LINK_RE.sub(" link ", message or "")
    return sum(1 for part in SENTENCE_SPLIT_RE.split(text.strip()) if LETTER_RE.search(part))


def findings_labels(message: str) -> list[str]:
    seen: list[str] = []
    for match in LABEL_RE.finditer(message or ""):
        label = match.group(1).lower()
        if label not in seen:
            seen.append(label)
    return seen


def reply_deficit(message: str) -> tuple[str, str] | None:
    """(rule_id, deficit text) when the reply breaks the one-sentence rule."""
    labels = findings_labels(message)
    count = sentence_count(message)
    if labels:
        shown = ", ".join(labels[:4])
        return RULE_FINDINGS_IN_CHAT, f"carries findings labels in chat ({shown})"
    if count > 1:
        return RULE_MULTI_SENTENCE, f"has {count} sentences, not one"
    return None


def read_rows(path: str) -> list[dict] | None:
    if not path or not os.path.isfile(path):
        return None
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8") as handle:
            for raw in handle:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(data, dict):
                    rows.append(data)
    except OSError:
        return None
    return rows


def _transcript_path(payload: dict) -> str:
    for key in ("transcript_path", "transcriptPath", "agent_transcript_path"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _last_assistant_text(rows: list[dict]) -> str:
    last = ""
    for data in rows:
        if _role(data) == "assistant":
            text = _text(data)
            if text.strip():
                last = text
    return last


def _unchecked(reason: str, stderr) -> None:
    (stderr or sys.stderr).write(f"catstack-hook-unchecked {HOOK}: {reason}\n")


def decide(payload: dict, stderr=None) -> Finding | None:
    """Hit: a Finding. Clean: None. Unchecked: None plus a stderr line."""
    if payload.get("stop_hook_active"):
        return None
    path = _transcript_path(payload)
    rows = read_rows(path)
    if rows is None:
        _unchecked("transcript could not be read" if path else "no transcript path in payload", stderr)
        return None
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        message = _last_assistant_text(rows)
    if not message.strip():
        _unchecked("no assistant reply text to read", stderr)
        return None
    shape = reflect_invoked(rows)
    if shape is None:
        return None
    deficit = reply_deficit(message)
    if deficit is None:
        return None
    rule_id, text = deficit
    return Finding(
        rule_id=rule_id,
        subject=f"reply:{hashlib.sha256(message.encode('utf-8')).hexdigest()[:16]}",
        message=MESSAGE.format(deficit=text),
        evidence=f"{shape}; {text}",
    )


def detect(event: dict[str, object]) -> list[Finding]:
    finding = decide(event if isinstance(event, dict) else {})
    return [finding] if finding is not None else []
