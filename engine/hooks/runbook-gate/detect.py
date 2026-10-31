"""Measure each step of the playbook the router injected, and refuse a done claim over an unproven hard step."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

import counters  # noqa: E402
from finding import Finding  # noqa: E402
import modes  # noqa: E402
import progress  # noqa: E402
import registry  # noqa: E402
import transcript_rows  # noqa: E402
from transcripts import codex_rollout  # noqa: E402

HOOK = "runbook-gate"
RULE_UNCHECKED = "runbook-gate.unchecked"
RULE_UNPROVEN = "runbook-gate.unproven-hard-step"
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
CLEARING_STATUSES = frozenset({STATUS_DONE, STATUS_OVERRIDDEN})
PROFILE_ADVISORY = "advisory"
PROFILE_GUIDED = "guided"
PROFILE_STRICT = "strict"
PROFILE_CEILING = {
    PROFILE_ADVISORY: registry.SOFT,
    PROFILE_GUIDED: registry.HARD,
    PROFILE_STRICT: registry.HARD,
}
BLOCKING_LEVELS = {
    PROFILE_ADVISORY: (),
    PROFILE_GUIDED: (registry.HARD,),
    PROFILE_STRICT: (registry.HARD, registry.CONDITIONAL),
}
LEVEL_STRENGTH = {registry.SOFT: 1, registry.CONDITIONAL: 2, registry.HARD: 3}
BINDING_SEPARATOR = "·"
EVIDENCE_LIMIT = 300
TRANSCRIPT_KEYS = ("agent_transcript_path", "transcript_path", "transcriptPath")
REPLY_KEYS = (
    "last_assistant_message",
    "lastAssistantMessage",
    "last-assistant-message",
    "assistant_message",
    "response",
)
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
FRONT_MATTER = re.compile(r"\A---[ \t]*\n(?P<body>.*?)\n---[ \t]*(?:\n|\Z)", re.DOTALL)
PROFILE_LINE = re.compile(r"^enforcement_profile:[ \t]*(?P<profile>[A-Za-z_-]+)[ \t]*$", re.MULTILINE)
STEP_HEADING = re.compile(r"^[ \t]{0,3}##[ \t]+(?P<number>\d+)\.[ \t]+(?P<remainder>\S.*?)[ \t]*$")
STEP_BINDING = re.compile(r"^(?P<title>.*?)\s*\[(?P<binding>[^\[\]]*)\]$")
EVIDENCE_PREFIX = "evidence:"
EVENT_PREFIX = "@"
DECLARATION = re.compile(r"\b(?P<kind>skip|override):[ \t]*(?P<reason>\S.*?)[ \t]*$", re.IGNORECASE)
DECLARATION_SKIP = "skip"
DECLARATION_OVERRIDE = "override"
LEADING_NUMBER = re.compile(r"^[ \t]*(?:[-*+][ \t]+)?(?:#{1,6}[ \t]+)?(?P<number>\d{1,2})[.)]")
DECLARED_NUMBER_FIRST = re.compile(r"\A(?P<number>\d{1,2})[.):]?[ \t]+(?P<reason>\S.*)\Z")
STEP_WORD_NUMBER = re.compile(r"\bstep[ \t]+(?P<number>\d{1,2})\b", re.IGNORECASE)
FENCED_BLOCK = re.compile(r"```.*?```", re.DOTALL)
DONE_CLAIM = re.compile(
    r"(?:^|[.!:\n]\s*|\*\*)(?:done|shipped|landed|finished|complete)\b"
    r"|\b(?:is|are|now|been|all|everything)[ \t]+(?:already[ \t]+|now[ \t]+|fully[ \t]+)?"
    r"(?:done|complete|finished|shipped|landed|passing|green)\b"
    r"|\b(?:ready[ \t]+to[ \t]+(?:ship|merge|land))\b"
    r"|\b(?:the[ \t]+playbook[ \t]+is[ \t]+(?:done|complete))\b",
    re.IGNORECASE,
)
NEGATED_DONE_CLAIM = re.compile(
    r"\b(?:not|never|no[ \t]+longer|isn't|aren't|wasn't|hasn't|haven't|won't|can't)[ \t]+"
    r"(?:been[ \t]+|yet[ \t]+|actually[ \t]+|fully[ \t]+|quite[ \t]+)*"
    r"(?:done|complete|finished|shipped|landed|passing|green|ready)\b",
    re.IGNORECASE,
)
OVERRIDE_SYNTAX = "override: <N> <reason>"


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
class Playbook:
    """The injected playbook: its name, its source, the profile it declares, and its bound steps."""

    name: str
    source: str
    profile: str
    steps: list[Step]


@dataclass(frozen=True)
class Session:
    """The pools of session text this gate decides a step's status and a done claim from."""

    transcript: str
    injections: list[str]
    reply_lines: list[str]
    tool_result_text: str
    last_reply: str


@dataclass(frozen=True)
class Resolved:
    """One step after measurement: its status, the level it reaches here, and why that is not the declared one."""

    step: Step
    measured: Measured
    level: str
    level_reason: str


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
    last_reply = ""
    for row in rows:
        for text in row_strings(row):
            if INJECTION_MARKER in text and INJECTION.search(text):
                injections.append(text)
        reply = reply_text(row)
        if reply:
            reply_lines.extend(reply.splitlines())
            last_reply = reply
        result = tool_result_text(row)
        if result:
            results.append(result)
    return Session(path, injections, reply_lines, "\n".join(results), last_reply)


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


def parse_profile(text: str) -> str:
    """The enforcement profile one playbook declares in its front matter, empty when it declares none."""
    front_matter = FRONT_MATTER.match(text)
    if front_matter is None:
        return ""
    declared = PROFILE_LINE.search(front_matter.group("body"))
    if declared is None:
        return ""
    return declared.group("profile").strip().strip("\"'").lower()


def read_playbook(name: str, sources: list[str]) -> Playbook:
    """Parse the injected playbook's steps and profile, or refuse rather than report nothing."""
    problems = []
    for source in reversed(sources):
        try:
            text = Path(source).read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            problems.append(f"{source}: playbook unreadable ({error})")
            continue
        steps = parse_steps(text)
        if not steps:
            problems.append(f"{source}: playbook has no bound step lines")
            continue
        profile = parse_profile(text)
        if profile not in PROFILE_CEILING:
            raise Unchecked(
                f"{source}: enforcement_profile is {profile or 'missing'}, not "
                f"{', '.join(sorted(PROFILE_CEILING))}; no step's level could be resolved"
            )
        return Playbook(name=name, source=source, profile=profile, steps=steps)
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
        reason = declaration.group("reason")
        number = declared_number(line, declaration.start())
        if number is None:
            number, reason = numbered_reason(reason)
        if number is None:
            continue
        found[number] = (declaration.group("kind").lower(), reason)
    return found


def numbered_reason(reason: str) -> tuple[int | None, str]:
    """The step number and reason of the documented `override: <N> <reason>` form."""
    written = DECLARED_NUMBER_FIRST.match(reason)
    if written is None:
        return None, reason
    return int(written.group("number")), written.group("reason")


def step_status(step: Step, session: Session, declared: dict[int, tuple[str, str]], overrides_allowed: bool) -> Measured:
    """This step's status and where the proof for it is."""
    if step.evidence_key and names_evidence(session.tool_result_text, step.evidence_key):
        proof = f"a tool result in {session.transcript} names evidence key {step.evidence_key}"
        return Measured(STATUS_DONE, proof, "", step.evidence_key)
    written = declared.get(step.number)
    if written is not None:
        kind, reason = written
        if kind == DECLARATION_SKIP:
            return Measured(STATUS_SKIPPED, f"the reply said skip: {reason}", reason, "")
        if overrides_allowed:
            return Measured(STATUS_OVERRIDDEN, f"the reply said override: {reason}", reason, "")
        return Measured(
            STATUS_UNKNOWN,
            f"the reply said override: {reason}, and this rule's policy never allows an override",
            reason,
            "",
        )
    if not step.evidence_key:
        proof = f"the {step.level or 'unlevelled'} binding names no evidence key to look for"
        return Measured(STATUS_UNKNOWN, proof, "", "")
    proof = f"no tool result in {session.transcript} names evidence key {step.evidence_key}"
    return Measured(STATUS_UNKNOWN, proof, "", "")


def step_policy(step: Step, level: str, hook_policy: registry.EnforcementPolicy) -> registry.EnforcementPolicy:
    """The hook's enforcement policy restated for one step, so a step's level is checked like any rule's."""
    return registry.EnforcementPolicy(
        default=level,
        capability=hook_policy.capability,
        evidence=(step.evidence_key,) if step.evidence_key else (),
        override=hook_policy.override,
    )


def ceilinged_level(step: Step, profile: str) -> tuple[str, str]:
    """This step's declared level after the playbook's profile ceiling has lowered it."""
    ceiling = PROFILE_CEILING[profile]
    declared = step.level if step.level in LEVEL_STRENGTH else ""
    if not declared:
        return declared, f"the binding declares level {step.level or 'none'}, which is not a level this gate knows"
    if LEVEL_STRENGTH[declared] <= LEVEL_STRENGTH[ceiling]:
        return declared, ""
    return ceiling, f"the {profile} profile lowers a {declared} step to {ceiling}"


def resolve_step(
    step: Step,
    measured: Measured,
    profile: str,
    hook_policy: registry.EnforcementPolicy,
    harness: str,
    event: dict[str, object],
    counts: dict[str, int],
) -> Resolved:
    """One step's status alongside the level it actually reaches on the running harness."""
    level, reason = ceilinged_level(step, profile)
    if not level:
        return Resolved(step, measured, modes.UNCHECKED_LEVEL, reason)
    checked, downgrade = modes.effective_level(step_policy(step, level, hook_policy), harness, event, counts)
    return Resolved(step, measured, checked, downgrade or reason)


def outgoing_reply(event: dict[str, object], session: Session) -> str:
    """The reply about to be delivered: the one the stop payload names, else the transcript's last."""
    for key in REPLY_KEYS:
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return session.last_reply


def claims_done(reply: str) -> bool:
    """True when the reply about to be delivered says the work is done."""
    plain = FENCED_BLOCK.sub(" ", reply)
    plain = NEGATED_DONE_CLAIM.sub(" ", plain)
    return DONE_CLAIM.search(plain) is not None


def unproven(resolved: list[Resolved], profile: str) -> list[Resolved]:
    """Every step this profile refuses over: blocking level, no proof and no override."""
    blocking = BLOCKING_LEVELS[profile]
    return [
        entry for entry in resolved
        if entry.level in blocking and entry.measured.status not in CLEARING_STATUSES
    ]


def step_finding(playbook: str, entry: Resolved) -> Finding:
    """One metrics row for one step: its rule id, its status, the level it reached, and where the proof is."""
    step, measured = entry.step, entry.measured
    reached = entry.level or "no level"
    return Finding(
        rule_id=f"{step.rule_id}.{measured.status}",
        subject=f"{playbook} step {step.number}",
        message=(
            f"{HOOK}: {playbook} step {step.number} ({step.title}) "
            f"bound to {step.rule_id} at level {step.level or 'unlevelled'} is {measured.status}; "
            f"it reaches {reached} here; {measured.proof}."
        ),
        evidence=measured.proof[:EVIDENCE_LIMIT],
        acted=ACTED_BY_STATUS[measured.status],
        runbook=playbook,
        step=str(step.number),
        override_reason=measured.override_reason,
        evidence_ref=measured.evidence_ref,
    )


def block_finding(playbook: Playbook, deficit: list[Resolved]) -> Finding:
    """The one block: the done claim, every step it outran, and the syntax that overrides each."""
    numbers = ", ".join(str(entry.step.number) for entry in deficit)
    lines = [
        f"{HOOK}: this reply claims the work is done, and {len(deficit)} "
        f"{playbook.profile} step(s) of {playbook.name} have no proof: {numbers}."
    ]
    for entry in deficit:
        key = entry.step.evidence_key or "no evidence key"
        lines.append(
            f"- step {entry.step.number} ({entry.step.title}) is {entry.level} and {entry.measured.status}: "
            f"{entry.measured.proof}. Run it so a tool result names {key}, "
            f"or write `override: {entry.step.number} <reason>` on its own line."
        )
    lines.append(
        f"The deficit is {len(deficit)} unproven step(s), not a wording problem: "
        f"run each one or override it with `{OVERRIDE_SYNTAX}`, then say the work is done."
    )
    return Finding(
        rule_id=RULE_UNPROVEN,
        subject=f"{playbook.name} steps {numbers}",
        message="\n".join(lines),
        evidence="; ".join(
            f"step {entry.step.number} {entry.level} {entry.measured.status}: {entry.measured.proof}"
            for entry in deficit
        )[:EVIDENCE_LIMIT],
        acted="acted",
        runbook=playbook.name,
        step=numbers,
        evidence_ref=", ".join(entry.step.evidence_key for entry in deficit if entry.step.evidence_key),
    )


def note_row(entry: Resolved) -> dict[str, object]:
    """One step's row in the session's progress note."""
    return {
        "step": entry.step.number,
        "rule_id": entry.step.rule_id,
        "level": entry.step.level,
        "effective_level": entry.level,
        "level_reason": entry.level_reason,
        "status": entry.measured.status,
        "evidence_ref": entry.measured.evidence_ref,
        "reason": entry.measured.override_reason,
        "proof": entry.measured.proof,
    }


def with_note_status(entry: Resolved, row: dict[str, object]) -> Resolved:
    """One resolved step restated with the status the progress note carried forward."""
    status = str(row.get("status", ""))
    if status == entry.measured.status:
        return entry
    measured = Measured(
        status=status,
        proof=str(row.get("proof", "")),
        override_reason=str(row.get("reason", "")),
        evidence_ref=str(row.get("evidence_ref", "")),
    )
    return Resolved(entry.step, measured, entry.level, entry.level_reason)


def carry_forward(resolved: list[Resolved], stored: dict[int, dict[str, object]]) -> tuple[list[Resolved], list[dict[str, object]]]:
    """Every step merged with the note from the previous stop, and the rows to store for the next one."""
    merged = []
    rows = []
    for entry in resolved:
        row = progress.carried_forward(note_row(entry), stored.get(entry.step.number))
        rows.append(row)
        merged.append(with_note_status(entry, row))
    return merged, rows


def note_stderr(event: dict[str, object], problem: str) -> None:
    """Say on stderr that the progress note could not be read or written."""
    if not problem:
        return
    lines = event.get("_catstack_stderr_lines")
    if not isinstance(lines, list):
        lines = []
        event["_catstack_stderr_lines"] = lines
    lines.append(f"catstack-hook-error {HOOK}: {problem}")


def silent(event: dict[str, object], findings: list[Finding]) -> None:
    """Hand the per-step measurement rows to the runtime as rows that are logged and never rendered."""
    if not findings:
        return
    channel = event.get("_catstack_silent_findings")
    if not isinstance(channel, list):
        channel = []
        event["_catstack_silent_findings"] = channel
    channel.extend(findings)


def hook_policy(event: dict[str, object]) -> registry.EnforcementPolicy:
    """This hook's enforcement policy, or a refusal when the registry cannot supply one."""
    try:
        policy = modes.enforcement_policy(HOOK, event)
    except Exception as error:
        raise Unchecked(f"enforcement policy unread ({type(error).__name__}: {error})") from error
    if policy is None:
        raise Unchecked(f"{HOOK} declares no enforcement policy, so no step's level could be resolved")
    return policy


def measure(event: dict[str, object]) -> list[Finding]:
    """The per-step rows for this session's playbook, plus the one block a done claim earns."""
    session = read_session(transcript_path(event))
    routed = last_injection(session.injections)
    if routed is None:
        return []
    name, sources = routed
    playbook = read_playbook(name, sources)
    policy = hook_policy(event)
    harness = str(event.get("_catstack_harness") or "")
    counts = counters.session_counters(event)
    overrides_allowed = policy.override != "never"
    declared = declarations(session.reply_lines)
    resolved = [
        resolve_step(
            step,
            step_status(step, session, declared, overrides_allowed),
            playbook.profile,
            policy,
            harness,
            event,
            counts,
        )
        for step in playbook.steps
    ]
    path = progress.note_path(counters.session_key(event))
    stored, read_problem = progress.read_note(path)
    note_stderr(event, read_problem)
    resolved, rows = carry_forward(resolved, progress.stored_steps(stored))
    note_stderr(event, progress.write_note(path, progress.build_note(
        playbook.name, playbook.profile, playbook.source, rows)))
    silent(event, [step_finding(playbook.name, entry) for entry in resolved])
    if not claims_done(outgoing_reply(event, session)):
        return []
    deficit = unproven(resolved, playbook.profile)
    if not deficit:
        return []
    return [block_finding(playbook, deficit)]


def detect(event: dict[str, object]) -> list[Finding]:
    """The block this stop earns, or one unchecked finding when an input could not be read."""
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
