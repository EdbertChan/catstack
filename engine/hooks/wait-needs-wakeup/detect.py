"""wait-needs-wakeup: waiting means scheduling a wakeup, never polling.

Two shapes, one rule. When the agent is waiting on something (CI, a merge
queue, a subagent, an external job) it must hand the wait to the harness
(a run_in_background command that exits when the condition is met, a
Monitor/Agent that notifies on completion, or ScheduleWakeup) and tell the
user a clock-time ETA. It must never burn the foreground on a sleep loop,
never end a turn with "will report" / "nothing needed from you for ~10
minutes" and no named next contact time, and never wake the same giant
transcript without bound.

PreToolUse (Bash): block a foreground poll loop (sleep inside a
while/until/retry-for with a status check) and a bare foreground sleep of
30 seconds or more. A background command that exits on its condition
(until, or a break) is the correct form and passes.

PreToolUse (ScheduleWakeup): block past WAIT_NEEDS_WAKEUP_BUDGET (default
10) wakeups per transcript. Each wake resumes this same context, so a
same-session wake is a poll check billed at full transcript size; past the
budget the wait must detach (background exit-on-condition, Monitor/Agent)
or the transcript must compact first. CronCreate is exempt — it starts a
fresh session.

Stop: block a reply that says it is waiting/watching/will report unless the
reply carries a clock-time ETA and the turn has a live wakeup (a wakeup
tool call this turn, or a background task launched and not yet reported).

Judgment stays with the model; this file matches shapes and fails open.
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
    "poll -> hand the wait to the harness: a run_in_background command that exits "
    "on its condition (until/break), or a Monitor/Agent that notifies once — "
    "ScheduleWakeup only when neither fits (each wake re-sends this whole "
    "transcript). Tell the user the ETA in their own timezone "
    "(wait-needs-wakeup). {reason}"
)
STOP_MESSAGE = (
    "wait-needs-wakeup: this reply says it is waiting / watching / will report, but {gap}. "
    "State a clock-time ETA in the user's own timezone (`date +%H:%M\\ %Z`, e.g. "
    "'back at 12:26 PDT') and hand the wait to the harness — a run_in_background "
    "command that exits on its condition, a Monitor/Agent that notifies once, or "
    "ScheduleWakeup only when neither fits (each wake re-sends this whole "
    "transcript). Both halves or neither: an ETA with no scheduled wakeup is a "
    "promise nothing keeps."
)
WAKE_BUDGET_ENV = "WAIT_NEEDS_WAKEUP_BUDGET"
WAKE_BUDGET_DEFAULT = 10
WAKE_BUDGET_MESSAGE = (
    "wake budget: this session has already scheduled {wakes} wakeups — every "
    "wake resumes this whole transcript (session-lifetime token burn is "
    "turns x context, not the check itself). Hand the watch to a "
    "run_in_background command that exits on its condition, a Monitor/Agent "
    "that notifies once, or compact before scheduling another wake "
    "(wait-needs-wakeup). Override: {env} env var."
)
RULE_FOREGROUND_POLL = "wait-needs-wakeup.foreground-poll"
RULE_BACKGROUND_LOOP_NO_EXIT = "wait-needs-wakeup.background-loop-no-exit"
RULE_BARE_FOREGROUND_SLEEP = "wait-needs-wakeup.bare-foreground-sleep"
RULE_WAKE_BUDGET = "wait-needs-wakeup.wake-budget"
RULE_WAIT_REPLY_GAPS = "wait-needs-wakeup.wait-reply-gaps"


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


def pretooluse_reason(payload: dict) -> str | None:
    if payload.get("tool_name") not in (None, "Bash"):
        return None
    tool_input = payload.get("tool_input") or {}
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    return classify_command(command, bool(tool_input.get("run_in_background")))


def count_scheduled_wakes(transcript_path: str) -> int:
    """ScheduleWakeup tool_use blocks already in the transcript, or -1 when the
    transcript cannot be read. Each wake resumes this same session, so the
    count is the session's poll-check total — the number that made the
    multi-day babysit sessions cost billions of tokens."""
    wakes = 0
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            for raw in handle:
                if '"ScheduleWakeup"' not in raw:
                    continue
                try:
                    data = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                for block in _tool_uses(data):
                    if block.get("name") == "ScheduleWakeup":
                        wakes += 1
    except OSError:
        return -1
    return wakes


def wake_budget(environ=None) -> int:
    env = os.environ if environ is None else environ
    try:
        return int(env.get(WAKE_BUDGET_ENV, "") or WAKE_BUDGET_DEFAULT)
    except ValueError:
        return WAKE_BUDGET_DEFAULT


def decide_wakeup_budget(payload: dict, environ=None) -> str | None:
    """Block the (budget+1)-th ScheduleWakeup: past this point the wait must
    leave the session (background exit-on-condition, Monitor/Agent) or the
    transcript must be compacted first."""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not transcript_path:
        return None
    wakes = count_scheduled_wakes(transcript_path)
    if wakes < 0 or wakes < wake_budget(environ):
        return None
    return WAKE_BUDGET_MESSAGE.format(wakes=wakes, env=WAKE_BUDGET_ENV)


def decide_pretooluse(payload: dict) -> str | None:
    if payload.get("tool_name") == "ScheduleWakeup":
        return decide_wakeup_budget(payload)
    reason = pretooluse_reason(payload)
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


class WakeupTracker:
    """What the transcript so far says about scheduled wakeups, fed one line at a time.

    scheduled_this_turn: a ScheduleWakeup / CronCreate call since the last
    human message. pending: a Monitor / Agent / run_in_background Bash whose
    task-notification has not arrived yet (it will wake the agent)."""

    def __init__(self) -> None:
        self.scheduled_this_turn = False
        self.launched: dict[str, str] = {}
        self.notified: set[str] = set()

    def feed(self, index: int, data: dict) -> None:
        if _is_human_user_line(data):
            self.scheduled_this_turn = False
        content = data.get("content") if isinstance(data.get("content"), str) else _text_content(data)
        self.notified.update(TOOL_USE_ID_RE.findall(content or ""))
        for block in _tool_uses(data):
            name = block.get("name")
            inp = block.get("input") or {}
            if name in WAKEUP_TOOLS:
                self.scheduled_this_turn = True
            if name in TASK_TOOLS or (name == "Bash" and inp.get("run_in_background")):
                self.launched[block.get("id") or f"line{index}"] = name

    def state(self) -> dict:
        pending = [name for tid, name in self.launched.items() if tid not in self.notified]
        return {"scheduled_this_turn": self.scheduled_this_turn, "pending": pending}


def wakeup_state(lines: list[dict]) -> dict:
    tracker = WakeupTracker()
    for i, data in enumerate(lines):
        tracker.feed(i, data)
    return tracker.state()


def stop_gaps(message: str, state: dict) -> list[str]:
    gaps = []
    if not (state["scheduled_this_turn"] or state["pending"]):
        gaps.append("no wakeup is scheduled (no ScheduleWakeup / Monitor call, no background task still pending)")
    if not has_clock_eta(message):
        gaps.append("no clock-time ETA is named")
    return gaps


def decide_stop_from_lines(message: str, lines: list[dict]) -> str | None:
    if not is_wait_reply(message):
        return None
    gaps = stop_gaps(message, wakeup_state(lines))
    if not gaps:
        return None
    return STOP_MESSAGE.format(gap="; ".join(gaps))


def _is_tool_result_line(data: dict) -> bool:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in content
    )


def replay_stop(rows):
    """Rows detector for scripts/test/backtest_detector.py: every turn-ending reply,
    judged against the wakeup state at that point. A wait reply that names an
    ETA and holds a wakeup is the near-miss."""
    tracker = WakeupTracker()
    held = None
    seen: set[str] = set()
    for index, data in rows:
        tracker.feed(index, data)
        kind = data.get("type")
        if kind not in ("user", "assistant"):
            continue
        if held is not None and kind == "user" and not _is_tool_result_line(data) and held[1] not in seen:
            seen.add(held[1])
            yield held
        held = None
        text = _text_content(data) if kind == "assistant" else ""
        if text.strip():
            gaps = stop_gaps(text, tracker.state()) if is_wait_reply(text) else None
            held = (index, text, gaps or None, gaps == [])
    if held is not None and held[1] not in seen:
        yield held


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


def detect(event: dict[str, object]) -> list[Finding]:
    """SDK detector: return findings for the current PreToolUse or Stop payload."""
    if not isinstance(event, dict):
        return []
    event_name = _event_name(event)
    if event_name == "Stop" or (
        not event_name and isinstance(event.get("last_assistant_message"), str)
    ):
        return _detect_stop(event)
    if event.get("tool_name") == "ScheduleWakeup":
        return _detect_wake_budget(event)
    if event.get("tool_name") in (None, "Bash"):
        return _detect_poll_command(event)
    return []


def _detect_poll_command(event: dict[str, object]) -> list[Finding]:
    reason = pretooluse_reason(event)
    if not reason:
        return []
    return [
        Finding(
            rule_id=_poll_rule_id(reason),
            subject=_tool_subject(event),
            message=PRETOOLUSE_MESSAGE.format(reason=reason),
            evidence=reason,
        )
    ]


def _detect_wake_budget(event: dict[str, object]) -> list[Finding]:
    message = decide_wakeup_budget(event)
    if not message:
        return []
    transcript_path = event.get("transcript_path") or event.get("transcriptPath") or ""
    wakes = count_scheduled_wakes(str(transcript_path))
    return [
        Finding(
            rule_id=RULE_WAKE_BUDGET,
            subject=_tool_subject(event),
            message=message,
            evidence=f"scheduled wakes: {wakes}",
        )
    ]


def _detect_stop(event: dict[str, object]) -> list[Finding]:
    message = decide_stop(event)
    if not message:
        return []
    reply = event.get("last_assistant_message") or ""
    transcript_path = event.get("transcript_path") or event.get("transcriptPath") or ""
    lines: list[dict] = []
    if transcript_path:
        try:
            with open(str(transcript_path), encoding="utf-8") as handle:
                lines = parse_lines(handle)
        except OSError:
            return []
    gaps = stop_gaps(str(reply), wakeup_state(lines))
    return [
        Finding(
            rule_id=RULE_WAIT_REPLY_GAPS,
            subject=_text_subject(str(reply)),
            message=message,
            evidence="; ".join(gaps),
        )
    ]


def _event_name(event: dict[str, object]) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _poll_rule_id(reason: str) -> str:
    if reason.startswith("background loop never exits"):
        return RULE_BACKGROUND_LOOP_NO_EXIT
    if reason.startswith("bare foreground sleep"):
        return RULE_BARE_FOREGROUND_SLEEP
    return RULE_FOREGROUND_POLL


def _tool_subject(event: dict[str, object]) -> str:
    for key in ("tool_use_id", "toolUseID", "tool_call_id", "id"):
        value = event.get(key)
        if isinstance(value, str) and value:
            return f"tool-call:{value}"
    tool_input = event.get("tool_input") or {}
    if isinstance(tool_input, dict):
        command = tool_input.get("command")
        if isinstance(command, str) and command:
            return _text_subject(command, prefix="command")
    tool_name = event.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        return f"tool:{tool_name}"
    return "tool:unknown"


def _text_subject(text: str, prefix: str = "reply") -> str:
    digest = hashlib.sha256((text or "").strip().encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"
