"""Measure each step of the playbook the router injected this session."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402
import transcript_rows  # noqa: E402
from transcripts import codex_rollout  # noqa: E402

HOOK = "runbook-gate"
RULE_UNCHECKED = "runbook-gate.unchecked"
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
STATUS_OVERRIDDEN = "overridden"
STATUS_UNKNOWN = "unknown"
ACTED_BY_STATUS = {
    STATUS_DONE: "acted",
    STATUS_SKIPPED: "ignored",
    STATUS_OVERRIDDEN: "overridden",
    STATUS_UNKNOWN: "unknown",
}
ACTED_UNKNOWN = ACTED_BY_STATUS[STATUS_UNKNOWN]
BINDING_SEPARATOR = "·"
EVIDENCE_LIMIT = 300
TRANSCRIPT_KEYS = ("agent_transcript_path", "transcript_path", "transcriptPath")
TOOL_RESULT_TYPES = frozenset({
    "tool_result", "tool-result", "toolResult",
    "function_call_output", "custom_tool_call_output",
})
INJECTION_MARKER = "Playbook:"
INJECTION = re.compile(
    r"^Playbook:[ \t]*(?P<name>[a-z0-9][a-z0-9-]*)[ \t]*\n"
    r"Read and apply the full source at (?P<sources>.+?), including its constraints\.",
    re.MULTILINE,
)
SOURCE_SEPARATOR = " and "
STEP_HEADING = re.compile(r"^[ \t]{0,3}##[ \t]+(?P<number>\d+)\.[ \t]+(?P<remainder>\S.*?)[ \t]*$")
STEP_BINDING = re.compile(r"^(?P<title>.*?)\s*\[(?P<binding>[^\[\]]*)\]$")
EVIDENCE_PREFIX = "evidence:"
EVENT_PREFIX = "@"
DECLARATION = re.compile(r"\b(?P<kind>skip|override):[ \t]*(?P<reason>\S.*?)[ \t]*$", re.IGNORECASE)
DECLARATION_SKIP = "skip"
LEADING_NUMBER = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?(?:#{1,6}[ \t]+)?(?P<number>\d{1,2})[.)]")
STEP_WORD_NUMBER = re.compile(r"\bstep[ \t]+(?P<number>\d{1,2})\b", re.IGNORECASE)


class Unchecked(Exception):
    """Raised when the session or its playbook cannot be read, so no step is reported clean."""


@dataclass(frozen=True)
class Step:
    """One `## N. Title [rule-id · level · evidence: key · @event]` line of a playbook."""

    number: int
    title: str
    rule_id: str
    level: str
    evidence_key: str
    event_name: str


@dataclass(frozen=True)
class Measured:
    """What one step's status is, where the proof is, and the step-log fields its row carries."""

    status: str
    proof: str
    override_reason: str
    evidence_ref: str


@dataclass(frozen=True)
class Session:
    """The three pools of session text this gate decides a step's status from."""

    transcript: str
    injections: list[str]
    reply_lines: list[str]
    tool_result_text: str


def transcript_path(event: dict[str, object]) -> str:
    """The session transcript this stop payload names, across the three harnesses."""
    for key in TRANSCRIPT_KEYS:
        value = event.get(key)
        if isinstance(value, str) and value:
            return value
    return codex_rollout(event)


def block_text(content: object) -> str:
    """Flatten one transcript content field into plain text."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                nested = block.get("text")
                if nested is None:
                    nested = block.get("content")
                if isinstance(nested, (str, list)):
                    parts.append(block_text(nested))
        return "\n".join(parts)
    return ""


def row_strings(node: object) -> list[str]:
    """Every string anywhere inside one transcript row."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [text for value in node.values() for text in row_strings(value)]
    if isinstance(node, list):
        return [text for value in node for text in row_strings(value)]
    return []


def reply_text(row: dict[str, object]) -> str:
    """Text the agent itself wrote in one transcript row."""
    message = transcript_rows.message(row)
    role = message.get("role") or row.get("role") or row.get("type")
    if role == "assistant":
        return block_text(message.get("content") if message else row.get("content"))
    payload = row.get("payload")
    if isinstance(payload, dict) and payload.get("type") == "message" and payload.get("role") == "assistant":
        return block_text(payload.get("content"))
    return ""


def tool_result_text(row: dict[str, object]) -> str:
    """Text a tool handed back in one transcript row."""
    parts = []
    message = transcript_rows.message(row)
    content = message.get("content") if message else row.get("content")
    if isinstance(content, list):
        parts.extend(
            block_text(block.get("content"))
            for block in content
            if isinstance(block, dict) and block.get("type") in TOOL_RESULT_TYPES
        )
    payload = row.get("payload")
    if isinstance(payload, dict) and payload.get("type") in TOOL_RESULT_TYPES:
        parts.append(block_text(payload.get("output")))
    return "\n".join(part for part in parts if part)


def read_session(path: str) -> Session:
    """Read one session transcript, or refuse rather than report its steps clean."""
    if not path:
        raise Unchecked("the stop payload named no transcript, so no injected playbook could be read")
    try:
        rows = transcript_rows.read_lines(path)
    except OSError as error:
        raise Unchecked(f"{path}: transcript unreadable ({error})") from error
    injections = []
    reply_lines: list[str] = []
    results = []
    for row in rows:
        for text in row_strings(row):
            if INJECTION_MARKER in text and INJECTION.search(text):
                injections.append(text)
        reply = reply_text(row)
        if reply:
            reply_lines.extend(reply.splitlines())
        result = tool_result_text(row)
        if result:
            results.append(result)
    return Session(path, injections, reply_lines, "\n".join(results))


def last_injection(injections: list[str]) -> tuple[str, list[str]] | None:
    """The playbook name and source paths the router injected last in this session."""
    for text in reversed(injections):
        matches = list(INJECTION.finditer(text))
        if not matches:
            continue
        match = matches[-1]
        sources = [part.strip() for part in match.group("sources").split(SOURCE_SEPARATOR) if part.strip()]
        return match.group("name"), sources
    return None


def parse_steps(text: str) -> list[Step]:
    """Every bound step line in one playbook."""
    steps = []
    for line in text.splitlines():
        heading = STEP_HEADING.match(line)
        if heading is None:
            continue
        binding = STEP_BINDING.match(heading.group("remainder"))
        if binding is None:
            continue
        parts = [part.strip() for part in binding.group("binding").split(BINDING_SEPARATOR)]
        evidence_key = ""
        event_name = ""
        for part in parts[2:]:
            if part.lower().startswith(EVIDENCE_PREFIX):
                evidence_key = part.split(":", 1)[1].strip()
            elif part.startswith(EVENT_PREFIX):
                event_name = part[len(EVENT_PREFIX):].strip()
        steps.append(Step(
            number=int(heading.group("number")),
            title=binding.group("title").strip(),
            rule_id=parts[0],
            level=parts[1].lower() if len(parts) > 1 else "",
            evidence_key=evidence_key,
            event_name=event_name,
        ))
    return steps


def read_steps(sources: list[str]) -> list[Step]:
    """Parse the steps of the injected playbook, or refuse rather than report nothing."""
    problems = []
    for source in reversed(sources):
        try:
            text = Path(source).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            problems.append(f"{source}: playbook unreadable ({error})")
            continue
        steps = parse_steps(text)
        if steps:
            return steps
        problems.append(f"{source}: playbook has no bound step lines")
    raise Unchecked("; ".join(problems) or "the injection named no playbook source")


def names_evidence(text: str, key: str) -> bool:
    """True when a tool result names this step's evidence key as a whole word."""
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])", text) is not None


def declared_number(line: str, before: int) -> int | None:
    """The step number a skip or override line points at."""
    leading = LEADING_NUMBER.match(line[:before])
    if leading:
        return int(leading.group("number"))
    numbers = list(STEP_WORD_NUMBER.finditer(line))
    return int(numbers[-1].group("number")) if numbers else None


def declarations(reply_lines: list[str]) -> dict[int, tuple[str, str]]:
    """Map each step number to the skip or override the agent wrote for it."""
    found: dict[int, tuple[str, str]] = {}
    for line in reply_lines:
        declaration = DECLARATION.search(line)
        if declaration is None:
            continue
        number = declared_number(line, declaration.start())
        if number is None:
            continue
        found[number] = (declaration.group("kind").lower(), declaration.group("reason"))
    return found


def step_status(step: Step, session: Session, declared: dict[int, tuple[str, str]]) -> Measured:
    """This step's status and where the proof for it is."""
    if step.evidence_key and names_evidence(session.tool_result_text, step.evidence_key):
        proof = f"a tool result in {session.transcript} names evidence key {step.evidence_key}"
        return Measured(STATUS_DONE, proof, "", step.evidence_key)
    written = declared.get(step.number)
    if written is not None:
        kind, reason = written
        if kind == DECLARATION_SKIP:
            return Measured(STATUS_SKIPPED, f"the reply said skip: {reason}", reason, "")
        return Measured(STATUS_OVERRIDDEN, f"the reply said override: {reason}", reason, "")
    if not step.evidence_key:
        proof = f"the {step.level or 'unlevelled'} binding names no evidence key to look for"
        return Measured(STATUS_UNKNOWN, proof, "", "")
    proof = f"no tool result in {session.transcript} names evidence key {step.evidence_key}"
    return Measured(STATUS_UNKNOWN, proof, "", "")


def step_finding(playbook: str, step: Step, measured: Measured) -> Finding:
    """One metrics row for one step: its rule id, its status, and where the proof is."""
    return Finding(
        rule_id=f"{step.rule_id}.{measured.status}",
        subject=f"{playbook} step {step.number}",
        message=(
            f"{HOOK}: {playbook} step {step.number} ({step.title}) "
            f"bound to {step.rule_id} at level {step.level or 'unlevelled'} is {measured.status}; {measured.proof}."
        ),
        evidence=measured.proof[:EVIDENCE_LIMIT],
        acted=ACTED_BY_STATUS[measured.status],
        runbook=playbook,
        step=str(step.number),
        override_reason=measured.override_reason,
        evidence_ref=measured.evidence_ref,
    )


def measure(event: dict[str, object]) -> list[Finding]:
    """One finding per step of the playbook this session routed."""
    session = read_session(transcript_path(event))
    routed = last_injection(session.injections)
    if routed is None:
        return []
    playbook, sources = routed
    declared = declarations(session.reply_lines)
    findings = []
    for step in read_steps(sources):
        findings.append(step_finding(playbook, step, step_status(step, session, declared)))
    return findings


def detect(event: dict[str, object]) -> list[Finding]:
    """One finding per routed step, or one unchecked finding when an input could not be read."""
    if event.get("stop_hook_active"):
        return []
    try:
        return measure(event)
    except Unchecked as unchecked:
        reason = str(unchecked)
        return [Finding(
            rule_id=RULE_UNCHECKED,
            subject=reason,
            message=f"{HOOK}: no playbook step was measured this session: {reason}",
            evidence=reason[:EVIDENCE_LIMIT],
            acted=ACTED_UNKNOWN,
        )]
