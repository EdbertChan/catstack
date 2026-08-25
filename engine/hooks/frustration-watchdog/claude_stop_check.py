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

Fail-open by design: any parse/read error allows the turn. `stop_hook_active`
allows the turn to avoid block loops.
"""
import json
import os
import re
import sys
from datetime import datetime

IMPATIENCE_PATTERNS = [
    ("profanity", re.compile(r"\b(fuck\w*|wtf|shit\w*|goddamn|dammit|damn it|stupid)\b", re.I)),
    ("told-you", re.compile(r"\bi (already |just )?told you\b", re.I)),
    ("waiting", re.compile(r"\b(i am|i'?m) (still )?waiting\b|\btime constraint\b|\bhurry up\b", re.I)),
    ("accusation", re.compile(r"\byou('?re| are) (thrashing|not listening|ignoring)\b", re.I)),
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


def human_user_messages(transcript_path, keep=8):
    """Last `keep` human-authored user messages as (iso_ts, text)."""
    msgs = []
    with open(transcript_path) as f:
        for line in f:
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "user":
                continue
            content = d.get("message", {}).get("content")
            text = content if isinstance(content, str) else None
            if isinstance(content, list):
                if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue
                text = "\n".join(
                    b.get("text", "") for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                )
            if not text or not text.strip():
                continue
            if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
                continue
            if "[Request interrupted by user" in text:
                continue
            msgs.append((d.get("timestamp"), text))
            if len(msgs) > keep:
                msgs.pop(0)
    return msgs


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
    if data.get("stop_hook_active"):
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
    sys.stderr.write(
        f"The user's last message was impatience-shaped ({', '.join(sorted(set(kinds)))}) "
        "and this reply hands them nothing visible. End the wait: give exactly one "
        "concrete action for the user (\"click X\", \"run Y\", \"say Z\"), ask them a "
        "direct question, or state an explicit no-action window "
        "(\"nothing needed from you for ~2 min\"). Per CLAUDE.md live-demo rules.\n"
    )
    sys.exit(2)


if __name__ == "__main__":
    main()
