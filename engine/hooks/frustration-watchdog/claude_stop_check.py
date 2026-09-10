#!/usr/bin/env python3
"""Claude Code Stop hook: user-waiting watchdog.

When the user's LAST message was impatience-shaped (an all-caps run,
profanity, "i told you", "i am waiting", ``???``, or a verbatim re-send of an
earlier message within 10 minutes), the assistant's outgoing message must
visibly end the wait: either one concrete action for the user (an imperative
like "click X", "run Y"), a direct question, or an explicit no-action ETA
("nothing needed from you for ~2 min"). Blocks (exit 2) when none is present.

Motivated by a /reflect on a 2026-08-17 live-demo session: 13/56 user
messages were frustration-flagged, and the worst cluster ("i am waiting for
you to do something", "WHY ARE WE NOT LAUNCHING A ZOOM MEETING") followed
turns that did background work and replied without a user-visible next step.
Signal patterns mirror skills/reflect/scripts/token_audit.py — that script is
the source of truth; keep the two in sync when tuning.

When a PreToolUse hook refused a tool call since the human's last message,
the block wording drops the "one concrete action" option and asks for a
direct question or a no-action window instead: the assistant is the one
blocked, and asking for an action pushed replies to hand the user the refused
steps. Only the wording changes, never whether the hook blocks. If the tool
results cannot be read, the default wording is used and the feedback says so.

Fail-open by design: any parse/read error allows the turn. `stop_hook_active`
allows the turn to avoid block loops.

SubagentStop opt-out (see claude.hook.json `subagent_stop`): this hook reads
the human's last message, and in a subagent transcript the "user" is the
parent agent's prompt, which often quotes the human verbatim. A payload that
carries `agent_id` therefore returns before reading anything.
"""
import json
import os
import re
import sys
from datetime import datetime

IMPATIENCE_PATTERNS = [
    ("profanity", re.compile(r"\b(fuck\w*|wtf|shit\w*|goddamn|dammit|damn it|stupid)\b", re.I)),
    ("told-you", re.compile(r"\bi (already |just )?told you\b|\bi asked you not\b|\bi already said\b", re.I)),
    ("waiting", re.compile(r"\b(i am|i'?m) (still )?waiting\b|\btime constraint\b|\bhurry up\b", re.I)),
    ("accusation", re.compile(r"\byou('?re| are) (thrashing|not listening|ignoring)\b|\bignoring me\b", re.I)),
    ("agent-blame", re.compile(r"\byou (fucked up|messed up|broke)\b|\byou('?ve| have) (fucked|messed) up\b", re.I)),
    ("multi-question-marks", re.compile(r"\?\?\?+")),
]

# Machine-generated role=user turns (slash-command/skill injections, task
# notifications, continuation summaries) are not the human talking.
SYSTEM_INJECTED_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
    "Stop hook feedback:",
    "PreToolUse hook",
    "PostToolUse hook",
    "UserPromptSubmit hook",
    "<user-prompt-submit-hook",
)

# An outgoing message "ends the wait" if it hands the user one concrete thing
# to do (an imperative opening a sentence, clause, or list item), asks them a
# direct question, or states an explicit no-action window. Clause-start
# anchoring matters: "— close the two old tabs" is a handoff, while the agent
# narrating its own verbs mid-clause ("and then I run the tests") is not.
NEXT_STEP_RE = re.compile(
    r"(?im)(?:^\s*(?:\d+[.)]\s+|[-*]\s+)?|[.;:!?]\s+|[—–-]\s+|\*\*)"
    r"(?:click|run|open|close|quit|say|speak|talk|type|press|join|drag|paste|"
    r"install|restart|reload|refresh|approve|select|pick|choose|check|look at|"
    r"go to|tell me|send me|give me|reply|answer|drop|put on|wear)\b"
)
ETA_RE = re.compile(
    r"(?i)\b(nothing (?:is )?needed|no action needed|hang tight|"
    r"~\s*\d+\s*(?:s|sec|seconds?|m|min|minutes?)|"
    r"i(?:'ll| will) (?:handle|do|take|run|fix|keep|watch))\b"
)

# How Claude Code records a tool call a PreToolUse hook refused: an is_error
# tool_result whose text opens "PreToolUse:Bash hook error: [<command>]: ...".
HOOK_REFUSAL_RE = re.compile(r"\s*PreToolUse:\S+ hook error\b")


def _is_allcaps(text):
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12 or len(text) <= 20:
        return False
    return sum(c.isupper() for c in letters) / len(letters) > 0.6


def _ts_seconds(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _human_text(d):
    """The human-authored text of a transcript line, or None."""
    if d.get("type") != "user":
        return None
    content = d.get("message", {}).get("content")
    text = content if isinstance(content, str) else None
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    if not text or not text.strip():
        return None
    if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
        return None
    if "[Request interrupted by user" in text:
        return None
    return text


def human_user_messages(transcript_path, keep=8):
    """Last `keep` human-authored user messages as (iso_ts, text)."""
    msgs = []
    with open(transcript_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _human_text(d)
            if text is None:
                continue
            msgs.append((d.get("timestamp"), text))
            if len(msgs) > keep:
                msgs.pop(0)
    return msgs


def _is_hook_refusal(block):
    if not (isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error")):
        return False
    content = block.get("content")
    if isinstance(content, list):
        content = "\n".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return isinstance(content, str) and bool(HOOK_REFUSAL_RE.match(content))


def turn_has_hook_refusal(transcript_path):
    """True when a PreToolUse hook refused a tool call since the human's last message."""
    refused = False
    with open(transcript_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if _human_text(d) is not None:
                refused = False
                continue
            if d.get("type") != "user":
                continue
            content = d.get("message", {}).get("content")
            if isinstance(content, list) and any(_is_hook_refusal(b) for b in content):
                refused = True
    return refused


def impatience_kinds(msgs):
    """Signal kinds on the LAST user message, or [] when calm."""
    if not msgs:
        return []
    ts, text = msgs[-1]
    t = text.strip()
    kinds = []
    if _is_allcaps(t):
        kinds.append("allcaps")
    for kind, rx in IMPATIENCE_PATTERNS:
        if rx.search(t):
            kinds.append(kind)
    norm = re.sub(r"\s+", " ", t).casefold()
    if len(norm) >= 12:
        secs = _ts_seconds(ts)
        for prev_ts, prev_text in msgs[:-1]:
            if re.sub(r"\s+", " ", prev_text.strip()).casefold() == norm:
                prev_secs = _ts_seconds(prev_ts)
                if secs is None or prev_secs is None or 0 <= secs - prev_secs <= 600:
                    kinds.append("verbatim-repeat")
                    break
    return kinds


def ends_the_wait(message):
    stripped = message.rstrip()
    if stripped.endswith("?"):
        return True  # a direct question is a handoff
    return bool(NEXT_STEP_RE.search(message) or ETA_RE.search(message))


def main():
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return
    if data.get("stop_hook_active") or data.get("agent_id"):
        return
    message = data.get("last_assistant_message") or ""
    transcript_path = data.get("transcript_path") or ""
    if not message or not transcript_path or not os.path.isfile(transcript_path):
        return
    try:
        msgs = human_user_messages(transcript_path)
        kinds = impatience_kinds(msgs)
    except Exception:
        return  # fail open: a broken watchdog must never brick a session
    if not kinds:
        return
    if ends_the_wait(message):
        return
    try:
        refused = turn_has_hook_refusal(transcript_path)
        unchecked = None
    except Exception as e:
        refused = False
        unchecked = f"{type(e).__name__}: {e}"
    head = (
        f"The user's last message was impatience-shaped ({', '.join(sorted(set(kinds)))}) "
        "and this reply hands them nothing visible. "
    )
    if refused:
        # A hook refused a tool call this turn, so the assistant is the one
        # blocked; asking the user for "one action" pushed replies to hand
        # them the refused steps. Offer only the question or the window.
        sys.stderr.write(
            head + "A hook refused a tool call this turn, so you are the one blocked: "
            "do not hand the user steps to work around it. End the wait: ask them a "
            "direct question, or state an explicit no-action window "
            "(\"nothing needed from you for ~2 min\"). Per CLAUDE.md live-demo rules.\n"
        )
    else:
        sys.stderr.write(
            head + "End the wait: give exactly one "
            "concrete action for the user (\"click X\", \"run Y\", \"say Z\"), ask them a "
            "direct question, or state an explicit no-action window "
            "(\"nothing needed from you for ~2 min\"). Per CLAUDE.md live-demo rules.\n"
        )
    if unchecked:
        sys.stderr.write(
            f"(frustration-watchdog could not read this turn's tool results ({unchecked}), "
            "so it could not tell whether a hook refused a tool call; the wording above "
            "is the default.)\n"
        )
    sys.exit(2)


if __name__ == "__main__":
    main()
