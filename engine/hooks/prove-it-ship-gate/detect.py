"""prove-it-ship-gate as a Stop hook.

The skill (corpus/skills/prove-it-ship-gate) is a claim-shape rule: when the
outgoing message says done / shipped / deployed / live about work with live
side effects (Linear, deploy, production host, webhook, Slack, external API),
the same message must carry live evidence or the literal prefix
`UNVERIFIED: live path`. Unit tests, fixtures, and UI registration do not
count. This lived only in prose; this file is the
mechanical half. Judgment (is this work really live-side-effect work) stays
with the model: the hook only matches shapes and fails open on parse errors.

Incident: Invoker PRs #10553-#10558 published cross-repo-research after unit
+ fixture + UI only; the user forced a live Linear e2e and a reflect.
"""
from __future__ import annotations

import json
import re

# A claim is a status assertion about the work, not any mention of the word.
# Sentence-initial status words ("Deployed. DO1 is now...") and copula forms
# ("is shipped", "are live", "now deployed") count; adjectives ("the deployed
# timeout") and progress talk ("actively working on it") do not. Negated
# forms ("not deployed", "isn't live") are removed before matching.
CLAIM_RE = re.compile(
    r"(?:(?:^|[.!:\n]\s*|\*\*)(?:deployed|shipped|landed|live|done)\b)|"
    r"\b(?:is|are|now|been|got|successfully|and)\s+(?:already\s+|now\s+|fully\s+)?(?:shipped|deployed|live|landed)\b|"
    r"\b(?:now works|fully fixed|working end[- ]to[- ]end|done and shipped|"
    r"tested,? and shipped|everything'?s? (?:landed|deployed|live)|"
    r"confirmed live|is up and running|running in production)\b",
    re.IGNORECASE,
)
NEGATED_CLAIM_RE = re.compile(
    r"\b(?:not|never|n't|isn't|aren't|wasn't|without being|not yet|hasn't|haven't)\s+"
    r"(?:been\s+|yet\s+|actually\s+|fully\s+)?(?:shipped|deployed|live|landed|done|merged)\b",
    re.IGNORECASE,
)
LIVE_NOUN_RE = re.compile(
    r"\b(?:linear|deploy(?:ed|ment|s)?|production|prod|do-?1|droplet|digital\s*ocean|"
    r"webhook|slack|external api|live mine|posthog|stripe|sentry|live path|"
    r"live (?:worker|owner|host|server|tick))\b",
    re.IGNORECASE,
)
PROXIMITY_WINDOW = 240  # chars between a claim word and a live noun

# Evidence a reviewer can chase without trusting the narrator: a URL, a
# commit sha, a ticket/PR id, a fenced block, an exit code, a PID, or a
# timestamp. Narrative like "ran it against production" is not evidence.
EVIDENCE_RE = re.compile(
    r"https?://\S+|```|\b[0-9a-f]{7,40}\b|\b[A-Z]{2,6}-\d{1,6}\b|#\d{3,6}\b|"
    r"\bexit[_ ]code\b|\bEXIT_CODE\b|\bPID\b|\bMainPID\b|"
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}",
    re.IGNORECASE,
)
UNVERIFIED_RE = re.compile(r"\bUNVERIFIED:\s*live path\b", re.IGNORECASE)

# Bash commands this turn that touch a live surface. A pytest run does not.
LIVE_COMMAND_RE = re.compile(
    r"(?:^|\s|\|)(?:ssh|curl|wget|gh\s+(?:api|pr\s+(?:view|checks|list|status)|run)|"
    r"systemctl|journalctl|kubectl|linear|doctl)\b",
    re.IGNORECASE,
)


def claims_live_ship(message: str) -> bool:
    if not message:
        return False
    message = NEGATED_CLAIM_RE.sub(" ", message)
    claim_positions = [m.start() for m in CLAIM_RE.finditer(message)]
    if not claim_positions:
        return False
    for noun in LIVE_NOUN_RE.finditer(message):
        if any(abs(noun.start() - c) <= PROXIMITY_WINDOW for c in claim_positions):
            return True
    return False


def has_evidence(message: str) -> bool:
    return bool(EVIDENCE_RE.search(message or ""))


def _is_user_line(data: dict) -> bool:
    if data.get("type") == "user":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "user"


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


def bash_commands_this_turn(transcript_path: str) -> list[str] | None:
    """Bash tool commands since the last authored user message. None when the
    transcript cannot be read (fail open), [] when read fine but empty."""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    turn_start = 0
    for i, raw in enumerate(lines):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not _is_user_line(data):
            continue
        text = _text_content(data)
        if not text.strip():
            continue
        if text.lstrip().startswith(("<command-", "<task-notification", "<system", "<local-command")):
            continue
        turn_start = i
    commands: list[str] = []
    for raw in lines[turn_start:]:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Bash":
                command = (block.get("input") or {}).get("command")
                if isinstance(command, str):
                    commands.append(command)
    return commands


def decide(payload: dict) -> str | None:
    """Return blocking feedback, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not claims_live_ship(message):
        return None
    if UNVERIFIED_RE.search(message) or has_evidence(message):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if transcript_path:
        commands = bash_commands_this_turn(transcript_path)
        if commands is None:
            return None  # unreadable transcript: fail open
        if any(LIVE_COMMAND_RE.search(c) for c in commands):
            return None
    return (
        "prove-it-ship-gate: this message claims done/shipped/live for work with a "
        "live side effect (Linear, deploy, production host, webhook, external API) "
        "but shows no live evidence -- no URL, sha, ticket/PR id, fenced output, exit "
        "code, or live command this turn. Fixture tests and UI registration do not "
        "prove the live path ran. Paste the live evidence in this message, or prefix "
        "the claim with `UNVERIFIED: live path`."
    )
