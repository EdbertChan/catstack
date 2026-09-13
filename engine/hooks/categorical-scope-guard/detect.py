"""categorical-scope-guard: a categorical word binds the whole set a command mutates.

When the live instruction quantifies a target with all / every / each / the
whole / any and all ("make all tasks use claude"), a mutation of that target
narrowed by a status or state discriminator swaps the user's word for the
agent's own judgment about which members matter. This module decides, for one
shell command, whether that happened.

Three outcomes. HIT: the user quantified noun N categorically and the command
mutates N through a status/state filter that is not the complete set. CLEAN:
anything else that could be classified. UNCHECKED: the command filters a
mutation by status but the filter values or the human turns could not be read.
"""
from __future__ import annotations
import sys

import json
import os
import re
from dataclasses import dataclass, field

HIT = "hit"
CLEAN = "clean"
UNCHECKED = "unchecked"

LIVE_TURNS = 4
MAX_SCAN_BYTES = 64 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
LONG_TURN_CHARS = 800
EDGE_CHARS = 400

TASK_STATUSES = frozenset({
    "pending", "queued", "running", "fixing_with_ai", "completed", "failed", "closed",
    "needs_input", "blocked", "review_ready", "awaiting_approval", "stale", "skipped",
})
WORKFLOW_STATUSES = frozenset({
    "pending", "running", "fixing_with_ai", "completed", "failed", "closed", "blocked",
    "review_ready", "awaiting_approval", "stale",
})
UNIVERSES = {
    "pr": frozenset({"open", "closed", "merged"}),
    "issue": frozenset({"open", "closed"}),
    "task": TASK_STATUSES,
    "workflow": WORKFLOW_STATUSES,
}
SUBSET_WORDS = frozenset({
    "open", "opened", "closed", "merged", "draft", "drafts", "pending", "queued", "running",
    "completed", "complete", "failed", "failing", "blocked", "stale", "skipped", "cancelled",
    "canceled", "remaining", "active", "inflight", "in-flight", "unfinished", "outstanding",
    "stuck", "incomplete", "done", "finished", "successful", "succeeded", "broken", "errored",
    "erroring", "waiting", "paused", "unstarted", "started", "non-terminal", "nonterminal",
    "unmerged", "approved", "mergeable", "green", "red", "passing", "live", "current", "new",
    "old", "existing", "leftover", "unrun", "idle", "terminal", "in_progress", "in-progress",
    "needs_input", "review_ready", "awaiting_approval", "fixing_with_ai",
})

NOUN_FORMS = {
    "pr": r"prs|pr|pull[\s-]+requests?",
    "issue": r"issues?",
    "run": r"runs|(?:workflow|ci|actions?)\s+runs?",
    "task": r"tasks?",
    "workflow": r"workflows?",
}

QUANTIFIER = r"any\s+and\s+all|all|every|each|the\s+whole|everything\s+(?:in|on|under)"
DETERMINER = r"(?:of\s+)?(?:(?:the|these|those|our|my|your|their|its|this|that)\s+)?"
PHRASE_BREAKERS = frozenset({
    "in", "on", "at", "to", "for", "with", "and", "or", "but", "of", "from", "by", "use",
    "using", "is", "are", "be", "that", "which", "who", "as", "into", "so", "then", "if",
    "not", "set", "make", "get", "have", "has", "had", "was", "were", "it", "them", "we",
    "you", "i",
})
STATE_QUESTION_OPENERS = frozenset({
    "are", "is", "was", "were", "do", "does", "did", "have", "has", "had",
})
LEADING_FILLERS = frozenset({"ok", "okay", "so", "now", "and", "but", "then", "wait", "hey", "also", "right", "alright"})

COMPLETE_SET_RE = re.compile(r"(?im)^[\s>*_-]*complete set\s*[:：]\s*\S")

NON_HUMAN_PREFIXES = (
    "stop hook feedback:",
    "<task-notification>",
    "base directory for this skill:",
    "this session is being continued",
    "caveat:",
    "<local-command-stdout>",
    "<local-command-stderr>",
    "[request interrupted",
    "another claude session sent a message",
    "<teammate-message",
    "<system-reminder>",
    "<bash-input>",
    "<bash-stdout>",
    "<bash-stderr>",
    "<user-prompt-submit-hook>",
    "[image",
)
COMMAND_ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)
COMMAND_WRAPPER_RE = re.compile(r"^\s*<command-(?:message|name)>")

FENCE_RE = re.compile(r"```[^\n]*\n.*?\n\s*```", re.S)
BLOCKQUOTE_RE = re.compile(r"(?m)^\s*>.*$")
INLINE_CODE_RE = re.compile(r"`[^`\n]*`")
DOUBLE_QUOTED_RE = re.compile(r"\"[^\"\n]{0,200}\"|“[^”\n]{0,200}”")

STATUS_HINT_RE = re.compile(
    r"(?i)status|state|\s-s\s|\bupdate\s+\S+\s+set\b|\bdelete\s+from\b|\b(?:"
    + "|".join(sorted(re.escape(w) for w in SUBSET_WORDS)) + r")\b"
)


@dataclass(frozen=True)
class ScopedFilter:
    noun: str
    text: str
    values: tuple[str, ...] | None
    negated: bool = False

    @property
    def readable(self) -> bool:
        return self.values is not None

    def is_complete(self) -> bool:
        if self.values is None:
            return False
        lowered = {v.lower() for v in self.values}
        if self.negated:
            return not lowered
        if "all" in lowered:
            return True
        universe = UNIVERSES.get(self.noun)
        return bool(universe) and lowered >= universe

    def describe(self) -> str:
        if self.values is None:
            return f"`{self.text}` (values the hook cannot read)"
        if self.negated:
            return f"`{self.text}` (drops {', '.join(self.values)})"
        return f"`{self.text}` (keeps only {', '.join(self.values)})"


@dataclass
class LiveWindow:
    turns: list[str] = field(default_factory=list)
    assistant_after: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Verdict:
    outcome: str
    message: str = ""


class Unreadable(Exception):
    pass


def canonical_noun(word: str) -> str:
    w = re.sub(r"[`\"'\[\]]", "", word).lower()
    if re.fullmatch(r"pull[\s-]+requests?", w):
        return "pr"
    for noun, forms in NOUN_FORMS.items():
        if re.fullmatch(forms, w):
            return noun
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "sses", "xes")):
        return w[:-2]
    if w.endswith("s") and not w.endswith("ss") and len(w) > 2:
        return w[:-1]
    return w


def noun_forms(noun: str) -> str:
    if noun in NOUN_FORMS:
        return NOUN_FORMS[noun]
    base = re.escape(noun)
    if noun.endswith("y"):
        return base + "|" + re.escape(noun[:-1]) + "ies"
    return base + "|" + base + "s|" + base + "es"


def _sql_body(text: str, start: int, limit: int = 2000) -> tuple[str, int]:
    out = []
    in_literal = False
    i = start
    end = min(len(text), start + limit)
    while i < end:
        ch = text[i]
        if text.startswith("'''", i) or text.startswith('"""', i):
            break
        if in_literal:
            out.append(ch)
            if ch == "'":
                in_literal = False
        elif ch == "'":
            in_literal = True
            out.append(ch)
        elif ch in "\";":
            break
        elif ch == "\\" and i + 1 < end and text[i + 1] == '"':
            break
        else:
            out.append(ch)
        i += 1
    return "".join(out), i


SQL_STATEMENT_RE = re.compile(
    r"(?i)\b(?:(update)\s+[`\[]?([A-Za-z_]\w*)[`\]]?\s+set\b"
    r"|(delete)\s+from\s+[`\[]?([A-Za-z_]\w*)[`\]]?"
    r"|(select)\b[^\";]{0,600}?\bfrom\s+[`\[]?([A-Za-z_]\w*)[`\]]?)"
)
STATUS_PREDICATE_RE = re.compile(
    r"(?i)(?<![\w.])(?:\w+\.)?(status|state)\s*(not\s+in|in|==|=|!=|<>)\s*"
    r"(\([^)]*\)|'[^']*'|\?|:\w+|%s|\{[^}]*\}|\$\w+|[A-Za-z_]\w*)"
)
SQL_LITERAL_RE = re.compile(r"'([^']*)'")
ID_KEYED_RE = re.compile(r"(?i)^\s*\(?\s*(?:\w+\.)?(?:rowid|id|\w+_id)\s*(?:=|in\b)")
DYNAMIC_SQL_RE = re.compile(r"\{[^}]*\}|%s|%\(")
CONCAT_AFTER_RE = re.compile(r"^\\?[\"']*\s*(?:\+|%|\.format\b)")


def _parse_sql_values(raw: str) -> tuple[str, ...] | None:
    raw = raw.strip()
    if raw.startswith("("):
        inner = raw[1:-1] if raw.endswith(")") else raw[1:]
        literals = SQL_LITERAL_RE.findall(inner)
        leftover = SQL_LITERAL_RE.sub("", inner).replace(",", "").strip()
        if leftover or not literals:
            return None
        return tuple(literals)
    if raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
        return (raw[1:-1],)
    return None


def _status_filters_in(where: str, noun: str) -> list[ScopedFilter]:
    found = []
    for match in STATUS_PREDICATE_RE.finditer(where):
        op = re.sub(r"\s+", " ", match.group(2).lower())
        values = _parse_sql_values(match.group(3))
        found.append(ScopedFilter(
            noun=noun,
            text=re.sub(r"\s+", " ", match.group(0).strip()),
            values=values,
            negated=op in {"not in", "!=", "<>"},
        ))
    return found


def sql_filters(command: str) -> list[ScopedFilter]:
    statements = []
    for match in SQL_STATEMENT_RE.finditer(command):
        kind = (match.group(1) or match.group(3) or match.group(5)).lower()
        table = match.group(2) or match.group(4) or match.group(6)
        body, end = _sql_body(command, match.start())
        statements.append((kind, canonical_noun(table), body, command[end:end + 12]))
    filters: list[ScopedFilter] = []
    selects_needed: set[str] = set()
    for kind, noun, body, after in statements:
        if kind == "select":
            continue
        where_match = re.search(r"(?is)\bwhere\b(.*)$", body)
        if not where_match:
            continue
        where = where_match.group(1)
        own = _status_filters_in(where, noun)
        if own:
            filters.extend(own)
        elif ID_KEYED_RE.search(where):
            selects_needed.add(noun)
        elif DYNAMIC_SQL_RE.search(where) or CONCAT_AFTER_RE.match(where.strip() or after):
            filters.append(ScopedFilter(noun=noun, text=re.sub(r"\s+", " ", body.strip())[:120], values=None))
    for kind, noun, body, _after in statements:
        if kind != "select" or noun not in selects_needed:
            continue
        where_match = re.search(r"(?is)\bwhere\b(.*)$", body)
        if where_match:
            filters.extend(_status_filters_in(where_match.group(1), noun))
    return _dedupe(filters)


def _dedupe(filters: list[ScopedFilter]) -> list[ScopedFilter]:
    seen = set()
    out = []
    for f in filters:
        key = (f.noun, f.text, f.values, f.negated)
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


@dataclass
class Pipeline:
    stages: list[str]
    substituted: bool
    consumer: str = ""


@dataclass
class _Frame:
    substituted: bool
    consumer: str = ""
    backtick: bool = False
    in_double: bool = False
    stages: list[str] = field(default_factory=list)
    buf: list[str] = field(default_factory=list)


def split_pipelines(command: str) -> list[Pipeline]:
    pipelines: list[Pipeline] = []
    frames = [_Frame(substituted=False)]

    def flush_stage(frame: _Frame) -> None:
        frame.stages.append("".join(frame.buf).strip())
        frame.buf.clear()

    def flush_pipeline(frame: _Frame) -> None:
        flush_stage(frame)
        kept = [stage for stage in frame.stages if stage]
        if kept:
            pipelines.append(Pipeline(kept, frame.substituted, frame.consumer))
        frame.stages.clear()

    def close_frame() -> None:
        flush_pipeline(frames.pop())
        frames[-1].buf.append("$(...)")

    i = 0
    n = len(command)
    while i < n:
        frame = frames[-1]
        ch = command[i]
        two = command[i:i + 2]
        if frame.in_double:
            if ch == "\\" and i + 1 < n:
                frame.buf.append(command[i:i + 2])
                i += 2
            elif ch == '"':
                frame.in_double = False
                frame.buf.append(ch)
                i += 1
            elif two == "$(":
                frames.append(_Frame(substituted=True, consumer="".join(frame.buf).strip()))
                i += 2
            elif ch == "`":
                frames.append(_Frame(substituted=True, consumer="".join(frame.buf).strip(), backtick=True))
                i += 1
            else:
                frame.buf.append(ch)
                i += 1
            continue
        if ch == "\\" and i + 1 < n:
            frame.buf.append(command[i:i + 2])
            i += 2
        elif ch == "'":
            close = command.find("'", i + 1)
            close = n - 1 if close == -1 else close
            frame.buf.append(command[i:close + 1])
            i = close + 1
        elif ch == '"':
            frame.in_double = True
            frame.buf.append(ch)
            i += 1
        elif two in ("$(", "<(", ">("):
            frames.append(_Frame(substituted=True, consumer="".join(frame.buf).strip()))
            i += 2
        elif ch == "`":
            if frame.backtick:
                close_frame()
            else:
                frames.append(_Frame(substituted=True, consumer="".join(frame.buf).strip(), backtick=True))
            i += 1
        elif ch == ")" and len(frames) > 1 and not frame.backtick:
            close_frame()
            i += 1
        elif two in ("||", "&&"):
            flush_pipeline(frame)
            i += 2
        elif ch in ";\n&()":
            flush_pipeline(frame)
            i += 1
        elif ch == "|":
            flush_stage(frame)
            i += 1
        else:
            frame.buf.append(ch)
            i += 1
    while len(frames) > 1:
        close_frame()
    flush_pipeline(frames[0])
    return pipelines


FLAG_VALUE = r"(?:=|\s+)(\"[^\"]*\"|'[^']*'|[^\s;|&)]+)"
LISTINGS = (
    (re.compile(r"\bgh\s+(pr|issue)\s+list\b"), (r"--state", r"-s")),
    (re.compile(r"\bgh\s+(run)\s+list\b"), (r"--status", r"-s")),
    (re.compile(r"\binvoker-cli\s+query\s+(tasks|workflows)\b"), (r"--status",)),
)
RETRY_TASKS_RE = re.compile(r"\binvoker-cli\s+retry-tasks\b")
JQ_EQ_RE = re.compile(r"\.(status|state)\s*(==|!=)\s*(\"[^\"]*\"|\$\w+|\.\w+)")
JQ_IN_RE = re.compile(r"\.(status|state)\s*\|\s*(IN|test)\s*\(([^)]*)\)")
PY_STATUS_RE = re.compile(
    r"(?:\.get\(\s*['\"](?:status|state)['\"][^)]*\)|\[\s*['\"](?:status|state)['\"]\s*\])"
    r"\s*(not\s+in|in|==|!=)\s*(\([^)]*\)|\[[^\]]*\]|'[^']*'|\"[^\"]*\"|\w+)"
)


def _flag_filter(stage: str, noun: str, flags: tuple[str, ...]) -> ScopedFilter | None:
    for flag in flags:
        match = re.search(r"(?<!\S)" + re.escape(flag) + FLAG_VALUE, stage)
        if not match:
            continue
        raw = match.group(1)
        text = f"{flag} {raw}"
        value = raw.strip("\"'")
        if not value or re.search(r"[$`{}*]", value):
            return ScopedFilter(noun=noun, text=text, values=None)
        return ScopedFilter(noun=noun, text=text, values=tuple(v for v in value.split(",") if v))
    return None


def _jq_filter(text: str, noun: str) -> ScopedFilter | None:
    text = text.replace('\\"', '"')
    eq, ne, unreadable, spans = [], [], False, []
    for match in JQ_EQ_RE.finditer(text):
        spans.append(match.group(0))
        raw = match.group(3)
        if not raw.startswith('"'):
            unreadable = True
            continue
        (eq if match.group(2) == "==" else ne).append(raw.strip('"'))
    for match in JQ_IN_RE.finditer(text):
        spans.append(match.group(0))
        literals = re.findall(r"\"([^\"]*)\"", match.group(3))
        if not literals:
            unreadable = True
            continue
        if match.group(2) == "test":
            eq.extend(v for lit in literals for v in re.split(r"[|()^$]+", lit) if v)
        else:
            eq.extend(literals)
    if not spans:
        return None
    text_repr = " ".join(spans)[:160]
    if unreadable:
        return ScopedFilter(noun=noun, text=text_repr, values=None)
    if eq:
        return ScopedFilter(noun=noun, text=text_repr, values=tuple(eq))
    return ScopedFilter(noun=noun, text=text_repr, values=tuple(ne), negated=True)


def _grep_filter(stage: str, noun: str) -> ScopedFilter | None:
    match = re.match(r"^(?:e|f|r)?grep\b|^rg\b", stage)
    if not match:
        return None
    rest = stage[match.end():]
    negated = bool(re.search(r"(?<!\S)-[a-zA-Z]*v[a-zA-Z]*(?!\S)", rest))
    tokens = re.findall(r"\"[^\"]*\"|'[^']*'|\S+", rest)
    pattern = None
    skip_next = False
    for tok in tokens:
        if skip_next:
            pattern = tok
            break
        if tok in ("-e", "--regexp"):
            skip_next = True
            continue
        if tok.startswith("-"):
            continue
        pattern = tok
        break
    if pattern is None:
        return None
    body = pattern.strip("\"'")
    words = [w.lower() for w in re.split(r"\\?\||[^A-Za-z_-]+", body) if w]
    words = [w for w in words if w not in {"status", "state", "e", "b", "i", "w"}]
    if not words:
        return None
    vocab = SUBSET_WORDS | UNIVERSES.get(noun, frozenset())
    if not all(w in vocab for w in words):
        return None
    return ScopedFilter(noun=noun, text=f"grep {pattern}"[:120], values=tuple(words), negated=negated)


def _python_filter(stage: str, noun: str) -> ScopedFilter | None:
    if not re.match(r"^python3?\b", stage):
        return None
    text = stage.replace('\\"', '"')
    match = PY_STATUS_RE.search(text)
    if not match:
        return None
    op = re.sub(r"\s+", " ", match.group(1))
    raw = match.group(2)
    if re.fullmatch(r"[A-Za-z_]\w*", raw):
        bound = re.search(r"(?m)^\s*" + re.escape(raw) + r"\s*=\s*(?:frozenset\(|set\()?([\[{(][^\]})]*[\]})])", text)
        raw = bound.group(1) if bound else raw
    literals = re.findall(r"'([^']*)'|\"([^\"]*)\"", raw)
    values = tuple(a or b for a, b in literals) if literals else None
    negated = op in {"not in", "!="}
    if re.match(r"\s*\)?\s*:\s*continue\b", text[match.end():]):
        negated = not negated
    return ScopedFilter(noun=noun, text=match.group(0)[:120], values=values, negated=negated)


SET_CONSUMER_RE = re.compile(r"^(?:xargs|while|parallel|for)\b")
DISPLAY_CONSUMER_RE = re.compile(r"^(?:echo|printf|print)\b")


def cli_filters(command: str) -> list[tuple[ScopedFilter, bool]]:
    found_all: list[tuple[ScopedFilter, bool]] = []
    for pipeline in split_pipelines(command):
        stages = pipeline.stages
        noun = None
        found: list[ScopedFilter] = []
        feeds = pipeline.substituted and not DISPLAY_CONSUMER_RE.match(pipeline.consumer)
        for stage in stages:
            if noun is None:
                for listing_re, flags in LISTINGS:
                    match = listing_re.search(stage)
                    if match:
                        noun = canonical_noun(match.group(1))
                        flag = _flag_filter(stage, noun, flags)
                        if flag:
                            found.append(flag)
                        jq_arg = re.search(r"--jq\s+('[^']*'|\"(?:\\.|[^\"\\])*\")", stage)
                        if jq_arg:
                            jq = _jq_filter(jq_arg.group(1), noun)
                            if jq:
                                found.append(jq)
                        break
                continue
            if SET_CONSUMER_RE.match(stage) or stage_mutates(stage, noun):
                feeds = True
            for probe in (
                lambda s: _jq_filter(s, noun) if re.match(r"^jq\b", s) else None,
                lambda s: _grep_filter(s, noun),
                lambda s: _python_filter(s, noun),
            ):
                hit = probe(stage)
                if hit:
                    found.append(hit)
                    break
        found_all.extend((f, feeds) for f in found)
    return found_all


GH_WRITE_API_RE = re.compile(
    r"\bgh\s+api\b(?=[^\n;|]*?(?:(?:-X|--method)\s*['\"]?(?:POST|PATCH|PUT|DELETE)\b"
    r"|\s(?:-f|-F|--field|--raw-field|--input)\s))(?![^\n;|]*?(?:-X|--method)\s*['\"]?GET\b)"
    r"[^\n;|]*?\b(pulls|issues)\b"
)
MUTATORS = {
    "pr": re.compile(r"\bgh\s+pr\s+(?:edit|merge|close|reopen|ready|comment|review|lock|unlock)\b"),
    "issue": re.compile(r"\bgh\s+issue\s+(?:edit|close|reopen|comment|delete|lock|unlock|transfer|pin|unpin)\b"),
    "run": re.compile(r"\bgh\s+run\s+(?:cancel|rerun|delete)\b"),
    "task": re.compile(
        r"\binvoker-cli\s+(?:retry-tasks?|retry|resume|delete|delete-all|cancel\w*|set-\w+|update\w*|"
        r"approve\w*|reject\w*|reroute\w*|route\w*|assign\w*)\b"
        r"|\binvoker-ui\b[^\n|;]*?\bset\s+task\b"
    ),
    "workflow": re.compile(r"\binvoker-cli\s+(?:retry|resume|delete|delete-all|cancel\w*)\b"),
}


def stage_mutates(stage: str, noun: str) -> bool:
    pattern = MUTATORS.get(noun)
    return bool(pattern and pattern.search(stage))


def has_mutator(command: str, noun: str) -> bool:
    pattern = MUTATORS.get(noun)
    if pattern and pattern.search(command):
        return True
    if noun in {"pr", "issue"}:
        for match in GH_WRITE_API_RE.finditer(command):
            if noun == "issue" or match.group(1) in {"pulls", "issues"}:
                return True
    forms = noun_forms(noun)
    return bool(re.search(r"(?i)\b(?:update\s+(?:" + forms + r")\s+set|delete\s+from\s+(?:" + forms + r"))\b", command))


def retry_tasks_filters(command: str) -> list[ScopedFilter]:
    filters = []
    for pipeline in split_pipelines(command):
        for stage in pipeline.stages:
            if RETRY_TASKS_RE.search(stage) and "--dry-run" not in stage:
                found = _flag_filter(stage, "task", ("--status",))
                if found:
                    filters.append(found)
    return filters


def scoped_mutation_filters(command: str) -> list[ScopedFilter]:
    if not command or not STATUS_HINT_RE.search(command):
        return []
    filters = list(sql_filters(command))
    filters.extend(retry_tasks_filters(command))
    for found, feeds in cli_filters(command):
        if feeds and has_mutator(command, found.noun):
            filters.append(found)
    return _dedupe(filters)


def _strip_quoted(text: str) -> str:
    text = FENCE_RE.sub(" ", text)
    text = BLOCKQUOTE_RE.sub(" ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    text = DOUBLE_QUOTED_RE.sub(" ", text)
    if len(text) > LONG_TURN_CHARS:
        text = text[:EDGE_CHARS] + "\n" + text[-EDGE_CHARS:]
    return text


def _sentences(text: str) -> list[tuple[str, bool]]:
    out = []
    for match in re.finditer(r"[^.!?\n]+[.!?]*", text):
        sentence = match.group(0).strip()
        if not sentence:
            continue
        words = re.findall(r"[a-z']+", sentence.lower())
        while words and words[0] in LEADING_FILLERS:
            words.pop(0)
        is_state_question = sentence.endswith("?") and bool(words) and words[0] in STATE_QUESTION_OPENERS
        out.append((sentence, is_state_question))
    return out


def _phrase_re(noun: str) -> re.Pattern[str]:
    return re.compile(
        r"(?i)(?<![\w-])(?P<quant>" + QUANTIFIER + r")\s+" + DETERMINER
        + r"(?P<mods>(?:[\w'-]+\s+){0,3}?)(?P<noun>" + noun_forms(noun) + r")(?![\w-])"
    )


def _subset_re(noun: str) -> re.Pattern[str]:
    vocab = "|".join(sorted((re.escape(w) for w in SUBSET_WORDS | UNIVERSES.get(noun, frozenset())), key=len, reverse=True))
    forms = noun_forms(noun)
    return re.compile(
        r"(?i)(?<![\w-])(?:" + vocab + r")(?:\s+(?:and|or|,)\s+(?:" + vocab + r"))*\s+(?:(?!(?:a|an|the)\s)[\w-]+\s+)?(?:"
        + forms + r"|ones)(?![\w-])"
        r"|(?<![\w-])(?:" + forms + r")\s+(?:that\s+are|which\s+are|in|with\s+status|still)\s+(?:" + vocab + r")(?![\w-])"
    )


@dataclass(frozen=True)
class Scope:
    kind: str
    phrase: str
    sentence: str


def scope_in_turn(text: str, noun: str) -> Scope | None:
    cleaned = _strip_quoted(text)
    phrase_re = _phrase_re(noun)
    subset_re = _subset_re(noun)
    categorical = None
    subset = None
    for sentence, is_state_question in _sentences(cleaned):
        for match in phrase_re.finditer(sentence):
            before = sentence[:match.start()].lower().rstrip()
            if re.search(r"(?:\bnot|n't)$", before):
                continue
            mods = [m.lower() for m in match.group("mods").split()]
            if any(m in PHRASE_BREAKERS for m in mods):
                continue
            vocab = SUBSET_WORDS | UNIVERSES.get(noun, frozenset())
            if any(m.strip("'") in vocab for m in mods):
                if not is_state_question and subset is None:
                    subset = Scope("subset", match.group(0), sentence)
                continue
            if categorical is None:
                categorical = Scope("categorical", match.group(0), sentence)
        if not is_state_question and subset is None:
            match = subset_re.search(sentence)
            if match:
                subset = Scope("subset", match.group(0), sentence)
    if subset:
        return subset
    return categorical


def live_scope(window: LiveWindow, noun: str) -> Scope | None:
    for text in reversed(window.turns):
        scope = scope_in_turn(text, noun)
        if scope:
            return scope if scope.kind == "categorical" else None
    return None


def human_text(entry: dict) -> str | None:
    if entry.get("type") != "user" or entry.get("isMeta") or entry.get("isCompactSummary"):
        return None
    if "toolUseResult" in entry:
        return None
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        text = content
    elif isinstance(content, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
            return None
        text = "\n".join(
            str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    else:
        return None
    stripped = text.lstrip()
    if COMMAND_WRAPPER_RE.match(stripped):
        return " ".join(m.strip() for m in COMMAND_ARGS_RE.findall(stripped))
    if stripped.lower().startswith(NON_HUMAN_PREFIXES):
        return None
    if not stripped:
        return None
    return text


def assistant_text(entry: dict) -> str:
    if entry.get("type") != "assistant":
        return ""
    message = entry.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _reverse_lines(path: str):
    size = os.path.getsize(path)
    scanned = 0
    remainder = b""
    with open(path, "rb") as handle:
        position = size
        while position > 0:
            if scanned >= MAX_SCAN_BYTES:
                raise Unreadable(f"transcript window is past the {MAX_SCAN_BYTES // (1024 * 1024)} MB scan cap")
            step = min(CHUNK_BYTES, position)
            position -= step
            handle.seek(position)
            chunk = handle.read(step) + remainder
            scanned += step
            lines = chunk.split(b"\n")
            remainder = lines.pop(0)
            for line in reversed(lines):
                yield line
        if remainder:
            yield remainder


def read_live_window(path: str, turns: int = LIVE_TURNS) -> LiveWindow:
    if not path:
        raise Unreadable("the hook payload carries no transcript_path")
    if not os.path.isfile(path):
        raise Unreadable(f"transcript {path} does not exist")
    window = LiveWindow()
    newest = True
    try:
        for raw in _reverse_lines(path):
            line = raw.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                if newest:
                    newest = False
                    continue
                raise Unreadable(f"transcript line is malformed JSON: {exc}") from exc
            newest = False
            if not isinstance(entry, dict):
                continue
            text = human_text(entry)
            if text is not None:
                window.turns.insert(0, text)
                if len(window.turns) >= turns:
                    break
                continue
            if not window.turns:
                said = assistant_text(entry)
                if said:
                    window.assistant_after.insert(0, said)
    except OSError as exc:
        raise Unreadable(f"transcript could not be read: {exc}") from exc
    if not window.turns:
        raise Unreadable("no human turn found in the transcript")
    return window


def _quote(sentence: str) -> str:
    sentence = re.sub(r"\s+", " ", sentence).strip()
    return sentence if len(sentence) <= 200 else sentence[:197] + "..."


EXITS = (
    "Do one of two things:\n"
    "  1. Drop the filter, so the command covers every {noun} there is.\n"
    "  2. Or write a line `Complete set: <why this subset is every {noun} there is>` in your reply, "
    "then re-run the same command."
)


def hit_message(scope: Scope, found: list[ScopedFilter]) -> str:
    noun = found[0].noun
    filters = "\n".join(f"  - {f.describe()}" for f in found)
    return (
        f"categorical-scope-guard: you said \"{_quote(scope.sentence)}\". "
        f"\"{scope.phrase.strip()}\" names every {noun}, and this command narrows {noun}s by a status filter:\n"
        f"{filters}\n" + EXITS.format(noun=noun)
    )


def unchecked_message(reason: str, found: list[ScopedFilter]) -> str:
    filters = "\n".join(f"  - {f.describe()}" for f in found)
    noun = found[0].noun if found else "item"
    return (
        f"categorical-scope-guard: UNCHECKED -- {reason}. The command mutates through a status filter:\n"
        f"{filters}\n"
        "The hook blocks what it could not classify rather than pass it. "
        + EXITS.format(noun=noun)
    )


def decide(command: str, window_loader) -> Verdict:
    try:
        found = scoped_mutation_filters(command)
    except Exception as exc:
        print(f"catstack-hook-error categorical-scope-guard: {type(exc).__name__}: {exc}", file=sys.stderr)
        return Verdict(UNCHECKED, (
            f"categorical-scope-guard: UNCHECKED -- the command parser failed ({exc!r}) on a command that "
            "mentions a status or state. Blocked rather than passed; drop the status filter or rephrase the command."
        ))
    if not found:
        return Verdict(CLEAN)
    try:
        window = window_loader()
    except Unreadable as exc:
        return Verdict(UNCHECKED, unchecked_message(f"could not read the live human turn ({exc})", found))
    if any(COMPLETE_SET_RE.search(text) for text in window.assistant_after):
        return Verdict(CLEAN)
    hits: dict[str, tuple[Scope, list[ScopedFilter]]] = {}
    unreadable: list[tuple[Scope, ScopedFilter]] = []
    for item in found:
        scope = live_scope(window, item.noun)
        if scope is None or item.is_complete():
            continue
        if not item.readable:
            unreadable.append((scope, item))
            continue
        hits.setdefault(item.noun, (scope, []))[1].append(item)
    if unreadable:
        scope, _ = unreadable[0]
        return Verdict(UNCHECKED, unchecked_message(
            f"you said \"{_quote(scope.sentence)}\", and the filter values below could not be read",
            [item for _, item in unreadable] + [f for _, fs in hits.values() for f in fs],
        ))
    if hits:
        return Verdict(HIT, "\n\n".join(hit_message(scope, fs) for scope, fs in hits.values()))
    return Verdict(CLEAN)


def decide_payload(payload: dict) -> Verdict:
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return Verdict(CLEAN)
    path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    return decide(command, lambda: read_live_window(path if isinstance(path, str) else ""))
