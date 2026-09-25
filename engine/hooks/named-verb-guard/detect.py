"""named-verb-guard: when the user asked for a verb, the reply must show it happened.

Whether the user asked (repro/test/prove, run/show, delete/revert, stop, or a
repeated demand for proof) is judged by the background model from one phrase
dictionary per request type. Whether the reply already carries that type's
evidence is shape only and stays here: a closed fenced block, a `path:line`,
a URL, a markdown table row, a delete/revert command, or no mutating tool call
after the message. A request whose evidence is already present is never sent
to the judge.

Target proof is the one request type that reads tool results. When the turn
changed something, the reply's proof must come from a live check (not a file
read) made before the first change, and from a check after the last change that
is not a read-back of a file the turn wrote, with a pasted output line found in
that check's result. A turn with no change never sends it.

Never blocks. A hit arrives on a later turn through the llm-judge inbox.
Fail-open on any read/parse error; `stop_hook_active` skips.
"""
from __future__ import annotations

import functools
import importlib.util
import json
import os
import re
import sys
import uuid

HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "_sdk")
LLM_JUDGE_DIR = os.path.join(os.path.dirname(HOOKS_DIR), "llm-judge")
LLM_JUDGE_PATH = os.path.join(LLM_JUDGE_DIR, "judge.py")
PHRASES_PATH = os.path.join(LLM_JUDGE_DIR, "phrases.py")

sys.path.insert(0, SDK_DIR)
sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_markers"))

from finding import Finding  # noqa: E402
import markers  # noqa: E402

HOOK_NAME = "named-verb-guard"
PROOF_DEMAND = "named-verb-guard-proof-demand"
PROVE_REQUEST = "named-verb-guard-prove-request"
SHOW_REQUEST = "named-verb-guard-show-request"
DELETE_REQUEST = "named-verb-guard-delete-request"
STOP_REQUEST = "named-verb-guard-stop-request"
TARGET_PROOF_REQUEST = "named-verb-guard-target-proof-request"
CHECKERS = (PROOF_DEMAND, PROVE_REQUEST, SHOW_REQUEST, DELETE_REQUEST, STOP_REQUEST, TARGET_PROOF_REQUEST)

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
FILE_LINE_RE = re.compile(r"\b[\w./-]+\.[A-Za-z]{1,5}:\d+\b")
URL_RE = re.compile(r"https?://\S+")
TABLE_ROW_RE = re.compile(r"(?m)^\s*\|.*\|\s*$")
DESTRUCTIVE_CMD_RE = re.compile(
    r"(?:^|\s|\||&&|;)(?:rm|unlink|trash|git\s+(?:rm|revert|reset|restore|checkout|clean|stash))\b",
    re.IGNORECASE,
)
MUTATING_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "StrReplace"}
FILE_WRITE_TOOLS = MUTATING_TOOLS - {"Bash"}
FILE_READ_TOOLS = {"Read", "Grep", "Glob", "LS", "NotebookRead"}
BASH_WRITE_RE = re.compile(
    r"(?:^|\s|\||&&|;)(?:mv|cp|tee|touch|mkdir|chmod|chown|ln|kill|pkill|killall|sed\s+-i|perl\s+-pi"
    r"|git\s+(?:commit|push|merge|rebase|apply|am|cherry-pick|add|tag))\b"
    r"|(?<![0-9&>])>{1,2}\s*(?!&|/dev/null)[\w./~$\"']",
)
BASH_FILE_READ_RE = re.compile(
    r"^\s*(?:cat|head|tail|less|more|sed\s+-n|grep|rg|jq|diff|git\s+(?:diff|show|log|blame))\b"
)
EVIDENCE_LINE_MIN = 4
MESSAGE_SEPARATOR = "\n\n--- next user message ---\n\n"

SYSTEM_INJECTED_PREFIXES = (
    "<command-",
    "<task-notification",
    "<local-command",
    "<system",
    "<user-prompt-submit-hook",
    "This session is being continued",
    "Base directory for this skill",
    "[IMPORTANT: User invoked",
    "Stop hook feedback:",
    "PreToolUse hook",
    "PostToolUse hook",
    "UserPromptSubmit hook",
)


def _text_of(data: dict) -> str | None:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return None


def _is_human_line(data: dict) -> str | None:
    if not isinstance(data, dict) or data.get("type") != "user":
        return None
    text = _text_of(data)
    if not text or not text.strip():
        return None
    if text.lstrip().startswith(SYSTEM_INJECTED_PREFIXES):
        return None
    if "[Request interrupted by user" in text:
        return None
    return text


def _result_text(block: dict) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    return ""


def read_transcript(transcript_path: str) -> tuple[list[str], list[dict]]:
    """(all human messages in order, tool_use blocks after the last one).

    Each tool_use block whose tool_result is in the transcript gets that
    result's text under the key "result".
    """
    humans: list[str] = []
    tool_uses: list[dict] = []
    by_id: dict[str, dict] = {}
    with open(transcript_path, encoding="utf-8") as handle:
        for line in handle:
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = _is_human_line(data)
            if text is not None:
                humans.append(text)
                tool_uses = []
                by_id = {}
                continue
            if not isinstance(data, dict) or data.get("type") not in ("assistant", "user"):
                continue
            message = data.get("message")
            content = message.get("content") if isinstance(message, dict) else None
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if data["type"] == "assistant" and block.get("type") == "tool_use":
                    tool_uses.append(block)
                    if isinstance(block.get("id"), str):
                        by_id[block["id"]] = block
                elif data["type"] == "user" and block.get("type") == "tool_result":
                    target = by_id.get(block.get("tool_use_id"))
                    if target is not None:
                        target["result"] = _result_text(block)
    return humans, tool_uses


def has_output_evidence(message: str) -> bool:
    return bool(FENCE_RE.search(message) or FILE_LINE_RE.search(message))


def has_link_evidence(message: str) -> bool:
    return bool(URL_RE.search(message) or TABLE_ROW_RE.search(message))


def bash_commands(tool_uses: list[dict]) -> list[str]:
    out = []
    for block in tool_uses:
        if block.get("name") == "Bash":
            command = (block.get("input") or {}).get("command")
            if isinstance(command, str):
                out.append(command)
    return out


def has_destructive_evidence(message: str, tool_uses: list[dict]) -> bool:
    if any(DESTRUCTIVE_CMD_RE.search(c) for c in bash_commands(tool_uses)):
        return True
    return any(DESTRUCTIVE_CMD_RE.search(c) for c in re.findall(r"`([^`]+)`", message))


def mutating_calls(tool_uses: list[dict]) -> list[str]:
    return [b.get("name") for b in tool_uses if b.get("name") in MUTATING_TOOLS]


def _command(block: dict) -> str:
    command = (block.get("input") or {}).get("command") if block.get("name") == "Bash" else None
    return command if isinstance(command, str) else ""


def _changes_something(block: dict) -> bool:
    return block.get("name") in FILE_WRITE_TOOLS or bool(BASH_WRITE_RE.search(_command(block)))


def _reads_a_file(block: dict) -> bool:
    return block.get("name") in FILE_READ_TOOLS or bool(BASH_FILE_READ_RE.search(_command(block)))


def _written_paths(tool_uses: list[dict]) -> set[str]:
    paths = set()
    for block in tool_uses:
        path = (block.get("input") or {}).get("file_path") or (block.get("input") or {}).get("notebook_path")
        if block.get("name") in FILE_WRITE_TOOLS and isinstance(path, str) and path:
            paths.add(path)
    return paths


def _reads_back(block: dict, written: set[str]) -> bool:
    if not _reads_a_file(block):
        return False
    tool_input = block.get("input") or {}
    haystack = " ".join(str(tool_input.get(k, "")) for k in ("file_path", "notebook_path", "path", "command"))
    return any(path in haystack or os.path.basename(path) in haystack for path in written)


def _pasted_output_lines(message: str) -> list[str]:
    lines = []
    for block in FENCE_RE.findall(message):
        for line in block.strip("`").splitlines()[1:]:
            line = line.strip()
            if len(line) >= EVIDENCE_LINE_MIN and not line.startswith("$ "):
                lines.append(line)
    return lines


def target_proof_gaps(message: str, tool_uses: list[dict]) -> list[str]:
    """What the reply lacks as proof of the exact live target and outcome; empty when nothing changed."""
    changes = [i for i, block in enumerate(tool_uses) if _changes_something(block)]
    if not changes:
        return []
    first, last = changes[0], changes[-1]
    gaps = []
    live_before = [b for b in tool_uses[:first] if not _reads_a_file(b) and b.get("result")]
    if not live_before:
        reads_before = any(_reads_a_file(b) for b in tool_uses[:first])
        gaps.append(
            "the target came only from file reads or earlier output, not a live query this turn"
            if reads_before
            else "the change ran before any check named the target or showed the bad case"
        )
    written = _written_paths(tool_uses)
    after = [
        b for b in tool_uses[last + 1:]
        if not _changes_something(b) and not _reads_back(b, written) and b.get("result")
    ]
    pasted = _pasted_output_lines(message)
    if not any(line in b["result"] for b in after for line in pasted):
        gaps.append(
            "no pasted output comes from a check of the real surface after the last change"
            " (a read-back of the file this turn wrote does not count)"
        )
    return gaps


def pending_requests(message: str, humans: list[str], tool_uses: list[dict]) -> list[tuple[str, str]]:
    """(checker, text to judge) for each request type whose evidence the reply lacks."""
    if not humans or not humans[-1].strip():
        return []
    if markers.well_formed_tags(message) or message.rstrip().endswith("?"):
        return []
    last = humans[-1]
    output_ok = has_output_evidence(message)
    link_ok = output_ok or has_link_evidence(message)
    pending: list[tuple[str, str]] = []
    if not link_ok and len(humans) >= 2:
        pending.append((PROOF_DEMAND, MESSAGE_SEPARATOR.join(humans)))
    if not output_ok:
        pending.append((PROVE_REQUEST, last))
    if not link_ok:
        pending.append((SHOW_REQUEST, last))
    if not has_destructive_evidence(message, tool_uses):
        pending.append((DELETE_REQUEST, last))
    if mutating_calls(tool_uses):
        pending.append((STOP_REQUEST, last))
    if target_proof_gaps(message, tool_uses):
        pending.append((TARGET_PROOF_REQUEST, last))
    return pending


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


def enqueue_judge(payload: dict) -> list[str]:
    """Enqueue one judge job asking every request type whose evidence is missing; return its id."""
    if not isinstance(payload, dict) or payload.get("stop_hook_active"):
        return []
    if _judge().is_subagent_payload(payload):
        return []
    message = payload.get("last_assistant_message") or ""
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not message or not transcript_path or not os.path.isfile(transcript_path):
        return []
    humans, tool_uses = read_transcript(transcript_path)
    pending = pending_requests(message, humans, tool_uses)
    if not pending:
        return []
    asks = []
    for checker, text in pending:
        dictionary = _phrases().load(checker)
        if checker == TARGET_PROOF_REQUEST:
            gaps = "; ".join(target_proof_gaps(message, tool_uses))
            dictionary = {**dictionary, "on_hit": dictionary["on_hit"] + " Missing: " + gaps + "."}
        asks.append((dictionary, text))
    job = _phrases().combined_job("named-verb-guard", transcript_path, asks)
    job["id"] = uuid.uuid4().hex
    return [_judge().enqueue(job)]


def try_enqueue_judge(payload: dict) -> None:
    try:
        enqueue_judge(payload)
    except Exception as exc:
        print(f"catstack-hook-error named-verb-guard: {type(exc).__name__}: {exc}", file=sys.stderr)
        return


def detect(event: dict[str, object]) -> list[Finding]:
    """Hand the reply to the background judge; its verdict arrives on the next turn."""
    try_enqueue_judge(event)
    return []


