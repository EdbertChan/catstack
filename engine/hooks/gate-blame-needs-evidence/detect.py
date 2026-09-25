"""gate-blame-needs-evidence: judge unread gate blame in the background."""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(HERE)
SDK_DIR = os.path.join(HOOKS_DIR, "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from finding import Finding  # noqa: E402
LLM_JUDGE_DIR = os.path.join(HOOKS_DIR, "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

HOOK_PATH_RE = re.compile(r"hooks/([A-Za-z0-9][\w.-]*)/")
NAMED_GATE_RE = re.compile(
    r"(?<![\w./-])([A-Za-z][\w]*(?:[-_][\w]+)+)\s+(hook|gate|lock|guard|checker|check|validator|linter)s?\b",
    re.IGNORECASE,
)
SCRIPT_RE = re.compile(r"(?<![\w.-])(?:[~$\w.-]*/)*([\w-]+)\.(?:py|sh|mjs|cjs|js|ts)\b")
SCRIPT_GATE_WORDS = {
    "check", "checks", "checker", "lint", "linter", "validate", "validator",
    "gate", "guard", "lock", "rules", "policy", "verify",
}

DELETE_HOOK_FILES_RE = re.compile(r"\brm\s+[^\n|;&]*?hooks/([A-Za-z0-9][\w.-]*)/")

TOOL_REFUSAL_RE = re.compile(r"hook error:(?:\s|\\n)*\[[^\]]*?hooks/([A-Za-z0-9][\w.-]*)/")
STOP_FEEDBACK_RE = re.compile(r"hook feedback:(?:\s|\\n)*\[[^\]]*?hooks/([A-Za-z0-9][\w.-]*)/")
READ_VERB_RE = re.compile(
    r"^\s*(?:sudo\s+)?(?:cat|bat|less|more|head|tail|nl|sed|awk|grep|egrep|rg|view|git\s+show|git\s+diff)\b"
)
SEGMENT_SPLIT_RE = re.compile(r"\|\|?|&&|;|\n")
BASH_INPUT_RE = re.compile(r"<bash-input>(.*?)</bash-input>", re.DOTALL)
CITATION_RE = re.compile(
    r"(?<![\w.-])((?:[~$\w.-]*/)*[\w.-]+\.(?:py|sh|mjs|cjs|js|ts|json|md|ya?ml|toml))`?"
    r"(?::L?\d+|#L\d+|,?\s+lines?\s+\d+|\s+at\s+lines?\s+\d+)",
    re.IGNORECASE,
)

STOP_MESSAGE = (
    "gate-blame-needs-evidence: this reply makes a claim about a gate -- that it is "
    "broken, still fires, clears a certain way, or should be switched off -- but this session holds no "
    "successful read of its source. A blocked or failed read does not count, and quoting the gate's "
    "refusal message is not quoting its rule. Read the gate source and cite the rule that fired as file:line "
    "before saying the gate is broken, saying how it clears, or asking the user to disable it or delete "
    "its files. If every tool is blocked, say so and ask the user for that one file, not to switch the "
    "gate off."
)
UNCHECKED_MESSAGE = (
    "gate-blame-needs-evidence: unchecked, letting this reply through: it blames {gates} but {why}, so "
    "whether the gate's source was read is unknown."
)
RULE_UNREAD_GATE = "gate-blame-needs-evidence.unread-gate"


def known_gate_names(hooks_dir: str = HOOKS_DIR) -> set[str]:
    try:
        entries = os.listdir(hooks_dir)
    except OSError as exc:
        sys.stderr.write(
            f"gate-blame-needs-evidence: cannot list {hooks_dir} ({exc!r}); matching gate names by shape only\n"
        )
        return set()
    return {
        name for name in entries
        if not name.startswith((".", "_")) and os.path.isdir(os.path.join(hooks_dir, name))
    }


def _gate(name: str, kind: str) -> dict:
    if kind == "script":
        pattern = r"(?<![\w.-])" + re.escape(name) + r"(?![\w.-])"
    else:
        pattern = r"(?<![\w.-])" + re.escape(name) + r"(?:/|\.\w{1,5}\b)"
    return {"name": name, "kind": kind, "read_re": re.compile(pattern)}


def gates_in(text: str, known: set[str]) -> list[dict]:
    found: dict[str, dict] = {}

    def add(name: str, kind: str, at: int) -> None:
        if name not in found:
            found[name] = dict(_gate(name, kind), at=at)

    for name in known:
        for match in re.finditer(r"(?<![\w.-])" + re.escape(name) + r"(?![\w-])", text):
            add(name, "hook", match.start())
            break
    for match in HOOK_PATH_RE.finditer(text):
        add(match.group(1), "hook", match.start())
    for match in NAMED_GATE_RE.finditer(text):
        ident, noun = match.group(1), match.group(2).lower()
        joined = f"{ident}-{noun}"
        name = joined if joined in known else ident
        add(name, "hook" if name in known else "named", match.start())
    for match in SCRIPT_RE.finditer(text):
        stem = match.group(1)
        if set(re.split(r"[-_]", stem.lower())) & SCRIPT_GATE_WORDS:
            basename = match.group(0).rsplit("/", 1)[-1]
            add(basename, "script", match.start())
    return [
        {k: v for k, v in gate.items() if k != "at"}
        for gate in sorted(found.values(), key=lambda g: g["at"])
    ]


def delete_requests(message: str) -> list[dict]:
    return [
        _gate(match.group(1), "hook")
        for match in DELETE_HOOK_FILES_RE.finditer(message or "")
    ]


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


def _content(data: dict):
    message = data.get("message")
    return message.get("content") if isinstance(message, dict) else data.get("content")


def latest_refusal_gate(lines: list[dict]) -> list[dict]:
    for pattern in (TOOL_REFUSAL_RE, STOP_FEEDBACK_RE):
        for data in reversed(lines):
            if data.get("type") != "user":
                continue
            matches = pattern.findall(json.dumps(data))
            if matches:
                return [_gate(matches[-1], "hook")]
    return []


def successful_reads(lines: list[dict]) -> list[str]:
    errored: set[str] = set()
    for data in lines:
        content = _content(data)
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result" and block.get("is_error"):
                errored.add(str(block.get("tool_use_id")))
    reads: list[str] = []
    for data in lines:
        content = _content(data)
        if data.get("type") == "user":
            text = content if isinstance(content, str) else json.dumps(content or "")
            for command in BASH_INPUT_RE.findall(text):
                reads.extend(_read_segments(command))
            continue
        if data.get("type") != "assistant" or not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if str(block.get("id")) in errored:
                continue
            name = block.get("name")
            tool_input = block.get("input") or {}
            if name in ("Read", "NotebookRead"):
                reads.append(str(tool_input.get("file_path") or tool_input.get("notebook_path") or ""))
            elif name == "Grep":
                reads.append(str(tool_input.get("path") or ""))
            elif name == "Bash":
                reads.extend(_read_segments(str(tool_input.get("command") or "")))
    return [r for r in reads if r]


def _read_segments(command: str) -> list[str]:
    return [segment for segment in SEGMENT_SPLIT_RE.split(command) if READ_VERB_RE.search(segment)]


def cites_gate(gate: dict, message: str, hooks_dir: str = HOOKS_DIR) -> bool:
    for match in CITATION_RE.finditer(message or ""):
        path = match.group(1)
        if "/" in path:
            if gate["read_re"].search(path):
                return True
            continue
        if gate["kind"] == "script":
            if path == gate["name"]:
                return True
        elif os.path.isfile(os.path.join(hooks_dir, gate["name"], path)):
            return True
    return False


def _where(gate: dict, hooks_dir: str) -> str:
    if gate["kind"] == "script":
        return f"`{gate['name']}`"
    detector = os.path.join(hooks_dir, gate["name"], "detect.py")
    if os.path.isfile(detector):
        return f"`{detector}`"
    if os.path.isdir(os.path.join(hooks_dir, gate["name"])):
        return f"the files under `{os.path.join(hooks_dir, gate['name'])}/`"
    return f"the file that defines `{gate['name']}`"


def unread_gates(message: str, lines: list[dict], hooks_dir: str = HOOKS_DIR) -> list[dict]:
    known = known_gate_names(hooks_dir)
    out: dict[str, dict] = {}
    for gate in gates_in(message or "", known) + delete_requests(message or ""):
        out.setdefault(gate["name"], gate)
    if not out:
        for gate in latest_refusal_gate(lines):
            out.setdefault(gate["name"], gate)
    reads = successful_reads(lines)
    return [
        gate for gate in out.values()
        if not any(gate["read_re"].search(r) for r in reads)
        and not cites_gate(gate, message, hooks_dir)
    ]


def _is_assistant_line(data: dict) -> bool:
    if data.get("type") == "assistant":
        return True
    message = data.get("message")
    return isinstance(message, dict) and message.get("role") == "assistant"


def _message_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return ""


def resolve_transcript(payload: dict) -> str:
    agent = payload.get("agent_transcript_path")
    if isinstance(agent, str):
        return agent if os.path.isfile(agent) else ""
    direct = payload.get("transcript_path") or payload.get("transcriptPath")
    if isinstance(direct, str) and os.path.isfile(direct):
        return direct
    conv = payload.get("conversation_id") or payload.get("conversationId")
    if isinstance(conv, str) and conv.strip():
        conv = conv.strip()
        root = os.path.join(os.path.expanduser("~"), ".cursor", "projects")
        try:
            for project in os.listdir(root):
                candidate = os.path.join(root, project, "agent-transcripts", conv, f"{conv}.jsonl")
                if os.path.isfile(candidate):
                    return candidate
        except OSError:
            pass
    return ""


def last_assistant_from_transcript(path: str) -> str:
    if not path or not os.path.isfile(path):
        return ""
    last = ""
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(data, dict) or not _is_assistant_line(data):
                    continue
                text = _message_text(data)
                if text.strip():
                    last = text
    except OSError:
        return ""
    return last


def last_assistant_text(payload: dict, transcript_path: str = "") -> str:
    for key in (
        "last_assistant_message",
        "last-assistant-message",
        "lastAssistantMessage",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return last_assistant_from_transcript(transcript_path)


def _on_hit(base: str, gates: list[dict], hooks_dir: str) -> str:
    names = ", ".join(f"`{gate['name']}`" for gate in gates)
    locations = " and ".join(_where(gate, hooks_dir) for gate in gates)
    return (
        f"{base} Gates: {names}. "
        f"Read: {locations}."
    )


@functools.cache
def _judge():
    spec = importlib.util.spec_from_file_location("llm_judge", LLM_JUDGE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge from {LLM_JUDGE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@functools.cache
def _phrases():
    spec = importlib.util.spec_from_file_location("llm_judge_phrases", PHRASES_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load llm-judge phrases from {PHRASES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _transcript_problem(payload: dict, path: str) -> str:
    supplied = (
        payload.get("agent_transcript_path")
        or payload.get("transcript_path")
        or payload.get("transcriptPath")
    )
    if isinstance(supplied, str) and supplied and not path:
        return f"the transcript could not be read ({supplied!r})"
    if not path:
        return "the payload names no transcript"
    return ""


def enqueue_judge(payload: dict, hooks_dir: str = HOOKS_DIR) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    if _judge().is_subagent_payload(payload):
        return None
    path = resolve_transcript(payload)
    problem = _transcript_problem(payload, path)
    if problem:
        return None
    text = last_assistant_text(payload, path)
    if not text.strip():
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            lines = parse_lines(handle)
    except OSError as exc:
        sys.stderr.write(
            f"{UNCHECKED_MESSAGE.format(gates='a gate', why=f'the transcript could not be read ({exc!r})')}\n"
        )
        return None
    gates = unread_gates(text, lines, hooks_dir)
    if not gates:
        return None
    dictionary = _phrases().load("gate-blame-needs-evidence")
    job = _phrases().job(dictionary, path, text)
    job["id"] = uuid.uuid4().hex
    job["on_hit"] = _on_hit(str(job["on_hit"]), gates, hooks_dir)
    return _judge().enqueue(job)


def detect(event: dict[str, object]) -> list[Finding]:
    """Return one finding for each gate blamed without source evidence."""
    if event.get("stop_hook_active") or event.get("agent_id"):
        return []
    event_name = str(
        event.get("hook_event_name")
        or event.get("hookEventName")
        or event.get("event")
        or ""
    ).lower()
    if event_name == "subagentstop":
        return []
    transcript_path = resolve_transcript(event)
    if _transcript_problem(event, transcript_path):
        return []
    message = last_assistant_text(event, transcript_path)
    if not message.strip():
        return []
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = parse_lines(handle)
    except OSError:
        return []

    gates = unread_gates(message, lines)
    return [
        Finding(
            rule_id=RULE_UNREAD_GATE,
            subject=_where(gate, HOOKS_DIR),
            message=_on_hit(STOP_MESSAGE, [gate], HOOKS_DIR),
            evidence=f"{gate['name']} source was not successfully read in this session",
        )
        for gate in gates
    ]


def try_enqueue_judge(payload: dict, hooks_dir: str = HOOKS_DIR) -> None:
    try:
        if isinstance(payload, dict):
            path = resolve_transcript(payload)
            problem = _transcript_problem(payload, path)
            if problem:
                text = last_assistant_text(payload, "")
                known = known_gate_names(hooks_dir)
                if not gates_in(text, known) and not delete_requests(text):
                    return
                sys.stderr.write(f"{UNCHECKED_MESSAGE.format(gates='a gate', why=problem)}\n")
                return
        enqueue_judge(payload, hooks_dir)
    except Exception as exc:
        print(f"catstack-hook-error gate-blame-needs-evidence: {type(exc).__name__}: {exc}", file=sys.stderr)
        return
