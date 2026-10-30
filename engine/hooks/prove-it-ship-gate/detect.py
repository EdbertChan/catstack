"""prove-it-ship-gate as a Stop hook.

The corpus prove-it-ship-gate skill is a claim-shape rule: when the
outgoing message says done / shipped / deployed / live about work with live
side effects (Linear, deploy, production host, webhook, Slack, external API),
the same message must carry live evidence or the literal prefix
a well-formed CAT-UNVERIFIED tag. Unit tests, fixtures, and UI registration do not
count. This lived only in prose; this file is the
mechanical half. Judgment (is this work really live-side-effect work) stays
with the model: the hook only matches shapes and fails open on parse errors.

Incident: Invoker PRs #10553-#10558 published cross-repo-research after unit
+ fixture + UI only; the user forced a live Linear e2e and a reflect.

No claim phrase is also a live noun. Bare "end-to-end" and "e2e" say how a
check ran, not where, and the claim list already spells "working end-to-end"
and "confirmed end-to-end" as claims, so counting the idiom as a surface would
put every such claim permanently on top of a live noun and collapse the
two-part check into one part. "Done, the parser works end-to-end" is a unit
suite. The surface in the incident was the desktop the windows opened on, and
"your machine", playwright, electron and popup already name it.

The possessive is not always glued to the noun. "your own machine" and "the
user's own screen" are the wording this repo uses everywhere -- the block
message below, the README, and the skill -- so the surface nouns accept one
qualifier ("own", "real", "actual", "personal", "local") after the possessive.
Without it the gate stays silent on exactly the phrasing it tells you to use.
"""
from __future__ import annotations

import json
import re
import os
import shlex
import sys
import hashlib

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_markers"))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

import markers  # noqa: E402
from finding import Finding  # noqa: E402

RULE_UNPROVEN_LIVE_CLAIM = "prove-it-ship-gate.unproven-live-claim"
RULE_SAME_REPRO = "prove-it-ship-gate.same-repro-not-rerun"

SHELL_TOOL_NAMES = frozenset({
    "Bash", "bash", "Shell", "shell", "Exec", "exec", "exec_command",
    "functions.exec_command", "local_shell", "shell_call",
})
EDIT_TOOL_NAMES = frozenset({
    "Write", "StrReplace", "Edit", "EditNotebook", "ApplyPatch", "apply_patch",
    "MultiEdit", "NotebookEdit", "edit_file",
})
COMMAND_PREFIXES = frozenset({"sudo", "env", "time", "command", "nohup", "nice"})
SHELL_ASSIGNMENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
GENERIC_PROGRAMS = frozenset({
    "git", "node", "python", "python3", "bash", "zsh", "sh", "ls", "cat", "rg",
    "grep", "find", "mkdir", "rm", "cp", "mv", "ln", "sed", "awk", "jq", "gh",
    "curl", "ssh", "pnpm", "npm", "npx", "vitest", "pytest", "cargo", "go",
    "make", "docker", "which", "readlink", "file", "echo", "head", "tail", "wc",
    "sort", "uniq", "tee", "xargs", "tar", "diff", "patch", "perl", "ruby",
    "open", "ps", "kill", "pwd", "date", "brew", "touch", "chmod", "mktemp",
    "cut", "tr", "printf", "cd", "export", "true", "false",
})
CLI_PROGRAM_RE = re.compile(r"^[a-z][a-z0-9]*(-[a-z][a-z0-9]*)+$")
PROCESS_SPAWN_CALL_RE = (
    r"\b(?:run|call|check_call|check_output|Popen|spawn|spawnSync|execFile|execFileSync|execa)\s*\(\s*"
)
EMBEDDED_CLI_RE = re.compile(
    PROCESS_SPAWN_CALL_RE
    + r"""\[\s*['\"]([a-z][a-z0-9]*(?:-[a-z][a-z0-9]*)+)['\"]\s*,\s*['\"]([a-z][a-z0-9-]*|--help|--version)['\"]"""
)
CLI_SUBCOMMAND_RE = re.compile(r"^[a-z][a-z0-9-]*$")
TEST_RUNNER_RE = re.compile(
    r"\bvitest\b|\bpytest\b|\bunittest\b|\bjest\b|"
    r"\bpnpm\b[^\n]{0,120}\b(?:run\s+)?test\b|\bnpm\s+test\b|"
    r"\bcargo\s+test\b|\bgo\s+test\b",
    re.IGNORECASE,
)


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
    r"confirmed live|is up and running|running in production)\b|"
    r"\bproof:\s*(?:yes|it works|confirmed)\b|"
    r"\b(?:proven|proved)\b|"
    r"\bconfirmed\s+(?:working|running|fixed|green|end[- ]to[- ]end)\b|"
    r"\b(?:all|both|everything)\b[^.!?\n]{0,60}\b(?:is|are)\s+done\b",
    re.IGNORECASE,
)
NEGATED_CLAIM_RE = re.compile(
    r"\b(?:not|never|n't|isn't|aren't|wasn't|without being|not yet|hasn't|haven't)\s+"
    r"(?:been\s+|yet\s+|actually\s+|fully\s+)?(?:shipped|deployed|live|landed|done|merged|proven|proved)\b",
    re.IGNORECASE,
)
LIVE_NOUN_RE = re.compile(
    r"\b(?:linear|deploy(?:ed|ment|s)?|production|prod|do-?1|droplet|digital\s*ocean|"
    r"webhook|slack|external api|live mine|posthog|stripe|sentry|live path|"
    r"nightly|pipeline|merge queue|(?:real|scheduled|next)\s+tick|"
    r"live (?:worker|owner|host|server|tick)|"
    r"(?:your|their|the user'?s)\s+(?:(?:own|real|actual|personal|local)\s+)?"
    r"(?:machine|mac|macbook|laptop|desktop|screen|session|computer|keyboard)|"
    r"playwright|electron|pop-?ups?)\b",
    re.IGNORECASE,
)
PROXIMITY_WINDOW = 240  # chars between a claim word and a live noun

# Evidence a reviewer can chase without trusting the narrator: a URL, a
# commit sha, a ticket/PR id, a fenced block, an exit code, a PID, or a
# timestamp. Narrative like "ran it against production" is not evidence.
EVIDENCE_RE = re.compile(
    r"https?://\S+|```|\b[0-9a-f]{7,40}\b|\b[A-Z]{2,6}-\d{1,6}\b|"
    r"\bexit[_ ]code\b|\bEXIT_CODE\b|\bPID\b|\bMainPID\b|"
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}",
    re.IGNORECASE,
)

PR_LINK_RE = re.compile(
    r"https?://\S*?/(?:pull|pull-requests|merge_requests)/\d+\S*",
    re.IGNORECASE,
)

LIVE_RECEIPT_RE = re.compile(
    r"\bwf-\d{10,}-\d+\b|actions/runs/\d+|\bdaily-\d{8}\b|"
    r"\bDelegated to live owner\b",
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


def has_live_receipt(message: str) -> bool:
    return bool(LIVE_RECEIPT_RE.search(message or ""))


def without_pr_links(message: str) -> str:
    return PR_LINK_RE.sub(" ", message or "")


def has_evidence(message: str) -> bool:
    return bool(EVIDENCE_RE.search(without_pr_links(message))) or has_live_receipt(message)


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
        if not isinstance(data, dict):
            continue
        for block in _tool_uses(data):
            if block.get("name") in SHELL_TOOL_NAMES:
                command = _shell_command(block)
                if command is not None:
                    commands.append(command)
    return commands


def _shell_command(block: dict) -> str | None:
    raw = block.get("input")
    if not isinstance(raw, dict):
        return None
    for key in ("command", "cmd"):
        value = raw.get(key)
        if isinstance(value, str):
            return value
    return None


def _tool_uses(data: dict) -> list[dict]:
    found: list[dict] = []
    message = data.get("message") if isinstance(data.get("message"), dict) else {}
    role = data.get("role") or message.get("role") or data.get("type")
    if role == "assistant":
        content = message.get("content") if message else data.get("content")
        if isinstance(content, list):
            found.extend(
                block for block in content
                if isinstance(block, dict) and block.get("type") == "tool_use"
            )
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    if isinstance(payload, dict) and payload.get("type") in {"function_call", "custom_tool_call"}:
        name = payload.get("name")
        raw = payload.get("arguments")
        if raw is None:
            raw = payload.get("input")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        if isinstance(name, str) and isinstance(raw, dict):
            found.append({"type": "tool_use", "name": name, "input": raw})
    return found


def _unquoted_segments(command: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    quote = ""
    i = 0
    while i < len(command):
        ch = command[i]
        if quote:
            buf.append(ch)
            if ch == quote and command[i - 1] != "\\":
                quote = ""
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if command.startswith("&&", i) or command.startswith("||", i) or command.startswith("<<", i):
            if command.startswith("<<", i):
                break
            parts.append("".join(buf))
            buf = []
            i += 2
            continue
        if ch in ";&|\n":
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def surface_keys(command: str) -> list[str]:
    """Program plus subcommand for a real CLI invocation. Empty for scripts,
    pipelines of unix tools, and test runners."""
    keys: list[str] = []
    for segment in _unquoted_segments(command):
        try:
            words = shlex.split(segment, posix=True)
        except ValueError:
            continue
        while words and (words[0] in COMMAND_PREFIXES or SHELL_ASSIGNMENT_RE.match(words[0])):
            words = words[1:]
        if not words:
            continue
        program = os.path.basename(words[0])
        if program in GENERIC_PROGRAMS or not CLI_PROGRAM_RE.fullmatch(program):
            continue
        subcommand = ""
        for word in words[1:]:
            if word in ("--help", "--version"):
                subcommand = word
                break
            if word.startswith("-"):
                continue
            if CLI_SUBCOMMAND_RE.fullmatch(word):
                subcommand = word
            break
        keys.append(f"{program} {subcommand}".strip())
    for program, subcommand in EMBEDDED_CLI_RE.findall(command):
        if CLI_SUBCOMMAND_RE.fullmatch(subcommand) or subcommand in ("--help", "--version"):
            keys.append(f"{program} {subcommand}")
    return keys


def _is_test_runner(command: str) -> bool:
    return bool(TEST_RUNNER_RE.search(command))


def _read_events(path: str) -> list[tuple[str, str]] | None:
    events: list[tuple[str, str]] = []
    try:
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    for raw in lines:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        for block in _tool_uses(data):
            name = block.get("name")
            if name in EDIT_TOOL_NAMES:
                events.append(("edit", ""))
            elif name in SHELL_TOOL_NAMES:
                command = _shell_command(block)
                if command is not None:
                    events.append(("cmd", command))
    return events


def _session_paths(transcript_path: str) -> list[str]:
    paths = [transcript_path]
    parent = os.path.dirname(transcript_path)
    if os.path.basename(parent) == "subagents":
        session_dir = os.path.dirname(parent)
        for name in os.listdir(session_dir):
            candidate = os.path.join(session_dir, name)
            if name.endswith(".jsonl") and os.path.isfile(candidate):
                paths.append(candidate)
        paths.extend(
            os.path.join(parent, name)
            for name in os.listdir(parent)
            if name.endswith(".jsonl")
        )
    else:
        subagents = os.path.join(parent, "subagents")
        if os.path.isdir(subagents):
            paths.extend(
                os.path.join(subagents, name)
                for name in sorted(os.listdir(subagents))
                if name.endswith(".jsonl")
            )
    seen: list[str] = []
    for path in paths:
        if path not in seen:
            seen.append(path)
    return seen


def same_repro_gap(transcript_path: str) -> list[str] | None:
    """Commands that showed the real program and were not run again after the
    last edit. None when the transcript cannot be read (fail open)."""
    if not transcript_path:
        return []
    primary = _read_events(transcript_path)
    if primary is None:
        return None
    last_edit = None
    previous_edit = -1
    for index, (kind, _command) in enumerate(primary):
        if kind == "edit":
            previous_edit, last_edit = (last_edit if last_edit is not None else -1), index
    if last_edit is None:
        return []
    if not any(kind == "cmd" and _is_test_runner(command) for index, (kind, command) in enumerate(primary) if index > last_edit):
        return []
    seen: set[str] = set()
    for path in _session_paths(transcript_path):
        if path == transcript_path:
            window = primary[previous_edit + 1:last_edit]
        else:
            window = _read_events(path) or []
        for kind, command in window:
            if kind == "cmd":
                seen.update(surface_keys(command))
    rerun: set[str] = set()
    for index, (kind, command) in enumerate(primary):
        if index > last_edit and kind == "cmd":
            rerun.update(surface_keys(command))
    return sorted(seen - rerun)


def _same_repro_feedback(payload: dict[str, object]) -> str | None:
    transcript_path = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
        or ""
    )
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    missing = same_repro_gap(transcript_path)
    if not missing:
        return None
    listed = ", ".join(f"`{command}`" for command in missing)
    return (
        "prove-it-ship-gate: the real command that showed the behavior was "
        f"{listed}. A later edit was checked with a test runner instead of that "
        "command. Rerun the same program and subcommand and paste its output. "
        "A vitest, pnpm test, or pytest run does not replace it."
    )


def detect(event: dict[str, object]) -> list[Finding]:
    """Return findings for unproven live ship claims."""
    findings: list[Finding] = []
    message = _blocking_feedback(event)
    reply = event.get("last_assistant_message") or ""
    reply_text = reply if isinstance(reply, str) else ""
    if message:
        findings.append(Finding(
            rule_id=RULE_UNPROVEN_LIVE_CLAIM,
            subject="reply:" + hashlib.sha256(reply_text.encode("utf-8")).hexdigest(),
            message=message,
            evidence=reply_text[:500],
        ))
    same = _same_repro_feedback(event)
    if same:
        findings.append(Finding(
            rule_id=RULE_SAME_REPRO,
            subject="same-repro:" + hashlib.sha256(same.encode("utf-8")).hexdigest(),
            message=same,
            evidence=same[:500],
        ))
    return findings


def decide(payload: dict) -> str | None:
    """Return blocking feedback, or None to let the turn finish."""
    findings = detect(payload if isinstance(payload, dict) else {})
    return findings[0].message if findings else None


def _blocking_feedback(payload: dict[str, object]) -> str | None:
    message = payload.get("last_assistant_message") or ""
    if not isinstance(message, str):
        message = ""
    if not claims_live_ship(message):
        return None
    if markers.well_formed_tags(message) or has_evidence(message):
        return None
    transcript_path = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
        or ""
    )
    if transcript_path:
        commands = bash_commands_this_turn(transcript_path)
        if commands is None:
            return None  # unreadable transcript: fail open
        if any(LIVE_COMMAND_RE.search(c) for c in commands):
            return None
    return (
        "prove-it-ship-gate: this message claims done/shipped/live/proven for work "
        "with a live side effect (Linear, deploy, production host, webhook, external "
        "API, or the user's own machine, session, or screen) but shows no live "
        "evidence -- no URL, sha, ticket id, fenced output, exit code, live-output "
        "receipt, or live command this turn. Fixture tests, UI registration, a dry "
        "run, and the PR number or PR link of this change do not prove the live path "
        "ran; only an id the pipeline itself emitted does (a workflow id, "
        "an Actions run URL, a release tag, a live-owner dispatch). Paste that "
        "evidence in this message, or tag the claim: "
        f"`{markers.TAG_TEMPLATE}`."
    )
