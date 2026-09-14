"""handoff-needs-smoke-test: a script handed to the user is a claim it runs.

A reply that ends with `! bash <path>` is asking the user to execute
something on their own machine. If this session never executed that path,
nobody has: a syntax check of the wrapper does not run the payload, and a
script assembled from nested quoting can collapse into a single line that
parses locally and breaks remotely.

The escape is the honest one: say the run cannot happen here and why. An
interactive browser login is a real reason; not having tried is not.
"""
from __future__ import annotations

import json
import os
import re

HANDOFF_RES = [
    re.compile(r"(?m)^\s*!\s*(?:bash|sh|zsh|python3?|node)\s+(\S+)"),
    re.compile(r"`\s*!\s*(?:bash|sh|zsh|python3?|node)\s+(\S+)\s*`"),
]
SCRIPT_SUFFIXES = (".sh", ".bash", ".zsh", ".py", ".mjs", ".js")

CANNOT_RUN_RE = re.compile(
    r"\b(?:cannot|can'?t|could not|couldn'?t|unable to|no way to)\b[^.\n]{0,80}"
    r"\b(?:run|execute|test|try|verify|reach|reproduce)\b"
    r"|\brequires? (?:your|a human|physical|interactive|browser)\b"
    r"|\bonly you can\b|\bneeds your browser\b|\binteractive (?:login|consent|approval)\b",
    re.IGNORECASE,
)

RUN_PREFIX_RE = re.compile(
    r"(?:^|[\s;|&(])(?:bash|sh|zsh|python3?|node|source|\.)\s+(\S+)"
)
WRITE_ONLY_RE = re.compile(
    r"(?:^|[\s;|&(])(?:cat|tee|chmod|cp|mv|scp|rsync|ls|stat|rm|touch|head|tail|wc|grep|rg)\b"
)

VERIFY_TOOLS = {"Bash"}

MESSAGE = (
    "handoff-needs-smoke-test: this reply hands over {targets} with `!`, and this "
    "session never executed {that}. A local syntax check does not run a remote "
    "payload, and nested quoting can collapse a multi-line script into one line "
    "that parses here and breaks there. Run it end to end, or run the same "
    "transport with a harmless payload, before handing it over. If the run "
    "genuinely cannot happen here -- an interactive browser login, a credential "
    "only the user holds -- say so in the reply and name the blocker."
)


def handoff_paths(message):
    """Script paths the reply asks the user to run."""
    found = []
    for pattern in HANDOFF_RES:
        for match in pattern.finditer(message or ""):
            path = match.group(1).strip("`'\"")
            if path.endswith(SCRIPT_SUFFIXES) and path not in found:
                found.append(path)
    return found


def names_a_blocker(message):
    return bool(CANNOT_RUN_RE.search(message or ""))


def _executed_paths(lines):
    """Paths this session actually ran through an interpreter."""
    ran = set()
    for data in lines:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") not in VERIFY_TOOLS:
                continue
            command = (block.get("input") or {}).get("command") or ""
            for segment in re.split(r"\|\||&&|[|;\n]", command):
                segment = segment.strip()
                if not segment or WRITE_ONLY_RE.match(segment):
                    continue
                match = RUN_PREFIX_RE.search(segment)
                if match:
                    ran.add(os.path.basename(match.group(1).strip("`'\"")))
    return ran


def parse_lines(raw_lines):
    parsed = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    return parsed


def decide_from_lines(message, lines):
    targets = handoff_paths(message)
    if not targets or names_a_blocker(message):
        return None
    ran = _executed_paths(lines)
    unrun = [t for t in targets if os.path.basename(t) not in ran]
    if not unrun:
        return None
    names = ", ".join(f"`{os.path.basename(t)}`" for t in unrun)
    return MESSAGE.format(targets=names, that="it" if len(unrun) == 1 else "them")


def decide(payload):
    """Blocking feedback for the Stop event, or None to let the turn finish."""
    if payload.get("stop_hook_active"):
        return None
    message = payload.get("last_assistant_message") or ""
    if not handoff_paths(message) or names_a_blocker(message):
        return None
    path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            lines = parse_lines(handle)
    except OSError:
        return None
    return decide_from_lines(message, lines)
