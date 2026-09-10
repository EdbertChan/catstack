"""gate-blame-needs-evidence: a claim about a gate needs a read of the gate.

A hook that refuses a tool call leaves its command and its refusal text in
the transcript (`PreToolUse:Read hook error: [python3 $HOME/.claude/hooks/
scope-lock/claude_pretool_scope.py]: Second scope correction ...`). Before
a reply may

  1. say that gate is broken, still firing, or clears a certain way (or
     reverse such a claim),
  2. tell the user to type fewer items than a refusal names as required, or
  3. ask the user to disable the hook or delete its files,

the session must have read the file that holds the gate's refusal text.

Read state for a gate has three outcomes, and only `read` silences a check:
  read     a tool call naming a file under the gate's hooks/<name>/ dir
           succeeded, and its output shows the refusal text or the file it
           named is the one on disk that holds it;
  refused  such a call was made and a gate refused it -- a refused read is
           not a read;
  none     no such call.

Quoting the refusal text is not a read: a real reply quoted it and then
claimed the gate was broken. An unreadable transcript is `unchecked`, not
clean; the Stop entrypoint says so on stderr and lets the reply through
(fail open, written down in README.md).
"""
from __future__ import annotations

import json
import os
import re

READ, REFUSED, NONE = "read", "refused", "none"
CLEAN, FEEDBACK, UNCHECKED = "clean", "feedback", "unchecked"

TOOL_REFUSAL_RE = re.compile(r"^\s*(\w+):(\w+) hook error: \[([^\]\n]*)\]:\s*(.*)\Z", re.DOTALL)
STOP_FEEDBACK_RE = re.compile(r"^\s*Stop hook feedback:\s*\n?\[([^\]\n]*)\]:\s*(.*)\Z", re.DOTALL)
HOOK_DIR_RE = re.compile(r"hooks/([A-Za-z0-9_.-]+)/")
HOOK_PATH_TOKEN_RE = re.compile(r"[^\s\"'=]*hooks/[A-Za-z0-9_.-]+/[^\s\"']*")
MIN_BARE_NAME_LEN = 4
WINDOW_WORDS = 6
MAX_SCAN_BYTES = 512 * 1024
DOC_SUFFIXES = (".md", ".txt", ".rst")

FENCE_RE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)
GATE_SUBJECT = (
    r"(?:\bit's|\bit|\bits(?:\s+\w+){1,3}|\bthey|\bthe (?:hook|gate|lock|guard|detector|check)|"
    r"\b(?:this|that|your) (?:hook|gate)|\btools?|\bevery (?:tool|call)|\b[\w-]+ (?:hook|gate)|`[^`\n]+` (?:hook|gate))"
)
CLAIM_PATTERNS = (
    ("says it is broken", re.compile(
        GATE_SUBJECT + r"(?:\s+(?:is|are|was|looks|seems))?\s+(?:\w+\s+)?(?:broken|buggy|misfiring)\b|"
        r"\bfix (?:its|their) bugs?\b|\bunfixable\b", re.IGNORECASE)),
    ("says it is still firing", re.compile(
        GATE_SUBJECT + r"(?:\s+(?:is|are))?\s+\**still\**\s+(?:fir\w*|block\w*|trip\w*|stopp\w*|refus\w*|active)\b|"
        r"\bkeeps? (?:fir|block|trip|refus)\w*|\b\d+ identical blocks?\b", re.IGNORECASE)),
    ("says how it clears", re.compile(
        r"\bclear(?:s|ed|ing)? (?:it|this|that|the (?:gate|hook|lock|block))\b|\bclear(?:ing)? condition\b|"
        r"\bunblock(?:s|ed|ing)? (?:it|tools|the tools|every tool|me|you)\b|"
        r"\b(?:it|the hook|the gate) only (?:allows?|lets?|passes)\b|\bneeds? a (?:session )?restart\b|"
        r"\breset\w*\b[^.\n]{0,30}\b(?:hook|gate|lock|state)\b", re.IGNORECASE)),
    ("reverses an earlier claim", re.compile(
        r"\bit'?s not the \w+\b|\bI was wrong\b|\bscratch that\b|\bI take (?:that|it) back\b", re.IGNORECASE)),
)
DISABLE_PATTERNS = (
    re.compile(r"\b(?:switch|turn|shut)\s+(?:it|this|that|them|the \w+|`?[\w-]+`?)\s+off\b", re.IGNORECASE),
    re.compile(r"\b(?:disabl|uninstall)(?:e|es|ed|ing|s)?\b(?!-)|\bcomment (?:it |this |that )?out\b", re.IGNORECASE),
    re.compile(r"\bremove (?:it|them|the (?:hook|gate|entry)|this hook|that hook|its entry)\b", re.IGNORECASE),
    re.compile(r"\btype\s+`?/hooks\b", re.IGNORECASE),
    re.compile(r"\b(?:rm|unlink|trash|shred)\s[^\n`]*hooks/[A-Za-z0-9_.-]+/"),
    re.compile(r"\bdelete (?:its|the hook'?s?|that hook'?s?) (?:\w+ )?files?\b", re.IGNORECASE),
)

REQUIRED_SENTENCE_RE = re.compile(r"\b(?:must|required?|requires|needs?|until|both)\b", re.IGNORECASE)
ITEM = r"(?:`[^`\n]+`|(?<![\w/`])/[a-z][\w-]*)"
ITEM_RE = re.compile(ITEM)
TYPE_INSTRUCTION_RE = re.compile(
    r"\b(?:type|invoke|enter)\s+(?:both\s+|just\s+|only\s+)?"
    r"(" + ITEM + r"(?:\s*(?:,\s*and|,\s*then|,|and|&|\+|then)\s*(?:both\s+)?" + ITEM + r")*)",
    re.IGNORECASE,
)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
QUOTES = "\"'“‘"

FEEDBACK_HEAD = "gate-blame-needs-evidence: this reply makes a claim about a gate it has not read."
FEEDBACK_TAIL = (
    "Read the file that holds the gate's refusal text and diagnose from what it says. If the "
    "gate blocks that read too, tell the user it is blocked and quote the refusal, with no "
    "claimed cause, no fewer steps than it names, and no ask to disable it or delete its files. "
    "A refused read is not a read, and quoting the refusal is not a read either."
)


def _norm(text: str) -> str:
    return " ".join((text or "").split())


def _windows(text: str) -> set[str]:
    words = _norm(text).split(" ")
    if len(words) <= WINDOW_WORDS:
        return {" ".join(words)} if words and words[0] else set()
    return {" ".join(words[i:i + WINDOW_WORDS]) for i in range(len(words) - WINDOW_WORDS + 1)}


def _shows(text: str, windows: set[str]) -> bool:
    flat = _norm(text)
    return bool(flat) and any(window in flat for window in windows)


def _block_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
            if not isinstance(b, dict) or b.get("type") in (None, "text")
        )
    return ""


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


def _content_blocks(data: dict) -> list:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return content if isinstance(content, list) else []


def _user_text(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in _content_blocks(data) if isinstance(b, dict) and b.get("type") == "text"
    )


def _gate_name(command: str) -> str:
    match = HOOK_DIR_RE.search(command or "")
    if match:
        return match.group(1)
    script = next((t for t in reversed((command or "").split()) if "/" in t), "")
    return os.path.basename(os.path.dirname(script))


def _gate_dir(command: str) -> str:
    token = HOOK_PATH_TOKEN_RE.search(command or "")
    if not token:
        return ""
    path = os.path.expanduser(os.path.expandvars(token.group(0)))
    return path if os.path.isdir(path) else os.path.dirname(path)


def scan_events(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Refusals (who refused, with what text) and tool calls (input, result)."""
    refusals: list[dict] = []
    calls: dict[str, dict] = {}
    order: list[str] = []
    for index, data in enumerate(lines):
        attachment = data.get("attachment")
        if data.get("type") == "attachment" and isinstance(attachment, dict):
            if attachment.get("type") == "hook_additional_context":
                text = _block_text(attachment.get("content"))
                if text.strip():
                    refusals.append({"command": "", "text": text, "index": index})
            continue
        if data.get("type") == "user":
            match = STOP_FEEDBACK_RE.match(_user_text(data))
            if match:
                refusals.append({"command": match.group(1), "text": match.group(2), "index": index})
        for block in _content_blocks(data):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and data.get("type") == "assistant":
                call_id = block.get("id") or f"line{index}"
                calls[call_id] = {
                    "name": block.get("name") or "",
                    "input": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    "result": None, "is_error": False, "refused": False, "index": index,
                }
                order.append(call_id)
            elif block.get("type") == "tool_result":
                call = calls.get(block.get("tool_use_id"))
                output = _block_text(block.get("content"))
                match = TOOL_REFUSAL_RE.match(output)
                if match:
                    refusals.append({"command": match.group(3), "text": match.group(4), "index": index})
                if call is not None:
                    call["result"] = output
                    call["is_error"] = bool(block.get("is_error"))
                    call["refused"] = call["is_error"] and bool(match)
    return refusals, [calls[c] for c in order]


def _refusal_files(gate_dir: str, windows: set[str]) -> set[str] | None:
    """Basenames in the gate's dir that hold the refusal text; None when the
    dir could not be read (the path proof is then unavailable, not clean)."""
    try:
        entries = list(os.scandir(gate_dir))
    except OSError:
        return None
    found: set[str] = set()
    for entry in entries:
        try:
            if not entry.is_file() or entry.name.endswith(DOC_SUFFIXES) or entry.stat().st_size > MAX_SCAN_BYTES:
                continue
            with open(entry.path, encoding="utf-8", errors="replace") as handle:
                if _shows(handle.read(), windows):
                    found.add(entry.name)
        except OSError:
            continue
    return found


def build_gates(refusals: list[dict]) -> dict[str, dict]:
    """Gates keyed by hook name; a refusal with no command (UserPromptSubmit
    context) joins the named gate whose text it repeats, else stands alone."""
    gates: dict[str, dict] = {}
    for refusal in refusals:
        if not refusal["command"]:
            continue
        name = _gate_name(refusal["command"])
        if not name:
            continue
        gate = gates.setdefault(name, {"name": name, "texts": [], "windows": set(), "dirs": set()})
        if _norm(refusal["text"]) not in (_norm(t) for t in gate["texts"]):
            gate["texts"].append(refusal["text"])
            gate["windows"] |= _windows(refusal["text"])
        gate_dir = _gate_dir(refusal["command"])
        if gate_dir:
            gate["dirs"].add(gate_dir)
    for refusal in refusals:
        if refusal["command"]:
            continue
        flat = _norm(refusal["text"])
        owner = next((g for g in gates.values() if any(_norm(t) == flat for t in g["texts"])), None)
        if owner is None:
            gates.setdefault(f"text:{flat[:80]}", {
                "name": "", "texts": [refusal["text"]], "windows": _windows(refusal["text"]), "dirs": set(),
            })
    for gate in gates.values():
        gate["files"] = set()
        for gate_dir in gate["dirs"]:
            gate["files"] |= _refusal_files(gate_dir, gate["windows"]) or set()
    return gates


def _targets(gate: dict, call: dict) -> bool:
    if gate["name"]:
        return bool(re.search(r"hooks/" + re.escape(gate["name"]) + r"(?:/|(?![\w.-]))", call["input"]))
    return ".jsonl" not in call["input"] and _shows(call["result"] or "", gate["windows"])


def _is_read(gate: dict, call: dict) -> bool:
    if not gate["texts"]:
        return True
    if _shows(call["result"] or "", gate["windows"]):
        return True
    return any(
        re.search(r"hooks/" + re.escape(gate["name"]) + r"/" + re.escape(f) + r"(?![\w.-])", call["input"])
        for f in gate["files"]
    )


def read_state(gate: dict, calls: list[dict]) -> tuple[str, int]:
    """(read | refused | none, number of refused attempts) for one gate."""
    refused = 0
    for call in calls:
        if not _targets(gate, call):
            continue
        if call["is_error"]:
            refused += 1 if call["refused"] else 0
            continue
        if call["result"] is not None and _is_read(gate, call):
            return READ, refused
    return (REFUSED if refused else NONE), refused


def named_gates(reply: str, gates: dict[str, dict]) -> list[dict]:
    """Hook gates the reply names: a hooks/<name>/ path, or the bare name of
    a gate that refused this session."""
    out: dict[str, dict] = {}
    for name in HOOK_DIR_RE.findall(reply or ""):
        out.setdefault(name, gates.get(name) or {
            "name": name, "texts": [], "windows": set(), "dirs": set(), "files": set(),
        })
    for name, gate in gates.items():
        if not gate["name"] or name in out or len(name) < MIN_BARE_NAME_LEN:
            continue
        if re.search(r"(?<![\w/.-])" + re.escape(name) + r"(?![\w-])", reply or ""):
            out[name] = gate
    return list(out.values())


def claim_kinds(reply: str) -> list[str]:
    prose = FENCE_RE.sub(" ", reply or "")
    return [label for label, pattern in CLAIM_PATTERNS if pattern.search(prose)]


def asks_disable(reply: str) -> bool:
    return any(pattern.search(reply or "") for pattern in DISABLE_PATTERNS)


def _item(token: str) -> str:
    return token.strip("`").strip().lstrip("/").lower()


def required_items(text: str) -> set[str]:
    """Items a refusal names as required: backticked or /slash tokens in a
    must / required / needs / until / both sentence."""
    items: set[str] = set()
    for sentence in re.split(r"(?<=[.;!?])\s+", text or ""):
        if REQUIRED_SENTENCE_RE.search(sentence):
            items |= {_item(t) for t in ITEM_RE.findall(sentence)}
    items.discard("")
    return items


def type_instructions(reply: str) -> list[set[str]]:
    """Items the reply tells the user to type, one set per sentence. Steps
    listed in one sentence count together; an instruction inside quotes is
    a quotation, not an ask."""
    out: list[set[str]] = []
    for sentence in SENTENCE_SPLIT_RE.split(reply or ""):
        told: set[str] = set()
        for match in TYPE_INSTRUCTION_RE.finditer(sentence):
            if match.start() and sentence[match.start() - 1] in QUOTES:
                continue
            told |= {_item(t) for t in ITEM_RE.findall(match.group(1))}
        if told:
            out.append(told)
    return out


def fewer_than_required(reply: str, gates: dict[str, dict]) -> list[tuple[dict, set[str], set[str]]]:
    hits = []
    instructions = type_instructions(reply)
    for gate in gates.values():
        for text in gate["texts"]:
            required = required_items(text)
            if len(required) < 2:
                continue
            for told in instructions:
                if told & required and required - told:
                    hits.append((gate, told & required, required))
                    break
            else:
                continue
            break
    return hits


def _label(gate: dict) -> str:
    if gate["name"]:
        return f"`{gate['name']}`"
    words = _norm(gate["texts"][0]).split(" ")[:8]
    return "the gate that said \"" + " ".join(words) + " ...\""


def _state_text(state: str, refused: int) -> str:
    if state == REFUSED:
        return f"all {refused} attempt(s) to read it were refused, and a refused read is not a read"
    return "no read of it was attempted this session"


def _where(gate: dict) -> str:
    if gate["files"]:
        return ", ".join(f"hooks/{gate['name']}/{f}" for f in sorted(gate["files"]))
    if gate["name"]:
        return f"the file under hooks/{gate['name']}/ that holds its refusal text"
    return "the file that holds that refusal text"


def evaluate(reply: str, lines: list[dict]) -> list[str]:
    """One line per failed check; empty when every check passes."""
    refusals, calls = scan_events(lines)
    gates = build_gates(refusals)
    findings: list[str] = []
    claims = claim_kinds(reply)
    disable = asks_disable(reply)
    if claims or disable:
        for gate in named_gates(reply, gates):
            state, refused = read_state(gate, calls)
            if state == READ:
                continue
            what = list(claims) + (["asks the user to disable it or delete its files"] if disable else [])
            findings.append(
                f"- About {_label(gate)}, it {', '.join(what)}; but {_state_text(state, refused)}. "
                f"Refusal text lives in: {_where(gate)}."
            )
    for gate, told, required in fewer_than_required(reply, gates):
        state, refused = read_state(gate, calls)
        if state == READ:
            continue
        findings.append(
            f"- It tells the user to type {', '.join(sorted(told))} but {_label(gate)} names "
            f"{', '.join(sorted(required))} as required, and {_state_text(state, refused)}."
        )
    return findings


def decide_stop_from_lines(reply: str, lines: list[dict]) -> str | None:
    findings = evaluate(reply, lines)
    if not findings:
        return None
    return "\n".join([FEEDBACK_HEAD, *findings, FEEDBACK_TAIL])


def decide_stop(payload: dict) -> tuple[str, str]:
    """(clean | feedback | unchecked, text) for the Stop event."""
    if payload.get("stop_hook_active"):
        return CLEAN, ""
    reply = payload.get("last_assistant_message") or ""
    if not (claim_kinds(reply) or asks_disable(reply) or type_instructions(reply)):
        return CLEAN, ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            lines = parse_lines(handle)
    except (OSError, TypeError, ValueError) as exc:
        return UNCHECKED, (
            f"gate-blame-needs-evidence: transcript unreadable ({exc!r}); gate read state is "
            "unchecked, not clean. Letting this reply through (fail open)."
        )
    message = decide_stop_from_lines(reply, lines)
    return (FEEDBACK, message) if message else (CLEAN, "")
