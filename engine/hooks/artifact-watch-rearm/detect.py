"""artifact-watch-rearm: tell the agent to re-arm artifact comment watches a restart dropped."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402

RULE_MISSING_WATCH = "artifact-watch-rearm.missing-watch"
STATE_DIR = os.environ.get(
    "ARTIFACT_WATCH_REARM_STATE_DIR",
    os.path.join(os.path.expanduser("~"), ".cache", "catstack-artifact-watch-rearm"),
)
SESSION_START_EVENT = "SessionStart"
FRESH_START_SOURCE = "startup"
ARTIFACT_URL_RE = re.compile(r"https://claude\.ai/artifact/([A-Za-z0-9_-]+)")
PUBLISHED_RE = re.compile(r"Published\b[^\n]*?\bat https://claude\.ai/artifact/([A-Za-z0-9_-]+)")
READ_HEADER_RE = re.compile(r"\A\s*\[Artifact\b[^\]\n]*")
EDITABLE_MARKERS = ("owned by you", "writer")
SYSTEM_REMINDER_RE = re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL)
ARTIFACT_URL_FORMAT = "https://claude.ai/artifact/{artifact_id}"

MESSAGE = (
    "artifact-watch-rearm: this session published, or was given, these artifacts: {urls}. "
    "Artifact watches are session-local and a restart, resume, clear or compaction can drop them; "
    "a dropped watch means a comment sent to Claude wakes nothing. "
    "Call ArtifactComments with action watch and no url to list this session's watches. "
    "For each URL above missing from that list, call ArtifactComments with action watch and that url, "
    "and pass replies true: the user asked for comment auto-replies to stay on. "
    "Skip any artifact the user can only view. Say nothing about this to the user unless a watch call fails."
)


class TranscriptScan:
    """What one pass over a transcript found: artifact ids by kind and the unreadable lines."""

    def __init__(self) -> None:
        self.editable: dict[str, None] = {}
        self.user_given: dict[str, None] = {}
        self.view_only: set[str] = set()
        self.stopped: set[str] = set()
        self.unreadable_lines = 0
        self.read_error = ""
        self.file_missing = False
        self.stderr_lines: list[str] = []

    def candidates(self) -> list[str]:
        """Artifact ids to keep watched, in first-seen order, minus view-only and user-stopped ones."""
        seen: dict[str, None] = {}
        for artifact_id in [*self.editable, *self.user_given]:
            if artifact_id in self.view_only or artifact_id in self.stopped:
                continue
            seen[artifact_id] = None
        return list(seen)

    def note_unreadable(self, path: str, line_number: int, reason: str) -> None:
        self.unreadable_lines += 1
        self.stderr_lines.append(
            f"catstack-hook-error artifact-watch-rearm: {path}:{line_number}: unreadable transcript line ({reason})"
        )


def _text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return ""


def _artifact_id_in(url: object) -> str:
    if not isinstance(url, str):
        return ""
    match = ARTIFACT_URL_RE.search(url)
    return match.group(1) if match else ""


def _note_user_text(scan: TranscriptScan, text: str) -> None:
    for artifact_id in ARTIFACT_URL_RE.findall(SYSTEM_REMINDER_RE.sub("", text)):
        scan.stopped.discard(artifact_id)
        scan.user_given.setdefault(artifact_id, None)


def _note_tool_use(scan: TranscriptScan, block: dict, pending: dict[str, tuple[str, str]]) -> None:
    name = block.get("name")
    tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    action = tool_input.get("action")
    if name == "Artifact" and action in (None, "publish") and not tool_input.get("asset"):
        pending[str(block.get("id"))] = ("publish", _artifact_id_in(tool_input.get("url")))
    elif name == "Artifact" and action == "read":
        pending[str(block.get("id"))] = ("read", _artifact_id_in(tool_input.get("url")))
    elif name == "ArtifactComments" and action == "watch" and tool_input.get("on") is False:
        artifact_id = _artifact_id_in(tool_input.get("url"))
        if artifact_id:
            scan.stopped.add(artifact_id)


def _note_tool_result(scan: TranscriptScan, block: dict, pending: dict[str, tuple[str, str]]) -> None:
    kind, requested_id = pending.pop(str(block.get("tool_use_id")), ("", ""))
    if not kind or block.get("is_error"):
        return
    text = _text_of(block.get("content"))
    if kind == "publish":
        match = PUBLISHED_RE.search(text)
        if match:
            scan.stopped.discard(match.group(1))
            scan.editable.setdefault(match.group(1), None)
    elif kind == "read" and requested_id:
        header = READ_HEADER_RE.match(text)
        if header is None:
            return
        if any(marker in header.group(0) for marker in EDITABLE_MARKERS):
            scan.editable.setdefault(requested_id, None)
            scan.view_only.discard(requested_id)
        else:
            scan.view_only.add(requested_id)


def scan_transcript(path: str, prompt: str = "") -> TranscriptScan:
    """Read a Claude transcript once and collect every artifact this session may hold a watch for."""
    scan = TranscriptScan()
    pending: dict[str, tuple[str, str]] = {}
    try:
        handle = open(path, encoding="utf-8")
    except OSError as exc:
        scan.read_error = f"{type(exc).__name__}: {exc}"
        scan.file_missing = isinstance(exc, FileNotFoundError)
        scan.stderr_lines.append(
            f"catstack-hook-error artifact-watch-rearm: cannot read transcript {path}: {scan.read_error}"
        )
        return scan
    with handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                scan.note_unreadable(path, line_number, f"JSONDecodeError: {exc}")
                continue
            if not isinstance(row, dict):
                scan.note_unreadable(path, line_number, f"row is {type(row).__name__}, not an object")
                continue
            message = row.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            role = message.get("role") if isinstance(message, dict) else None
            if role == "user" and isinstance(content, str):
                _note_user_text(scan, content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    scan.note_unreadable(path, line_number, f"content block is {type(block).__name__}, not an object")
                    continue
                if block.get("type") == "tool_use":
                    _note_tool_use(scan, block, pending)
                elif block.get("type") == "tool_result":
                    _note_tool_result(scan, block, pending)
                elif role == "user" and block.get("type") == "text":
                    _note_user_text(scan, _text_of([block]))
    if prompt:
        _note_user_text(scan, prompt)
    if scan.unreadable_lines:
        scan.stderr_lines.append(
            f"catstack-hook-error artifact-watch-rearm: {scan.unreadable_lines} unreadable line(s) in {path}; "
            "artifacts on those lines were not seen"
        )
    return scan


def _session_key(event: dict) -> str:
    session_id = event.get("session_id")
    if isinstance(session_id, str) and session_id:
        return session_id
    return hashlib.sha256(str(event.get("transcript_path", "")).encode("utf-8")).hexdigest()[:32]


def _state_path(event: dict) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", _session_key(event))
    return os.path.join(STATE_DIR, f"{safe}.json")


def _set_key(artifact_ids: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(artifact_ids)).encode("utf-8")).hexdigest()[:16]


def _already_injected(event: dict, set_key: str, stderr_lines: list[str]) -> bool:
    path = _state_path(event)
    try:
        with open(path, encoding="utf-8") as handle:
            return set_key in json.load(handle)
    except FileNotFoundError:
        return False
    except (OSError, ValueError) as exc:
        stderr_lines.append(f"catstack-hook-error artifact-watch-rearm: state {path} unreadable ({type(exc).__name__}: {exc}); injecting")
        return False


def _remember(event: dict, set_key: str, reset: bool, stderr_lines: list[str]) -> None:
    path = _state_path(event)
    keys: list[str] = []
    if not reset:
        try:
            with open(path, encoding="utf-8") as handle:
                keys = list(json.load(handle))
        except (OSError, ValueError):
            keys = []
    keys.append(set_key)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(keys, handle)
    except OSError as exc:
        stderr_lines.append(f"catstack-hook-error artifact-watch-rearm: cannot write state {path}: {type(exc).__name__}: {exc}")


def _is_fresh_start(event: dict) -> bool:
    """A brand-new session has no transcript file yet, so a missing file there means no artifacts."""
    return event.get("hook_event_name") == SESSION_START_EVENT and event.get("source") == FRESH_START_SOURCE


def detect(event: dict) -> list[Finding]:
    """One finding naming the artifacts to re-watch, or none when there is nothing new to say."""
    transcript_path = event.get("transcript_path")
    stderr_lines = event.setdefault("_catstack_stderr_lines", [])
    if not isinstance(transcript_path, str) or not transcript_path:
        stderr_lines.append("catstack-hook-error artifact-watch-rearm: payload has no transcript_path; nothing checked")
        return []
    prompt = event.get("prompt") if isinstance(event.get("prompt"), str) else ""
    scan = scan_transcript(transcript_path, prompt)
    if scan.file_missing and _is_fresh_start(event):
        return []
    stderr_lines.extend(scan.stderr_lines)
    artifact_ids = scan.candidates()
    if not artifact_ids:
        return []
    is_session_start = event.get("hook_event_name") == SESSION_START_EVENT
    set_key = _set_key(artifact_ids)
    if not is_session_start and _already_injected(event, set_key, stderr_lines):
        return []
    _remember(event, set_key, reset=is_session_start, stderr_lines=stderr_lines)
    urls = ", ".join(ARTIFACT_URL_FORMAT.format(artifact_id=artifact_id) for artifact_id in artifact_ids)
    return [Finding(
        rule_id=RULE_MISSING_WATCH,
        subject=",".join(artifact_ids),
        message=MESSAGE.format(urls=urls),
        evidence=f"{len(artifact_ids)} artifact(s) in {transcript_path}; {scan.unreadable_lines} unreadable line(s)",
    )]
