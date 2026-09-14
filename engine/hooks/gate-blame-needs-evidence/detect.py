"""gate-blame-needs-evidence: blaming a gate needs a read of the gate.

A reply that says a hook, gate, lock or checker is broken, still fires when
it should not, clears a certain way, or should be switched off, is a claim
about that gate's rule. The claim needs the rule: a successful Read / cat of
a file under the gate's directory somewhere in the session, or a file:line
citation of the gate's source in the reply itself. Without either, the Stop
hook sends the reply back once, asking for the gate's own rule.

Seen once: a scope-lock hard stop held for an hour while the assistant told
the user "its stated clear condition is met and it still fires", asked for
the hook to be removed, and suggested deleting guessed state files -- all
before any successful read of detect.py. The hook was working as written.

A blocked read is not a read: a Read or cat whose tool result is an error
(the gate refusing its own source, a missing file) does not count. Quoting
the gate's refusal message is not quoting its rule; only a source citation
(`detect.py:159`, `detect.py line 159`) counts.

The gate is named in the blame sentence or the ones beside it: a hook
directory name (scope-lock), `<name> hook|gate|lock|guard|checker`, a
`hooks/<name>/` path, or a checker script (review-unit-rules.mjs). A
sentence like "it still fires" with no name falls back to the hook that
last refused a tool call in the transcript (a Stop hook's feedback only when
no tool was refused), plus the gates named elsewhere in the reply.

Three outcomes. hit: the reply goes back with the message (exit 2). clean:
no gate blame, or every blamed gate was read or cited. unchecked: the reply
blames a gate but the transcript could not be read, so the hook cannot tell
whether the gate was read; it says so on stderr and lets the reply through.
Failing open is this hook's written choice: sending back a correct
diagnosis is the cost it most avoids.

Stop only; it never blocks a tool call. Judgment stays with the model; this
file matches shapes.
"""
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
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

HIT = "hit"
CLEAN = "clean"
UNCHECKED = "unchecked"

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

UNCHECKED_MESSAGE = (
    "gate-blame-needs-evidence: unchecked, letting this reply through: it blames {gates} but {why}, so "
    "whether the gate's source was read is unknown."
)


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
    """Every gate the text names, in order, one entry per name."""
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
    """`rm ... hooks/<name>/...` anywhere in the reply, code blocks included."""
    return [
        {"phrase": match.group(0).strip(), "gate": _gate(match.group(1), "hook")}
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
    """The gate that last refused a tool call (`hook error: [.../hooks/<name>/...]`);
    only when none did, the Stop hook that last sent a reply back. A Stop
    hook's feedback on the previous reply is not what "it still fires" means
    while a tool gate is blocking, and a hook summary line refuses nothing."""
    for pattern in (TOOL_REFUSAL_RE, STOP_FEEDBACK_RE):
        for data in reversed(lines):
            if data.get("type") != "user":
                continue
            matches = pattern.findall(json.dumps(data))
            if matches:
                return [_gate(matches[-1], "hook")]
    return []


def successful_reads(lines: list[dict]) -> list[str]:
    """Paths and read commands from tool calls whose result was not an error,
    plus the user's own `!` read commands."""
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
    """The reply cites a line of this gate's source (`detect.py:159`)."""
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
    gates = gates_in(message, known_gate_names(hooks_dir))
    gates.extend(delete["gate"] for delete in delete_requests(message))
    if not gates:
        gates = latest_refusal_gate(lines)
    unique: dict[str, dict] = {}
    for gate in gates:
        unique.setdefault(gate["name"], gate)
    reads = successful_reads(lines)
    return [
        gate for gate in unique.values()
        if not any(gate["read_re"].search(read) for read in reads)
        and not cites_gate(gate, message, hooks_dir)
    ]


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


def enqueue_judge(payload: dict) -> str | None:
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return None
    transcript = payload.get("agent_transcript_path") or payload.get("transcript_path") or payload.get("transcriptPath")
    if not isinstance(transcript, str) or not os.path.isfile(transcript):
        if transcript:
            raise OSError(f"transcript could not be read: {transcript}")
        return None
    with open(transcript, encoding="utf-8") as handle:
        lines = parse_lines(handle)
    unread = unread_gates(message, lines)
    if not unread:
        return None
    dictionary = _phrases().load("gate-blame-needs-evidence")
    job = _phrases().job(dictionary, transcript, message)
    names = ", ".join(f"`{gate['name']}`" for gate in unread)
    where = " and ".join(_where(gate, HOOKS_DIR) for gate in unread)
    job["on_hit"] = f"{dictionary['on_hit']} Gates: {names}. Read {where}."
    job["id"] = uuid.uuid4().hex
    return _judge().enqueue(job)


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except OSError as exc:
        sys.stderr.write(UNCHECKED_MESSAGE.format(
            gates="a gate", why=f"the transcript could not be read ({exc!r})"
        ) + "\n")
    except Exception:
        return
