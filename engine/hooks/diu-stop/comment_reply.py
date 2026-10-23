"""Refuse a reply to a comment on a document before it is posted when it runs
over diu's comment cap or uses wording the reader would have to ask about.

The reply body is read out of the tool call that posts it: an
`ArtifactComments` reply, or a Claude Docs utterance created on its own,
inside a batch, or by updating one. Three outcomes: block, allow, or
unchecked when the call posts a comment whose text cannot be read. The
mechanical half of the `phrases/plain-words-*` lists is checked here (code
names, abbreviations, technical words, status codes, two negatives in one
sentence); the lists that need a reader's judgment stay with the judge on
the Stop surface.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field

from diu_limit import comment_limit, comment_rule_text, comment_words, is_acknowledgement
from plain_words import recent_user_messages

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402

RULE_LENGTH = "diu-stop.comment-reply-length"
RULE_JARGON = "diu-stop.comment-reply-jargon"
RULE_UNCHECKED = "diu-stop.comment-reply-unchecked"

ARTIFACT_COMMENTS = "ArtifactComments"
DOCS_PREFIX = "mcp__claude_ai_Claude_Docs__"
DOCS_TOOLS = ("create", "batch", "update")
SURFACE_MARKERS = (ARTIFACT_COMMENTS, "Claude_Docs")
RECENT_USER_TURNS = 5
LISTED_HITS = 5
EXCERPT_LIMIT = 100

LENGTH_MESSAGE = (
    "diu: this reply to a comment on a document is {count} words; a comment reply is {rule}. "
    "Say the outcome in one or two plain sentences. Put anything longer into the document and point at it."
)
JARGON_MESSAGE = (
    "diu: this reply to a comment on a document uses wording the reader would have to ask about: {items}. "
    "Say it in everyday words, or reuse the words the comment itself used."
)
UNCHECKED_MESSAGE = (
    "diu: the reply text in this {surface} call could not be read ({detail}), so it is unchecked, not clean. "
    "Put the reply where the tool expects it (ArtifactComments: text; a Claude Docs utterance: "
    "payload.value.body) and send it again."
)

EVERYDAY_ABBREVIATIONS = frozenset({
    "OK", "PR", "PRS", "MR", "MRS", "CI", "ID", "IDS", "AM", "PM", "AI", "UI", "URL", "URLS",
    "FYI", "ASAP", "TODO", "PS", "US", "UK", "USA", "TV", "CEO", "VP", "QA", "ELI5", "FAQ", "PDF",
})
HYPHEN_MIDDLES = frozenset({"to", "by", "of", "the", "and", "in", "or", "a", "on", "for", "at", "up"})
TECHNICAL_WORDS = (
    "regex", "infra", "repo", "config", "auth", "token", "endpoint", "payload", "schema", "lint",
    "linter", "stdin", "stdout", "stderr", "env", "daemon", "cron", "webhook", "backend", "frontend",
    "runtime", "refactor", "redeploy", "rollback", "hotfix", "rebase", "cherry-pick", "squash",
    "force-push", "upstream", "downstream", "traceback", "segfault", "deadlock", "idempotent",
    "deterministic", "heuristic", "orchestrator", "worktree", "symlink", "subagent", "matcher",
    "preflight", "mutex", "latency", "throughput", "json", "yaml", "toml", "sdk", "cli", "api", "mcp",
    "http", "oauth", "jwt", "sha", "hash", "hunk", "lockfile", "monorepo", "namespace", "boolean",
    "null", "async", "callback", "middleware", "serialize", "parser", "stack trace", "race condition",
    "three-way", "merge-base",
)

FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
URL_RE = re.compile(r"https?://\S+")
CITATION_RE = re.compile(r"(?<![\w/.-])(?:[\w.-]+/)*[\w-]+\.[A-Za-z]\w*(?::\d+\b|#L\d+\b)(?:\s*@\s*\S+)?")
QUOTED_RE = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'|`[^`\n]*`")
CODE_NAME_RES = (
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b"),
    re.compile(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b"),
    re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+:(?=\s)"),
    re.compile(r"(?<![\w-])--[A-Za-z][\w-]*"),
    re.compile(r"(?<![\w/.-])[\w./-]*\w\.(?:py|js|mjs|cjs|ts|tsx|json|toml|ya?ml|sh|sql|rs|go|java|rb|css|html|md)\b"),
)
HYPHENATED_RE = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)+\b")
ABBREVIATION_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,5}\b")
STATUS_CODE_RE = re.compile(
    r"\b[1-5]\d\d\s+(?:unauthorized|forbidden|not found|bad request|internal server error|error|status|response|code)\b",
    re.IGNORECASE,
)
NEGATION_RE = re.compile(
    r"\b(?:no longer|never|not|cannot|can't|won't|don't|doesn't|didn't|isn't|aren't|wasn't|weren't"
    r"|without|nothing|none|nor|unless)\b",
    re.IGNORECASE,
)
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
WORD_RE = re.compile(r"[A-Za-z0-9][\w.-]*")


@dataclass
class Extraction:
    surface: str
    bodies: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Hit:
    kind: str
    text: str


def _kind(value) -> str:
    return "missing" if value is None else f"a {type(value).__name__}"


def _tool_name(event: dict) -> str | None:
    value = event.get("tool_name") or event.get("toolName")
    return value if isinstance(value, str) else None


def _artifact_comments(tool_input) -> Extraction | None:
    surface = f"{ARTIFACT_COMMENTS} reply"
    if not isinstance(tool_input, dict):
        return Extraction(surface, problems=["its input is not an object, so the action and text cannot be read"])
    if tool_input.get("action") != "reply":
        return None
    text = tool_input.get("text")
    if isinstance(text, str):
        return Extraction(surface, bodies=[text])
    return Extraction(surface, problems=[f"its text field is {_kind(text)}, not a string"])


def _is_utterance_op(item: dict) -> bool:
    if item.get("object") == "utterance":
        return True
    ref = item.get("ref")
    return isinstance(ref, dict) and ref.get("object") == "utterance"


def _utterance_body(payload) -> tuple[str | None, str | None]:
    if isinstance(payload, str):
        return payload, None
    if not isinstance(payload, dict):
        return None, f"the utterance payload is {_kind(payload)}, so its body cannot be read"
    value = payload.get("value", payload)
    if not isinstance(value, dict):
        return None, "the utterance value is not an object, so its body cannot be read"
    if value.get("kind") == "resolve":
        return None, None
    body = value.get("body")
    if isinstance(body, str):
        return body, None
    return None, f"the utterance body is {_kind(body)}, not a string"


def _from_utterances(surface: str, payloads: list) -> Extraction | None:
    extraction = Extraction(surface)
    for payload in payloads:
        body, problem = _utterance_body(payload)
        if problem:
            extraction.problems.append(problem)
        elif body is not None:
            extraction.bodies.append(body)
    if not extraction.bodies and not extraction.problems:
        return None
    return extraction


def _docs(name: str, tool_input) -> Extraction | None:
    surface = f"Claude Docs {name}"
    if not isinstance(tool_input, dict):
        return Extraction(surface, problems=["its input is not an object, so no comment inside it can be read"])
    if name == "create":
        if tool_input.get("object") != "utterance":
            return None
        return _from_utterances(surface, [tool_input.get("payload")])
    if name == "update":
        ref = tool_input.get("ref")
        if not (isinstance(ref, dict) and ref.get("object") == "utterance"):
            return None
        return _from_utterances(surface, [tool_input.get("payload")])
    batch = tool_input.get("batch")
    if batch is None:
        return None
    if not isinstance(batch, list):
        return Extraction(surface, problems=["its batch field is not a list, so no comment inside it can be read"])
    payloads = [item.get("payload") for item in batch if isinstance(item, dict) and _is_utterance_op(item)]
    if not payloads:
        return None
    return _from_utterances(surface, payloads)


def extract(event: dict) -> Extraction | None:
    """The reply bodies a tool call posts, or None when it posts no comment."""
    payload_error = event.get("_payload_error")
    if isinstance(payload_error, str):
        raw = event.get("_raw_payload")
        if isinstance(raw, str) and any(marker in raw for marker in SURFACE_MARKERS):
            return Extraction("comment-posting", problems=[payload_error])
        return None
    tool = _tool_name(event)
    if tool is None:
        return None
    tool_input = event.get("tool_input") or event.get("toolInput")
    if tool == ARTIFACT_COMMENTS:
        return _artifact_comments(tool_input)
    if tool.startswith(DOCS_PREFIX) and tool[len(DOCS_PREFIX):] in DOCS_TOOLS:
        return _docs(tool[len(DOCS_PREFIX):], tool_input)
    return None


def user_vocabulary(event: dict) -> tuple[frozenset[str], str]:
    """Words the user wrote in recent turns; a term they used first is theirs to reuse."""
    path = event.get("transcript_path")
    if not isinstance(path, str) or not path:
        return frozenset(), ""
    try:
        text = recent_user_messages(path, RECENT_USER_TURNS)
    except OSError as exc:
        print(
            f"catstack-hook-error diu-stop: cannot read {path}, so the comment's own words are "
            f"unknown and every term is checked: {exc}",
            file=sys.stderr,
        )
        return frozenset(), ""
    return frozenset(word.lower().rstrip(".") for word in WORD_RE.findall(text)), text.lower()


def _prose(body: str) -> str:
    return CITATION_RE.sub(" ", URL_RE.sub(" ", FENCE_RE.sub(" ", body)))


def _excerpt(sentence: str) -> str:
    flat = " ".join(sentence.split())
    return flat if len(flat) <= EXCERPT_LIMIT else flat[:EXCERPT_LIMIT - 3] + "..."


def _hyphenated_hit(token: str) -> bool:
    if any(ch.isdigit() for ch in token) and any(ch.isalpha() for ch in token):
        return True
    parts = token.split("-")
    return len(parts) >= 3 and not any(part in HYPHEN_MIDDLES for part in parts[1:-1])


def find_jargon(body: str, known_words: frozenset[str] = frozenset(), user_text: str = "") -> list[Hit]:
    prose = _prose(body)
    hits: list[Hit] = []
    seen: set[str] = set()

    def known(token: str) -> bool:
        lowered = token.lower().rstrip(":")
        return lowered in known_words or (bool(user_text) and lowered in user_text)

    def add(kind: str, token: str) -> None:
        key = token.lower().rstrip(":")
        if key in seen or known(token):
            return
        seen.add(key)
        hits.append(Hit(kind, token))

    for pattern in CODE_NAME_RES:
        for match in pattern.finditer(prose):
            add("a code name", match.group(0))
    for match in HYPHENATED_RE.finditer(prose):
        if _hyphenated_hit(match.group(0)):
            add("an internal name", match.group(0))
    for match in ABBREVIATION_RE.finditer(prose):
        if match.group(0) not in EVERYDAY_ABBREVIATIONS:
            add("an abbreviation", match.group(0))
    for word in TECHNICAL_WORDS:
        match = re.search(rf"(?<![\w-]){re.escape(word)}(?:e?s)?(?![\w-])", prose, re.IGNORECASE)
        if match:
            add("a technical word", match.group(0))
    for match in STATUS_CODE_RE.finditer(prose):
        add("a status code", match.group(0))
    for sentence in SENTENCE_RE.split(QUOTED_RE.sub(" ", prose)):
        if len(NEGATION_RE.findall(sentence)) >= 2:
            hits.append(Hit("two negatives in one sentence", _excerpt(sentence)))
    return hits


def _items(hits: list[Hit]) -> str:
    listed = [f'{hit.kind} "{hit.text}"' for hit in hits[:LISTED_HITS]]
    if len(hits) > LISTED_HITS:
        listed.append(f"and {len(hits) - LISTED_HITS} more")
    return "; ".join(listed)


def check_body(body: str, known_words: frozenset[str] = frozenset(), user_text: str = "") -> list[Finding]:
    findings = []
    count = comment_words(body)
    if count > comment_limit(body):
        message = LENGTH_MESSAGE.format(count=count, rule=comment_rule_text(is_acknowledgement(body)))
        findings.append(Finding(rule_id=RULE_LENGTH, subject=body, message=message, evidence=f"{count} words"))
    hits = find_jargon(body, known_words, user_text)
    if hits:
        message = JARGON_MESSAGE.format(items=_items(hits))
        findings.append(Finding(rule_id=RULE_JARGON, subject=body, message=message, evidence=_items(hits)))
    return findings


def detect(event: dict) -> list[Finding]:
    extraction = extract(event)
    if extraction is None:
        return []
    findings = []
    for problem in extraction.problems:
        message = UNCHECKED_MESSAGE.format(surface=extraction.surface, detail=problem)
        findings.append(Finding(rule_id=RULE_UNCHECKED, subject=problem, message=message, evidence=problem))
    known_words, user_text = user_vocabulary(event)
    for body in extraction.bodies:
        findings.extend(check_body(body, known_words, user_text))
    return findings
