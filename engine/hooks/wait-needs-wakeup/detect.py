"""wait-needs-wakeup: waiting means scheduling a wakeup, never polling.

Two shapes, one rule. When the agent is waiting on something (CI, a merge
queue, a subagent, an external job) it must hand the wait to the harness
(ScheduleWakeup, Monitor, a run_in_background command that exits when the
condition is met, a running subagent that notifies on completion) and tell
the user a clock-time ETA. It must never burn the foreground on a sleep
loop, and never end a turn with "will report" / "nothing needed from you
for ~10 minutes" and no named next contact time.

PreToolUse (Bash): block a foreground poll loop (sleep inside a
while/until/retry-for with a status check) and a bare foreground sleep of
30 seconds or more. A background command that exits on its condition
(until, or a break) is the correct form and passes.

Stop: block a reply that says it is waiting/watching/will report unless the
reply carries a clock-time ETA and the turn has a live wakeup (a wakeup
tool call this turn, or a background task launched and not yet reported).

Judgment stays with the model; this file matches shapes and fails open.
"""
from __future__ import annotations

import json
import re

LOOP_RE = re.compile(
    r"(?=(\b(?P<kind>for|while|until)\b(?P<head>.*?)(?:;|\n)\s*do\b(?P<body>.*?)\bdone\b))",
    re.DOTALL,
)
RETRY_FOR_HEAD_RE = re.compile(r"\$\(\s*seq\b|\{\d+\.\.\d+\}|\bseq\s+\d+", re.IGNORECASE)
SLEEP_RE = re.compile(r"(?<![\w./-])sleep\s+(\d+(?:\.\d+)?)([smhd]?)\b")
STATUS_CHECK_RE = re.compile(
    r"(?<![\w./-])(?:gh|curl|wget|grep|test|ls|stat|docker|pg_isready|kubectl|ssh|nc|ping|"
    r"git|systemctl|ps|pgrep|lsof|nvidia-smi)\b|\[\[?\s",
)
EXIT_ON_CONDITION_RE = re.compile(r"\bbreak\b|\bexit\b|\breturn\b")
BARE_SLEEP_LIMIT_SECS = 30
UNIT_SECS = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}

WAKEUP_TOOLS = {"ScheduleWakeup", "CronCreate"}
TASK_TOOLS = {"Monitor", "Agent"}
TOOL_USE_ID_RE = re.compile(r"<tool-use-id>\s*([^<\s]+)\s*</tool-use-id>")

WAIT_RE = re.compile(
    r"nothing needed from you|"
    r"\b(?:a|the|re-?arm(?:ing|ed)? (?:a|the)) watcher\b|"
    r"\bwill report\b|\breports? back\b|\breport (?:all|the result|when|once)\b|"
    r"\bstill running\b|\brunning in the background\b|\bagents? (?:are|is|still) running\b|"
    r"\bwaiting (?:on|for) (?!you\b|your\b)|"
    r"\b(?:I'll|I will|will) (?:check|poll|watch|report)\b|"
    r"\b(?:in|for|about|within) ~?\d+ ?(?:min|minutes)\b|"
    r"\bthe moment (?:it|that|#\d+|\w+) (?:reports|finishes|lands|merges)\b|"
    r"\buntil (?:the|those|its|it) (?:\w+ )?(?:PRs?|links?|agents?|watchers?|runs?|jobs?|results?|reports?)\b[^.]{0,40}(?:arrive|report|finish|land|merge)",
    re.IGNORECASE,
)
QUOTED_BEFORE = ('"', "'", "`")
CLOCK_ETA_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\s*(?:UTC|GMT|Z\b|[A-Z]{2,4}T\b|[+-]\d{2}:?\d{2}|[ap]\.?m\.?\b)|"
    r"\b(?:at|by|around|before|ETA)\s+~?(?:[01]?\d|2[0-3]):[0-5]\d\b",
)

PAST_CLOCK_RE = re.compile(r"\b\w+ed\s+(?:(?:at|by)\s+~?)?$")

PRETOOLUSE_MESSAGE = (
    "poll -> schedule a wakeup: ScheduleWakeup / Monitor / run_in_background+exit-on-condition, "
    "and tell the user the ETA in their own timezone (wait-needs-wakeup). {reason}"
)
STOP_MESSAGE = (
    "wait-needs-wakeup: this reply says it is waiting / watching / will report, but {gap}. "
    "State a clock-time ETA in the user's own timezone (`date +%H:%M\\ %Z`, e.g. "
    "'back at 12:26 PDT') and schedule the wakeup (ScheduleWakeup / Monitor / a "
    "run_in_background command that exits on the condition). Both halves or neither: "
    "an ETA with no scheduled wakeup is a promise nothing keeps."
)


def _sleep_secs(match: re.Match) -> float:
    return float(match.group(1)) * UNIT_SECS.get(match.group(2) or "", 1)


def poll_loops(command: str) -> list[dict]:
    """Every loop in the command whose body sleeps and whose head or body
    runs a status check. `for` counts only as a retry loop (seq / range)."""
    found: list[dict] = []
    for match in LOOP_RE.finditer(command or ""):
        kind = match.group("kind")
        head = match.group("head") or ""
        body = match.group("body") or ""
        if kind == "for" and not RETRY_FOR_HEAD_RE.search(head):
            continue
        if not SLEEP_RE.search(body):
            continue
        if not STATUS_CHECK_RE.search(head + body):
            continue
        found.append({
            "kind": kind,
            "span": (match.start(1), match.end(1)),
            "exits_on_condition": kind == "until" or bool(EXIT_ON_CONDITION_RE.search(body)),
        })
    return found


def bare_sleeps(command: str, loops: list[dict]) -> list[float]:
    """Sleep durations (seconds) outside every detected loop span."""
    out: list[float] = []
    for match in SLEEP_RE.finditer(command or ""):
        inside = any(start <= match.start() < end for start, end in (lp["span"] for lp in loops))
        if not inside:
            out.append(_sleep_secs(match))
    return out


def classify_command(command: str, run_in_background: bool = False) -> str | None:
    """Reason this Bash command is a foreground poll, or None when it is fine."""
    if not command or "sleep" not in command:
        return None
    loops = poll_loops(command)
    if loops:
        if not run_in_background:
            kinds = ", ".join(sorted({lp["kind"] for lp in loops}))
            return f"foreground {kinds} loop sleeps while checking a status"
        if not any(lp["exits_on_condition"] for lp in loops):
            return "background loop never exits on its condition (no until / break)"
    if not run_in_background:
        long = [s for s in bare_sleeps(command, loops) if s >= BARE_SLEEP_LIMIT_SECS]
        if long:
            return f"bare foreground sleep of {int(max(long))}s"
    return None


def decide_pretooluse(payload: dict) -> str | None:
    if payload.get("tool_name") not in (None, "Bash"):
        return None
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    reason = classify_command(command, bool(tool_input.get("run_in_background")))
    if not reason:
        return None
    return PRETOOLUSE_MESSAGE.format(reason=reason)


def is_wait_reply(text: str) -> bool:
    """Wait language outside quotes (a reply that quotes the rule is not waiting)."""
    for match in WAIT_RE.finditer(text or ""):
        if match.start() and text[match.start() - 1] in QUOTED_BEFORE:
            continue
        return True
    return False


def has_clock_eta(text: str) -> bool:
    """A clock time that reads as a next contact time, not a past event
    ("merged at 07:24 UTC" is history, "back at 07:26 UTC" is an ETA)."""
    for match in CLOCK_ETA_RE.finditer(text or ""):
        if not PAST_CLOCK_RE.search(text[: match.start()]):
            return True
    return False


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
    if not text.strip():
        return False
    return not text.lstrip().startswith("<")


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


def _tool_uses(data: dict):
    if data.get("type") != "assistant":
        return
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            yield block


def wakeup_state(lines: list[dict]) -> dict:
    """What the transcript says about scheduled wakeups.

    scheduled_this_turn: a ScheduleWakeup / CronCreate call since the last
    human message. pending: a Monitor / Agent / run_in_background Bash whose
    task-notification has not arrived yet (it will wake the agent)."""
    turn_start = 0
    for i, data in enumerate(lines):
        if _is_human_user_line(data):
            turn_start = i
    launched: dict[str, str] = {}
    notified: set[str] = set()
    scheduled_this_turn = False
    for i, data in enumerate(lines):
        content = data.get("content") if isinstance(data.get("content"), str) else _text_content(data)
        for tid in TOOL_USE_ID_RE.findall(content or ""):
            notified.add(tid)
        for block in _tool_uses(data):
            name = block.get("name")
            inp = block.get("input") or {}
            if name in WAKEUP_TOOLS and i >= turn_start:
                scheduled_this_turn = True
            if name in TASK_TOOLS or (name == "Bash" and inp.get("run_in_background")):
                launched[block.get("id") or f"line{i}"] = name
    pending = [name for tid, name in launched.items() if tid not in notified]
    return {"scheduled_this_turn": scheduled_this_turn, "pending": pending}


def decide_stop_from_lines(message: str, lines: list[dict]) -> str | None:
    if not is_wait_reply(message):
        return None
    state = wakeup_state(lines)
    has_wakeup = state["scheduled_this_turn"] or bool(state["pending"])
    eta = has_clock_eta(message)
    if has_wakeup and eta:
        return None
    gaps = []
    if not has_wakeup:
        gaps.append("no wakeup is scheduled (no ScheduleWakeup / Monitor call, no background task still pending)")
    if not eta:
        gaps.append("no clock-time ETA is named")
    return STOP_MESSAGE.format(gap="; ".join(gaps))


def decide_stop(payload: dict) -> str | None:
    """Return blocking feedback for the Stop event, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not is_wait_reply(message):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    lines: list[dict] = []
    if transcript_path:
        try:
            with open(transcript_path, encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return None
    return decide_stop_from_lines(message, lines)
