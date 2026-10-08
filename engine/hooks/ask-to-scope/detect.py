"""Block a committing or user-visible tool call once per user message when the
message leaves out which target it means.

Typed inputs decide everything they can: which tool is running, whether it can
only read, whether the target already appears in the user's message, and
whether the assistant already asked a question this turn. Whether the message
is ambiguous is meaning, so the shared llm-judge answers it from the
`ambiguous-ask` phrase dictionary on a private verdict channel, and the hook
waits for that one verdict so a block lands before the tool runs. Regexes only
extract URLs and paths to show as candidates; none of them decides anything.
"""
from __future__ import annotations

import os
import posixpath
import re
import shlex
import sys
import time

HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
HOOKS_DIR = os.path.dirname(HOOK_DIR)
sys.path.insert(0, os.path.join(HOOKS_DIR, "_sdk"))

import judge_channel  # noqa: E402
from events import is_human_text  # noqa: E402
from finding import Finding  # noqa: E402
from judge_channel import CLEAN, HIT, UNCHECKED  # noqa: E402
from transcript_rows import content_text, is_user_prompt, message, read_lines, tool_uses  # noqa: E402

HOOK = "ask-to-scope"
RULE_ID = "ask-to-scope.ambiguous-ask"
CHECKER = "ambiguous-ask"
WAIT_ENV = "ASK_TO_SCOPE_WAIT_SECONDS"
STATE_ENV = "ASK_TO_SCOPE_STATE_DIR"
DEFAULT_WAIT_SECONDS = 40.0
CONFIG = judge_channel.ChannelConfig(
    hook=HOOK,
    id_prefix="ats",
    state_env=STATE_ENV,
    cache_dirname="catstack-ask-to-scope",
)

FILE_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
AGENT_TOOLS = frozenset({"Agent", "Task"})
SHELL_TOOLS = frozenset({"Bash"})
BROWSER_OPEN_ACTIONS = frozenset({"navigate", "browser_navigate", "open_url", "tabs_create", "tabs_create_mcp"})
ASKING_TOOLS = frozenset({"AskUserQuestion"})
PATH_INPUT_KEYS = ("file_path", "notebook_path")

READ_ONLY_HEADS = frozenset({
    "basename", "cat", "cd", "date", "diff", "dirname", "echo", "egrep", "fgrep", "file", "find", "grep",
    "head", "jq", "ls", "printf", "pwd", "realpath", "rg", "sed", "stat", "tail", "test", "true", "type",
    "wc", "which",
})
READ_ONLY_GIT = frozenset({"blame", "describe", "diff", "grep", "log", "ls-files", "ls-remote", "rev-parse", "shortlog", "show", "status"})
STAGE_BREAKS = frozenset({"|", "||", "&&", ";", "&"})
QUIET_REDIRECT_TARGETS = {">": "/dev/null", ">>": "/dev/null"}
FIND_WRITERS = frozenset({"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprint0", "-fprintf", "-fls"})

URL_RE = re.compile(r"https?://[^\s'\"`<>)\]]+")
ABS_PATH_RE = re.compile(r"(?<![\w/:.@-])(?:~|\.\.?)?(?:/[\w@+.-]+){2,}")
REL_PATH_RE = re.compile(r"(?<![\w/:.@-])(?:[\w@+-][\w@+.-]*/)+[\w@+-][\w@+.-]*\.[A-Za-z]\w{0,7}\b")
TICKED_FILE_RE = re.compile(r"`([\w@+-][\w@+.-]*\.[A-Za-z]\w{0,7})`")
CI_REF_RE = re.compile(r"\b(?:job|pipeline)\s+#?\d{4,}\b", re.IGNORECASE)
PROMPT_SPLIT_RE = re.compile(r"""[\s`'"<>()\[\],;]+""")
FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
TRAILING_PUNCTUATION = ".,;:!?)]}'\""

MAX_CANDIDATES = 12
CANDIDATE_TURNS = 2
JUDGE_PROMPT_CHARS = 1500

BLOCK_MESSAGE = (
    "ask-to-scope: the user's message does not say which target they mean, and you were about to {action}. "
    "Candidates from the last {turns} turns:\n{candidates}\n"
    "Put one scoping question to the user now, for example an AskUserQuestion whose options are the candidates "
    "above: ask which one they mean. Ask what they mean, not whether you may. If reading or searching can narrow "
    "it down, do that first and ask only about what is still open. This hook blocks once per user message; once "
    "you have asked, your tool calls proceed."
)
NO_CANDIDATES = "(none found in those turns; ask what they are pointing at)"
UNCHECKED_MESSAGE = (
    "ask-to-scope: UNCHECKED, allowing this {action}: {why}. Nothing decided whether the user's message left "
    "out which target they mean, so this call was not held for a scoping question."
)


def wait_seconds() -> float:
    return judge_channel.wait_seconds(WAIT_ENV, DEFAULT_WAIT_SECONDS)


def state_path(transcript: str) -> str:
    return judge_channel.state_path(CONFIG, transcript)


def browser_open_tool(name: str) -> bool:
    return name.startswith("mcp__") and name.rsplit("__", 1)[-1] in BROWSER_OPEN_ACTIONS


def shell_tokens(command: str) -> list[str] | None:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = False
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        print(f"catstack-hook-error {HOOK}: could not parse the shell command, treating it as not read-only: {exc}", file=sys.stderr)
        return None


def drop_quiet_redirects(tokens: list[str]) -> list[str] | None:
    kept: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in QUIET_REDIRECT_TARGETS and following == QUIET_REDIRECT_TARGETS[token]:
            index += 2
            continue
        if token == ">&" and following in {"1", "2"}:
            index += 2
            continue
        kept.append(token)
        index += 1
    return kept


def stage_is_read_only(stage: list[str]) -> bool:
    if not stage:
        return False
    head = posixpath.basename(stage[0])
    if head == "git":
        rest = stage[1:]
        while rest and rest[0] == "-C":
            rest = rest[2:]
        return bool(rest) and rest[0] in READ_ONLY_GIT
    if head not in READ_ONLY_HEADS:
        return False
    if head == "find":
        return not FIND_WRITERS.intersection(stage)
    if head == "sed":
        return not any(arg == "--in-place" or (arg.startswith("-") and not arg.startswith("--") and "i" in arg) for arg in stage[1:])
    return True


def is_read_only_command(command: str) -> bool:
    tokens = shell_tokens(command)
    if tokens is None:
        return False
    tokens = drop_quiet_redirects(tokens)
    stages: list[list[str]] = [[]]
    for token in tokens:
        if token in STAGE_BREAKS:
            stages.append([])
        elif any(char in token for char in "<>()`"):
            return False
        else:
            stages[-1].append(token)
    nonempty = [stage for stage in stages if stage]
    return bool(nonempty) and all(stage_is_read_only(stage) for stage in nonempty)


def gated_action(event: dict) -> str | None:
    """What the call does, in words for the block message, or None when the hook never gates it."""
    name = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    if name in FILE_TOOLS:
        return "edit a file"
    if name in AGENT_TOOLS:
        return "launch a subagent"
    if browser_open_tool(name):
        return "open a page"
    if name in SHELL_TOOLS and not is_read_only_command(str(tool_input.get("command") or "")):
        return "run a command"
    return None


def extract_references(text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for match in URL_RE.finditer(text):
        found.append((match.start(), match.group(0).rstrip(TRAILING_PUNCTUATION)))
    remaining = URL_RE.sub(lambda match: " " * len(match.group(0)), text)
    for pattern in (ABS_PATH_RE, REL_PATH_RE, CI_REF_RE):
        for match in pattern.finditer(remaining):
            found.append((match.start(), match.group(0).rstrip(TRAILING_PUNCTUATION)))
    for match in TICKED_FILE_RE.finditer(remaining):
        found.append((match.start(1), match.group(1)))
    return [reference for _, reference in sorted(found)]


def targets(event: dict) -> list[str]:
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    found: list[str] = []
    url = tool_input.get("url")
    if isinstance(url, str) and url:
        found.append(url)
    for key in PATH_INPUT_KEYS:
        value = tool_input.get(key)
        if isinstance(value, str) and value:
            found.append(value)
    if str(event.get("tool_name") or "") in SHELL_TOOLS:
        found.extend(extract_references(str(tool_input.get("command") or "")))
    return found


def prompt_names(target: str, prompt: str) -> bool:
    if target.rstrip("/") in prompt:
        return True
    if "://" in target:
        return False
    for token in PROMPT_SPLIT_RE.split(prompt):
        trimmed = token.removeprefix("./")
        if trimmed and target.rstrip("/").endswith("/" + trimmed):
            return True
    return False


def target_is_named(event: dict, prompt: str) -> bool:
    found = targets(event)
    return bool(found) and all(prompt_names(target, prompt) for target in found)


def latest_user_turn(rows: list[dict]) -> tuple[int, str] | None:
    """(row index, text) of the latest real user message, or None when a relayed machine turn is the latest."""
    for index in range(len(rows) - 1, -1, -1):
        row = rows[index]
        if row.get("type") != "user" or row.get("isMeta") or row.get("isSidechain"):
            continue
        content = message(row).get("content")
        if isinstance(content, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            continue
        text = content_text(content).strip()
        if not text:
            continue
        if is_user_prompt(row) and is_human_text(text):
            return index, text
        return None
    return None


def human_prompt_indexes(rows: list[dict]) -> list[int]:
    return [i for i, row in enumerate(rows) if is_user_prompt(row) and is_human_text(content_text(message(row).get("content")))]


def asks_a_question(text: str) -> bool:
    prose = INLINE_CODE_RE.sub(" ", FENCE_RE.sub(" ", URL_RE.sub(" ", text)))
    return any(line.rstrip().endswith("?") for line in prose.splitlines())


def already_asked(rows: list[dict], prompt_index: int) -> bool:
    last_text = ""
    for row in rows[prompt_index + 1:]:
        if row.get("type") != "assistant":
            continue
        for use in tool_uses(row):
            if use.get("name") in ASKING_TOOLS:
                return True
        content = message(row).get("content")
        if isinstance(content, list):
            texts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            if texts:
                last_text = "\n".join(texts)
    return bool(last_text) and asks_a_question(last_text)


def row_references(row: dict) -> list[str]:
    content = message(row).get("content")
    if not isinstance(content, list):
        return []
    found: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            found.extend(extract_references(str(block.get("text") or "")))
        elif block.get("type") == "tool_use":
            tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
            for key in ("url", *PATH_INPUT_KEYS, "path"):
                value = tool_input.get(key)
                if isinstance(value, str) and value:
                    found.append(value)
            if block.get("name") in SHELL_TOOLS:
                found.extend(extract_references(str(tool_input.get("command") or "")))
    return found


def candidates(rows: list[dict], prompt_index: int) -> list[str]:
    boundaries = [i for i in human_prompt_indexes(rows) if i < prompt_index]
    start = boundaries[-CANDIDATE_TURNS] if len(boundaries) >= CANDIDATE_TURNS else 0
    seen: dict[str, None] = {}
    for row in rows[start:prompt_index]:
        if row.get("type") != "assistant":
            continue
        for reference in row_references(row):
            seen.pop(reference, None)
            seen[reference] = None
    return list(seen)[-MAX_CANDIDATES:]


def judge_text(found: list[str], prompt: str) -> str:
    listing = "\n".join(f"- {c}" for c in found) or "- (nothing was mentioned)"
    return "\n".join([
        "Things the assistant mentioned in its last two turns:",
        listing,
        "The user's latest message:",
        prompt[-JUDGE_PROMPT_CHARS:],
    ])


def block_key(transcript: str, prompt_index: int, prompt: str) -> str:
    return f"ats-blocked-{judge_channel.sha(transcript + chr(0) + str(prompt_index) + chr(0) + prompt)}"


def evaluate(event: dict, wait: float | None = None) -> tuple[str, str]:
    """(outcome, message): outcome is "allow", "block", or "unchecked"."""
    if not isinstance(event, dict) or event.get("agent_id"):
        return "allow", ""
    action = gated_action(event)
    if action is None:
        return "allow", ""
    transcript = event.get("transcript_path") or event.get("transcriptPath")
    if not isinstance(transcript, str) or not transcript:
        return "unchecked", UNCHECKED_MESSAGE.format(action=action, why="the payload names no transcript")
    try:
        rows = read_lines(transcript)
    except OSError as exc:
        return "unchecked", UNCHECKED_MESSAGE.format(action=action, why=f"the transcript could not be read: {exc}")
    latest = latest_user_turn(rows)
    if latest is None:
        return "allow", ""
    prompt_index, prompt = latest
    if target_is_named(event, prompt) or already_asked(rows, prompt_index):
        return "allow", ""
    verdicts = judge_channel.Verdicts(CONFIG, transcript, time.time())
    blocked_id = block_key(transcript, prompt_index, prompt)
    if verdicts.outcome(blocked_id) == HIT:
        return "allow", ""
    found = candidates(rows, prompt_index)
    jid = verdicts.request(CHECKER, judge_text(found, prompt))
    outcome = judge_channel.await_verdicts(
        verdicts, [jid], lambda: verdicts.outcome(jid), wait_seconds() if wait is None else wait
    )
    if outcome == HIT:
        verdicts.record(blocked_id, HIT)
    verdicts.save()
    if outcome == CLEAN:
        return "allow", ""
    if outcome == UNCHECKED:
        why = verdicts.reasons.get(jid) or "the judge could not answer"
        return "unchecked", UNCHECKED_MESSAGE.format(action=action, why=why)
    listing = "\n".join(f"- {c}" for c in found) or NO_CANDIDATES
    return "block", BLOCK_MESSAGE.format(action=action, turns=CANDIDATE_TURNS, candidates=listing)


def detect(event: dict) -> list[Finding]:
    outcome, text = evaluate(event)
    if outcome == "unchecked":
        print(text, file=sys.stderr)
        subject = str(event.get("tool_use_id") or "unchecked")
        unchecked = Finding(rule_id="ask-to-scope.unchecked", subject=subject, message=text, evidence=text)
        event["_catstack_unchecked_findings"] = [unchecked]
        return []
    if outcome != "block":
        return []
    subject = str(event.get("tool_use_id") or f"tool:{event.get('tool_name')}")
    return [Finding(rule_id=RULE_ID, subject=subject, message=text, evidence=text[:2000])]
