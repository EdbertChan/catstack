"""agent-routing-guard: refuse an Agent spawn that carries publication work
while Invoker is available.

The incident this closes: one session spawned eight subagents, each of which
produced a PR-worthy commit, with `invoker-cli` on PATH and the user having
asked three separate times to route through Invoker. Nothing guarded the
vehicle -- the only PreToolUse hook matching the Agent tool
(engine/hooks/cat-mode-default) injects cat-mode into the subagent's prompt
and never asks whether a subagent was the right runner at all.

Fires when both hold:

1. The Agent payload's prompt carries a publication verb -- commit, push,
   merge, or open/make/create/raise/file/submit/land a PR. The verb has to
   read as an action: a determiner in front of it ("the last commit", "a
   PR-worthy commit", "each merge") marks a noun, which is how a read-only
   research or verification prompt mentions the same words. A verb negated
   earlier in its own clause ("Do not edit, create, commit, or push
   anything") and a verb hyphen-joined into a name ("principle-push-not-poll",
   "auto-merge") do not count either; "force-push" and "squash-merge" still do.
2. `invoker-cli` resolves on PATH. That is a proxy for the routing rule's own
   condition -- Invoker's MCP tools being available -- which a PreToolUse
   payload cannot see. PATH is the observable stand-in and is named as such
   wherever this hook reports.

Stays silent when `invoker-cli` is absent (nothing to route to), when the
prompt has no publication verb, when the payload carries `agent_id` (a
subagent splitting its own work is not the routing decision -- rule 3 was
already answered by whoever spawned it), and when the user's current message
says "do it locally" or "don't use invoker".

THE OVERRIDE CHECK FAILS CLOSED, deliberately, and it is the one part of
this hook that does. The override lives in the user's current message, which
this reads from the transcript. Three outcomes, not two: the message says
override (silent), the message says nothing (block), or the message could
not be read -- no transcript path, an unreadable or over-cap file, no user
line in it -- which blocks with its own message naming the reason. An
override that cannot be read is not an override; treating "unreadable" as
"no override was given" would be the safe direction only if the hook were
optional, and treating it as "an override was given" would silently restore
the incident. The block costs a turn and names how to clear it. Everything
else here fails open: a payload that will not parse, a missing tool_input,
and a promptless call are all left alone.
"""
from __future__ import annotations

import json
import os
import re
import shutil

AGENT_TOOL_NAMES = frozenset({"Agent", "Task"})
INVOKER_CLI = "invoker-cli"
ROUTING_SKILL = "invoker-plan-to-invoker"

TRANSCRIPT_SIZE_CAP_BYTES = 32 * 1024 * 1024
OVERRIDE_SCAN_TAIL_CHARS = 400

OVERRIDE_PRESENT = "override"
OVERRIDE_ABSENT = "none"
OVERRIDE_UNCHECKED = "unchecked"

ACTION_VERB_RES = (
    ("commit", re.compile(r"(?i)\bcommit(?:s|ted|ting)?\b")),
    ("push", re.compile(r"(?i)\bpush(?:es|ed|ing)?\b")),
    ("merge", re.compile(r"(?i)\bmerg(?:e|es|ed|ing)\b")),
)

PR_ACTION_RE = re.compile(
    r"(?i)\b(?:open|opens|opening|make|makes|making|create|creates|creating"
    r"|raise|raises|raising|file|files|filing|submit|submits|submitting"
    r"|land|lands|landing|ship|ships|shipping)\s+"
    r"(?:(?:a|an|the|one|another|its|your|their|each|every|\d+)\s+)?"
    r"(?:draft\s+)?(?:prs?|pull\s+requests?)\b"
)

NOUN_CONTEXT_RE = re.compile(
    r"(?i)\b(?:the|a|an|this|that|these|those|each|every|one|two|three|\d+"
    r"|last|latest|previous|first|newest|next|head|initial|merge|which|whose"
    r"|its|his|her|their|your|my|our)\s+(?:\w+[\s-]+){0,2}\Z"
)

CLAUSE_BREAK_RE = re.compile(r"[.!?](?=\s)|[;\n\r]")
NEGATION_RE = re.compile(r"(?i)(?<![\w-])(?:not|never|neither|nor|without|don['’]?t|no)(?![\w-])")
SCOPE_BREAK_RE = re.compile(
    r"(?i)\b(?:but|then|instead|until|unless|before|after|once|except|rather|so)\b"
)
DOUBLE_NEGATIVE_RE = re.compile(r"(?i)\s*(?:forget|fail|hesitate|neglect|stop|omit)\b")
LIST_SEPARATOR_RE = re.compile(r"(?i),|\b(?:and|or|nor)\b")
NO_GAP_RE = re.compile(r"(?i)\s*(?:need\s+to\s+)?")
HYPHEN_PREFIX_RE = re.compile(r"(\w+)-\Z")
HYPHEN_SUFFIX_RE = re.compile(r"-\w")
HYPHEN_VERB_PREFIXES = frozenset({"force", "re", "squash", "rebase"})

SUBAGENT_ID_KEYS = ("agent_id", "agentId")

LOCAL_OVERRIDE_RES = (
    re.compile(r"(?i)\b(?:do|run|fix|handle|keep|build|write|land)\s+"
               r"(?:it|this|that|these|them|the\s+\w+)\s+local(?:ly)?\b"),
    re.compile(r"(?i)\b(?:stay|keep\s+it|keep\s+this)\s+local\b"),
    re.compile(r"(?i)\blocal(?:ly)?\s+only\b"),
    re.compile(r"(?i)\b(?:don'?t|do\s+not|no\s+need\s+to|never)\s+use\s+invoker\b"),
    re.compile(r"(?i)\b(?:without|skip|bypass|no)\s+invoker\b"),
)

BLOCK_MESSAGE = (
    "agent-routing-guard: this Agent spawn carries publication work ({verbs}) and "
    "invoker-cli is on PATH, so the subagent is the wrong vehicle. cat-mode "
    "execution routing rule 3 -- an approved plan or durable/parallel work goes to "
    "Invoker when Invoker is available, not into parallel subagents each landing "
    "its own commit -- decides this one. Follow the installed {skill} skill to "
    "produce the plan, then invoker_prepare_plan_review, one explicit user "
    "approval, invoker_submit_plan. A subagent is still the right tool for "
    "read-only research and verification. The user overrides this by saying \"do "
    "it locally\" or \"don't use invoker\"."
)

UNCHECKED_MESSAGE = (
    "agent-routing-guard: this Agent spawn carries publication work ({verbs}) and "
    "invoker-cli is on PATH, and the local override could not be checked ({reason}). "
    "An override that cannot be read is not an override, so cat-mode execution "
    "routing rule 3 stands: an approved plan or durable/parallel work goes to "
    "Invoker, not into parallel publishing subagents. Follow the installed {skill} "
    "skill, or ask the user to restate \"do it locally\" / \"don't use invoker\" in "
    "this turn."
)


def tool_name(payload: dict) -> str:
    for key in ("tool_name", "toolName", "tool", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def transcript_path(payload: dict) -> str:
    for key in ("transcript_path", "transcriptPath"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def spawned_by_subagent(payload: dict) -> bool:
    """True when the caller is itself a subagent.

    Rule 3 is a decision about the parent's work, taken once. A subagent that
    fans its own slice out further is executing a route that was already
    chosen, so re-asking there would block work Invoker may itself be running.
    """
    for key in SUBAGENT_ID_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _is_noun_use(text: str, start: int) -> bool:
    return bool(NOUN_CONTEXT_RE.search(text[:start]))


def _is_hyphen_joined(text: str, start: int, end: int) -> bool:
    if HYPHEN_SUFFIX_RE.match(text, end):
        return True
    prefix = HYPHEN_PREFIX_RE.search(text[:start])
    return bool(prefix) and prefix.group(1).lower() not in HYPHEN_VERB_PREFIXES


def _is_negated(text: str, start: int) -> bool:
    """True when a negation cue earlier in the verb's clause governs it.

    The cue stops governing at a scope word ("but", "then", "until"), after
    "don't forget" and its kin, and after a list item longer than one word, so
    "Don't touch the tests, fix it and commit" still counts the commit.
    "no" only governs the word right after it ("no pushing", "no need to").
    """
    clause = CLAUSE_BREAK_RE.split(text[:start])[-1]
    cues = list(NEGATION_RE.finditer(clause))
    if not cues:
        return False
    cue = cues[-1]
    gap = clause[cue.end():]
    if SCOPE_BREAK_RE.search(gap) or DOUBLE_NEGATIVE_RE.match(gap):
        return False
    if cue.group().lower() == "no":
        return bool(NO_GAP_RE.fullmatch(gap))
    return all(len(item.split()) <= 1 for item in LIST_SEPARATOR_RE.split(gap)[:-1])


def publication_verbs(prompt: str) -> list[str]:
    """The publication verbs this prompt uses as actions, deduped and ordered."""
    text = prompt or ""
    found: list[str] = []
    for label, pattern in ACTION_VERB_RES:
        for match in pattern.finditer(text):
            if _is_noun_use(text, match.start()):
                continue
            if _is_hyphen_joined(text, match.start(), match.end()):
                continue
            if _is_negated(text, match.start()):
                continue
            found.append(label)
            break
    if any(not _is_negated(text, match.start()) for match in PR_ACTION_RE.finditer(text)):
        found.append("open a PR")
    return found


def invoker_available(path: str | None = None) -> bool:
    return bool(shutil.which(INVOKER_CLI, path=path))


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "output_text"):
                parts.append(str(block.get("text") or ""))
        return "\n".join(parts)
    return ""


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    text = _text_content(data)
    return bool(text.strip()) and not text.lstrip().startswith("<")


def last_human_message(path: str) -> tuple[str, str]:
    """(text, reason). A non-empty reason means the message could not be read
    and the caller must treat the override as unchecked, never as absent."""
    if not path:
        return "", "no transcript path in the hook payload"
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        return "", f"transcript unreadable: {exc}"
    if size > TRANSCRIPT_SIZE_CAP_BYTES:
        return "", (
            f"transcript is {size} bytes, over the "
            f"{TRANSCRIPT_SIZE_CAP_BYTES}-byte scan cap"
        )
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError as exc:
        return "", f"transcript unreadable: {exc}"
    for raw in reversed(lines):
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict) and _is_human_user_line(data):
            return _text_content(data), ""
    return "", "no user message in the transcript"


def override_state(path: str) -> tuple[str, str]:
    """One of OVERRIDE_PRESENT / OVERRIDE_ABSENT / OVERRIDE_UNCHECKED, plus
    the reason when the check could not run.

    Only the tail of the message is scanned. A long paste is a log or a
    transcript whose quoted text can contain "do not use Invoker" as somebody
    else's dialogue; a live directive sits at the edge of what was just typed.
    """
    text, reason = last_human_message(path)
    if reason:
        return OVERRIDE_UNCHECKED, reason
    window = text[-OVERRIDE_SCAN_TAIL_CHARS:]
    if any(pattern.search(window) for pattern in LOCAL_OVERRIDE_RES):
        return OVERRIDE_PRESENT, ""
    return OVERRIDE_ABSENT, ""


def block_message(verbs: list[str]) -> str:
    return BLOCK_MESSAGE.format(verbs=", ".join(verbs), skill=ROUTING_SKILL)


def unchecked_message(verbs: list[str], reason: str) -> str:
    return UNCHECKED_MESSAGE.format(
        verbs=", ".join(verbs), reason=reason, skill=ROUTING_SKILL
    )


def decide(payload: dict) -> str | None:
    """The refusal to print, or None to let the spawn through."""
    if not isinstance(payload, dict):
        return None
    if tool_name(payload) not in AGENT_TOOL_NAMES:
        return None
    tool_input = payload.get("tool_input") or payload.get("toolInput")
    if not isinstance(tool_input, dict):
        return None
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    if spawned_by_subagent(payload):
        return None
    verbs = publication_verbs(prompt)
    if not verbs:
        return None
    if not invoker_available():
        return None
    state, reason = override_state(transcript_path(payload))
    if state == OVERRIDE_PRESENT:
        return None
    if state == OVERRIDE_UNCHECKED:
        return unchecked_message(verbs, reason)
    return block_message(verbs)
