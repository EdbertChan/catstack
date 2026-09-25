#!/usr/bin/env python3
"""Token-spend, thrash, and model-tier audit across coding-agent tools.

Usage:
    token_audit.py claude <path-to-session.jsonl>
    token_audit.py claude <path-to-session.jsonl> --out /tmp/audit.json
    token_audit.py claude <path-to-session.jsonl> --no-subagents
    token_audit.py claude <path-to-session.jsonl> --judge
    token_audit.py codex  <path-to-rollout.jsonl>
    token_audit.py codex  <path-to-rollout.jsonl> --out /tmp/audit.json
    token_audit.py omp    <path-to-omp-session.jsonl>
    token_audit.py cursor <path-to-agent-transcript.jsonl>
    token_audit.py remotes                 # list configured remote targets (names only)

With --out (claude, omp, and codex), write a JSON report to that path and
print a short summary on stdout. Claude/OMP/Codex all include named yes/no
flags (frustration-signals, intervention-must-automate, brevity-follow-ups,
self-retraction).
The human-input flags report unchecked when no human text can be classified.
Without --out, print the full prose report (legacy default).

Claude mode also loads the session's Task-tool subagent transcripts
(<session-dir>/subagents/agent-*.jsonl) and attributes their tokens and
thrash to the parent session under a `subagents` section: they are the
parent's delegated work, not separate sessions. A subagent's first
role=user record is the parent's instruction, so it never feeds the
human-only frustration / intervention-must-automate flags. --no-subagents
opts out.

All four tools log locally as JSONL, but only Claude Code, Codex, and OMP
embed per-turn token usage. OMP (~/.omp/agent/sessions/**/*.jsonl) is the
richest of the three: each assistant message carries usage.input/output/
cacheRead/cacheWrite plus an already-computed usage.cost.{input,output,
cacheRead,total} in dollars - no pricing table needed to get real $ figures
out of an OMP session. OMP mode also does real thrash detection (redundant
reads, tool errors), not just cost summation - tool calls are `toolCall`
content blocks (name + arguments) on assistant messages, and results are
separate `toolResult`-role messages carrying `isError`; `read`/`write` name
the file in `arguments.path`, `edit` embeds it in an apple-patch header
inside `arguments.input` (`[/path/to/file.ts#anchor]`) - all verified
against real sessions, not guessed. Cursor's local agent-transcripts (~/.cursor/projects/*/
agent-transcripts/*/*.jsonl) carry no token/usage/model fields at all -
verified by scanning real transcripts, not assumed. So `cursor` mode only
reports thrash (redundant tool calls), never token/cost numbers, and says so.

--judge (claude, omp, codex, cursor) asks the llm-judge, one call per human
message, whether the person restated a rule that already exists (the
`restated-rule` phrase dictionary). Without it that check is unchecked, so
intervention-must-automate reports unchecked instead of a clean no.

Apart from --judge, this script only counts and flags mechanically. It does not judge whether a
flagged item was actually avoidable, and it never SSHes anywhere - `remotes`
just reads target *names* out of ~/.invoker/config.json (if present) so the
reflect Cost lens knows what remote scanning would be possible; actually
running an audit against a remote host is a separate, explicitly-confirmed
step outside this script.
"""
import bisect, json, sys, hashlib, os, re, time
from datetime import datetime
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import transcript_provenance

# Published per-token list prices, $/MTok (see claude-api skill, cached 2026-06-24).
# Cache-read tokens are billed at ~0.1x the model's own input price.
PRICING = {
    "claude-fable-5-1": {"input": 10.00, "output": 50.00, "cache_read": 0.25},
    "claude-opus-5": {"input": 5.00, "output": 25.00, "cache_read": 0.50},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00, "cache_read": 0.20},
    "claude-haiku-4-5": {"input": 1.00, "output": 5.00, "cache_read": 0.10},
}

SECRET_RE = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"(?:sk-proj-|sk-ant-|sk-(?!proj-|ant-))[A-Za-z0-9_-]{20,}|"
    r"sk_[A-Za-z0-9]{20,}|"
    r"(?:ghp_|gho_)[A-Za-z0-9]{20,}|"
    r"github_pat_[A-Za-z0-9_]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"xox[abp]-[A-Za-z0-9-]{20,}"
    r")(?![A-Za-z0-9_-])"
)


def redact_secrets(text):
    return SECRET_RE.sub("[REDACTED-KEY]", text)


def model_tier_savings(simple_turn_output_tokens, from_model="claude-sonnet-5", to_model="claude-haiku-4-5"):
    """Deterministic backtest: what would it have cost to run the flagged
    lookup-only turns' OUTPUT tokens on a cheaper model instead, at published
    list prices. Input/cache-read tokens for those turns aren't tracked at
    per-turn granularity, so this only prices the output side - a lower bound
    on total savings, not the full figure. Returns (actual_$, cheaper_$, saved_$)."""
    actual = simple_turn_output_tokens * PRICING[from_model]["output"] / 1_000_000
    cheaper = simple_turn_output_tokens * PRICING[to_model]["output"] / 1_000_000
    return actual, cheaper, actual - cheaper

def sig(name, inp):
    s = json.dumps(inp, sort_keys=True)[:2000]
    return hashlib.sha1(s.encode()).hexdigest(), s

# A Bash command matching this counts as "the agent checked its own work" -
# the fast-feedback-loop signal used by the two detectors below. Heuristic
# only: it flags the shape of a verification attempt, not whether the right
# check ran or whether it passed.
VERIFY_RE = re.compile(
    r"\b(pytest|jest|vitest|mocha|rspec|unittest|go\s+(test|vet|build)|"
    r"cargo\s+(test|check|build)|mvn\s+\S*test|gradle\s+\S*test|make\s+test|"
    r"(npm|pnpm|yarn)\s+(run\s+)?test|tsc\b|typecheck|eslint|ruff|flake8|pylint)\b",
    re.I,
)

# A Bash command directly interpreting/running the just-edited file (no
# test framework involved) also counts as verification for a one-off
# script - e.g. `python3 foo.py`, `node foo.js`, `./foo.sh`. VERIFY_RE alone
# missed this: confirmed against a real session where a 9-edit streak on
# claude_session_cost.py was flagged even though every edit cluster was
# immediately followed by `python3 claude_session_cost.py ...` and the
# agent read its real output before editing again - the feedback loop was
# in use, the detector just didn't recognize the shape. Unlike VERIFY_RE
# (which resets every file's streak on any match), this only counts as
# verification for the specific file(s) actually being run.
DIRECT_RUN_RE = re.compile(
    r"(?:\b(?:python3?|node|ruby|bash|sh|perl)\s+\S*?([\w.-]+\.\w+)\b|"
    r"\./([\w./-]*[\w.-]+\.\w+)\b)"
)


def _direct_run_targets(command):
    """Basenames of any file(s) a Bash command directly executes, e.g.
    'python3 tools/claude_session_cost.py --top 5' -> {'claude_session_cost.py'},
    './run-all.sh' -> {'run-all.sh'}. Two alternatives because a bare `./foo.sh`
    has no space between the `./` prefix and the filename, unlike an
    interpreter invocation - verified against both real shapes, not merged
    into one pattern that silently missed the no-space case."""
    hits = set()
    for m in DIRECT_RUN_RE.finditer(command or ""):
        name = m.group(1) or m.group(2)
        if name:
            hits.add(os.path.basename(name))
    return hits


# Frustration signals: mechanical detectors for the moments the user's tone
# spiked. Added after a real session where 13/56 user messages were all-caps
# demands, profanity, or verbatim repeats — and the reflect synthesis ranked
# root causes by frustration caused, not tokens burned. This is the feed for
# the Frustration lens (see references/lenses.md); the lens gets this output,
# never the raw JSONL.
FRUSTRATION_PATTERNS = [
    ("profanity", re.compile(r"\b(fuck\w*|wtf|shit\w*|goddamn|dammit|damn it|stupid)\b", re.I)),
    ("told-you", re.compile(r"\bi (already |just )?told you\b|\bi asked you not\b|\bi already said\b", re.I)),
    ("waiting", re.compile(r"\b(i am|i'?m) (still )?waiting\b|\btime constraint\b|\bhurry up\b", re.I)),
    ("accusation", re.compile(r"\byou('?re| are) (thrashing|not listening|ignoring)\b|\bignoring me\b", re.I)),
    ("agent-blame", re.compile(r"\byou (fucked up|messed up|broke)\b|\byou('?ve| have) (fucked|messed) up\b", re.I)),
    ("multi-question-marks", re.compile(r"\?\?\?+")),
    ("restated-ask", re.compile(
        r"\ball i (asked|wanted|said)\b"
        r"|\bthat'?s not what i (asked|said)\b"
        r"|\bi only asked\b"
        r"|\bmy (original|actual) (ask|question) was\b", re.I)),
    ("proof-challenge", re.compile(
        r"\b(can|could|did|will) you /?prove[- ]?it\b"
        r"|/prove-it\b"
        r"|\bis the proof att?ach?ed\b"
        r"|\bwhere'?s the proof\b"
        r"|\bprove (to me )?that (it|this|that|the|#?\d)", re.I)),
    ("cheap-way-out", re.compile(r"\bcheap way out\b|\bwhy would you\b|\bbogus\b|\bdidn'?t (even )?(work|run)\b|\bthat'?s (weird|wierd)\b|\bstraight up\b", re.I)),
    ("explicit-invocation", re.compile(r"(?:^|\s)/(?:automate-me|reflect|thrash)\b", re.I)),
    ("undo-challenge", re.compile(r"\bwhy did .{0,80}\brevert|\bwe need (that|it)\b", re.I)),
]

# Same-type user intervention. One correction can be cheap. Repeating the
# class (told-you / accusation / agent-blame twice, two of those kinds in
# one session, or a verbatim re-send) is the automate-me trigger. Product
# blame ("the ui is messed up") does not match agent-blame.
MIN_RESEND_GAP_SECS = 5

INTERVENTION_KINDS = frozenset({
    "told-you", "accusation", "agent-blame", "restated-ask", "proof-challenge",
    "cheap-way-out", "explicit-invocation", "restated-after-rejection", "restated-rule",
})
RESTATED_RULE_CHECKER = "restated-rule"
RESTATED_RULE_TIMEOUT_SECONDS = 180
RESTATED_RULE_WORKERS = 8
LLM_JUDGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))),
    "hooks", "llm-judge",
)
CLAUDE_REJECTED_TOOL_RESULT = "User rejected tool use"
CLAUDE_REJECTED_DENIAL_KIND = "user-rejected"
INTERVENTION_COMMAND_NAMES = frozenset({"/automate-me", "/thrash"})
BREVITY_COMMAND_NAMES = frozenset({"/diu"})
REVIEW_COMMAND_NAMES = frozenset({"/reflect"})
BREVITY_TRIGGER_TEXTS = frozenset({"eli5", "eli 5"})
BREVITY_HOOK_NAME = "diu-stop"
_STOP_HOOK_BLOCK_PREFIX = "Stop hook feedback"
_STOP_HOOK_SCRIPT_RE = re.compile(r"([A-Za-z0-9_-]+)/[a-z0-9_]+\.py")
_CLAUDE_COMMAND_NAME_RE = re.compile(r"<command-name>\s*(?P<name>[^<]+?)\s*</command-name>", re.DOTALL)

# function_call_output / custom_tool_call_output payloads carry their exit
# status as prose ("Process exited with code 1" for exec_command,
# "Exit code: 1" for apply_patch) - verified against a real rollout file,
# not guessed. No structured is_error field exists on this transcript shape.
_CODEX_EXIT_CODE_RE = re.compile(r"(?:Process exited with code|Exit code:)\s*(-?\d+)")
_CODEX_CMD_RE = re.compile(r'"cmd"\s*:\s*"((?:\\.|[^"\\])*)"')
_PATCH_PATH_RE = re.compile(r"\*\*\* (?:Update|Add|Delete) File: ([^\\\r\n\"]+)")


def _codex_output_is_error(text):
    m = _CODEX_EXIT_CODE_RE.search(text or "")
    if not m:
        return False
    try:
        return int(m.group(1)) != 0
    except ValueError:
        return False


def _decode_json_string(value):
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value


def _codex_bash_command(payload):
    name = str(payload.get("name") or "")
    raw = payload.get("input")
    if isinstance(raw, dict):
        return raw.get("cmd") or raw.get("command")
    if not isinstance(raw, str):
        return None
    if name in {"exec_command", "functions.exec_command"}:
        match = _CODEX_CMD_RE.search(raw)
        return _decode_json_string(match.group(1)) if match else raw
    if name == "exec" and "exec_command" in raw:
        match = _CODEX_CMD_RE.search(raw)
        return _decode_json_string(match.group(1)) if match else raw
    return None


def _codex_patch_paths(payload):
    name = str(payload.get("name") or "")
    raw = payload.get("input")
    if isinstance(raw, dict):
        raw = raw.get("patch") or raw.get("input") or raw.get("cmd") or ""
    if not isinstance(raw, str):
        return []
    if "apply_patch" not in raw and name not in {"apply_patch", "functions.apply_patch"}:
        return []
    return [path.strip() for path in _PATCH_PATH_RE.findall(raw)]


def _codex_message_text(payload):
    parts = []
    for block in payload.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") in ("input_text", "output_text", "text"):
            text = block.get("text") or ""
            if text:
                parts.append(text)
    return "\n".join(parts)


def _ts_seconds(ts):
    """ISO string (claude/omp both use ISO with Z) -> epoch seconds, else None."""
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _is_allcaps(text):
    letters = [c for c in text if c.isalpha()]
    if len(letters) < 12 or len(text) <= 20:
        return False
    return sum(c.isupper() for c in letters) / len(letters) > 0.6


def _is_api_error_line(row):
    """A turn that never produced a response. Claude writes these as an
    assistant row carrying isApiErrorMessage plus an `error` code (observed
    shape: model "<synthetic>", zero usage, text "Login expired - Please run
    /login"), which is why an ordinary assistant row cannot stand in for it."""
    if not isinstance(row, dict) or row.get("type") != "assistant":
        return False
    return bool(row.get("isApiErrorMessage") or row.get("error"))


def _claude_queued_human_prompt(row):
    if row.get("type") != "attachment" or row.get("agentId") or row.get("isSidechain"):
        return None
    attachment = row.get("attachment")
    if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
        return None
    if (attachment.get("origin") or {}).get("kind") != "human":
        return None
    prompt = attachment.get("prompt")
    return prompt if isinstance(prompt, str) else None


def _claude_human_texts(path, rows):
    if "/subagents/" in path.replace("\\", "/"):
        return
    rows = rows if isinstance(rows, list) else list(rows)
    last_user_index_by_text = {}
    for index, row in enumerate(rows):
        message = row.get("message") if row.get("type") == "user" else None
        if isinstance(message, dict):
            last_user_index_by_text[
                transcript_provenance._text_from_content(message.get("content")).strip()
            ] = index
    for index, row in enumerate(rows):
        queued = _claude_queued_human_prompt(row)
        if queued is not None:
            if last_user_index_by_text.get(queued.strip(), -1) <= index:
                yield queued
            continue
        if row.get("type") != "user" or row.get("agentId") or row.get("isSidechain"):
            continue
        message = row.get("message")
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        text = transcript_provenance._text_from_content(message.get("content"))
        if row.get("isMeta") or text.lstrip().startswith(_STOP_HOOK_BLOCK_PREFIX):
            continue
        yield text


def _claude_hook_block_names(path, rows):
    """Hook names from each Stop-hook block the harness injected as a user row.

    These rows are the checkers speaking, never the person, so they are read
    here and excluded from every human count."""
    names = Counter()
    if "/subagents/" in path.replace("\\", "/"):
        return names
    for row in rows:
        if row.get("type") != "user" or row.get("agentId") or row.get("isSidechain"):
            continue
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        text = transcript_provenance._text_from_content(message.get("content"))
        if not text.lstrip().startswith(_STOP_HOOK_BLOCK_PREFIX):
            continue
        for name in set(_STOP_HOOK_SCRIPT_RE.findall(text)):
            names[name] += 1
    return names


def _brevity_hook_blocks_flag(blocks, requests):
    """Times the brevity checker stopped a reply, next to the times the person
    had to ask. Both counts read the same session; only the second one means
    the checker did not do its job."""
    if blocks is None:
        return _flag(
            "brevity-hook-blocks", "unchecked", None,
            "hook blocks are not recorded in this harness's transcript",
        )
    return _flag(
        "brevity-hook-blocks", "yes" if blocks else "no", blocks,
        f"{blocks} reply/replies stopped by the brevity checker; "
        f"{requests} request(s) for a shorter reply from the person",
    )


def _claude_command_names(text):
    for match in _CLAUDE_COMMAND_NAME_RE.finditer(text):
        name = match.group("name").strip()
        if name and not name.startswith("/"):
            name = "/" + name
        yield name


def _claude_intervention_command_counts(path, rows):
    counts = Counter()
    for text in _claude_human_texts(path, rows):
        for name in _claude_command_names(text):
            if name in INTERVENTION_COMMAND_NAMES:
                counts[name] += 1
    return counts


def _is_review_command_row(row):
    if row.get("type") == "queue-operation":
        text = transcript_provenance._text_from_content(row.get("content"))
    else:
        message = row.get("message")
        text = transcript_provenance._text_from_content(
            message.get("content") if isinstance(message, dict) else None
        )
    return bool(set(_claude_command_names(text)) & REVIEW_COMMAND_NAMES)


def _claude_frustration_messages(rows, path=""):
    """Direct human messages as (index, ts, text), plus the indices of /reflect
    commands. A /reflect command is the person asking for a review; its
    arguments name the review's subject, so the tone scan skips them."""
    utterances = transcript_provenance.direct_human_claude_rows(
        rows, path, include_queue_operations=True,
    )
    msgs = [(u.index, u.timestamp, u.text) for u in utterances]
    review_indices = {u.index for u in utterances if _is_review_command_row(rows[u.index])}
    return msgs, review_indices


def _is_claude_user_rejection(row):
    if row.get("type") != "user" or row.get("agentId") or row.get("isSidechain"):
        return False
    return (
        row.get("toolDenialKind") == CLAUDE_REJECTED_DENIAL_KIND
        or row.get("toolUseResult") == CLAUDE_REJECTED_TOOL_RESULT
    )


def claude_restated_after_rejection(rows, user_msgs):
    """Human message indices that answer a rejected tool call.

    The rejection is read from the harness's typed denial fields, never from
    the tool_result prose. The counted item is the next human message after
    the rejection, so only a person's own words reach the count."""
    human_indices = sorted(idx for idx, _, text in user_msgs if isinstance(text, str) and text.strip())
    hits = {}
    for index, row in enumerate(rows):
        if not _is_claude_user_rejection(row):
            continue
        at = bisect.bisect_right(human_indices, index)
        if at < len(human_indices):
            hits[human_indices[at]] = ["restated-after-rejection"]
    return hits


def _load_restated_rule_judge():
    if LLM_JUDGE_DIR not in sys.path:
        sys.path.insert(0, LLM_JUDGE_DIR)
    import judge
    import phrases

    return judge, phrases, phrases.load(RESTATED_RULE_CHECKER)


def judge_restated_rule(user_msgs, unflagged_indices=None, enabled=False):
    """Ask the llm-judge whether each human message restates an existing rule.

    Returns {"status": "judged"|"unchecked", "hits": {index: [kind]},
    "unchecked": n, "rationale": str}. Off, unreadable, or unanswered is
    unchecked, never a clean zero."""
    candidates = [
        (idx, text) for idx, _, text in user_msgs
        if isinstance(text, str) and text.strip()
        and not (unflagged_indices and idx in unflagged_indices)
    ]
    if not enabled:
        return {
            "status": "unchecked", "hits": {}, "unchecked": len(candidates),
            "rationale": f"{RESTATED_RULE_CHECKER} not judged (run with --judge)",
        }
    try:
        judge, phrases, dictionary = _load_restated_rule_judge()
    except Exception as exc:
        print(f"token_audit: {RESTATED_RULE_CHECKER} judge could not load: {type(exc).__name__}: {exc}", file=sys.stderr)
        return {
            "status": "unchecked", "hits": {}, "unchecked": len(candidates),
            "rationale": f"{RESTATED_RULE_CHECKER} judge could not load: {type(exc).__name__}: {exc}",
        }

    def ask(item):
        idx, text = item
        result = judge.ask(phrases.prompt(dictionary, text), timeout_seconds=RESTATED_RULE_TIMEOUT_SECONDS)
        return idx, result

    hits = {}
    reasons = []
    with ThreadPoolExecutor(max_workers=RESTATED_RULE_WORKERS) as pool:
        results = list(pool.map(ask, candidates))
    for idx, result in results:
        answer = result.get("answer") if result.get("outcome") == "answered" else None
        if not isinstance(answer, dict):
            reasons.append("; ".join(
                f"{a.get('runner')}: {a.get('reason')}" for a in result.get("attempts") or []
            ) or "no runner answered")
            continue
        if answer.get("match") is True:
            hits[idx] = [RESTATED_RULE_CHECKER]
    unchecked = len(reasons)
    if unchecked:
        print(
            f"token_audit: {RESTATED_RULE_CHECKER} judge left {unchecked}/{len(candidates)} message(s) unchecked: {reasons[0]}",
            file=sys.stderr,
        )
    return {
        "status": "unchecked" if unchecked else "judged",
        "hits": hits,
        "unchecked": unchecked,
        "rationale": (
            f"{RESTATED_RULE_CHECKER} judged {len(candidates) - unchecked}/{len(candidates)} message(s), "
            f"{len(hits)} hit(s)"
            + (f"; unchecked: {reasons[0][:200]}" if unchecked else "")
        ),
    }


def _merge_kinds(*maps):
    merged = {}
    for mapping in maps:
        for idx, kinds in (mapping or {}).items():
            merged.setdefault(idx, []).extend(kinds)
    return merged


def _is_brevity_trigger_text(text):
    return text.strip().rstrip(".!?").strip().lower() in BREVITY_TRIGGER_TEXTS


def _claude_brevity_follow_ups(path, rows):
    diu_commands = eli5_only = 0
    for text in _claude_human_texts(path, rows):
        names = set(_claude_command_names(text))
        if names & BREVITY_COMMAND_NAMES:
            diu_commands += 1
        elif not names and _is_brevity_trigger_text(text):
            eli5_only += 1
    return diu_commands, eli5_only


def _brevity_follow_ups_flag(eli5_only, diu_commands=None):
    diu_text = "not recorded by this harness" if diu_commands is None else str(diu_commands)
    count = eli5_only + (diu_commands or 0)
    rationale = f"{count} request(s) for a shorter reply: /diu={diu_text} eli5-only={eli5_only}"
    if diu_commands is None and not count:
        return _flag(
            "brevity-follow-ups", "unchecked", None,
            f"{rationale}; a zero here is not a clean count without the /diu command field",
        )
    return _flag("brevity-follow-ups", "yes" if count else "no", count, rationale)


def _has_index_between(sorted_indices, prev_idx, curr_idx):
    """True if any element of sorted_indices falls strictly between prev_idx
    and curr_idx (exclusive on both ends). bisect keeps this O(log n) on
    large sessions."""
    lo = bisect.bisect_right(sorted_indices, prev_idx)
    return lo < len(sorted_indices) and sorted_indices[lo] < curr_idx


def frustration_signals(user_msgs, interruptions=0, failed_turn_indices=None, unflagged_indices=None,
                        extra_kinds=None, judge=False):
    """user_msgs: [(ordinal, iso_timestamp_or_None, text)] — HUMAN-authored
    messages only (never tool_results, never interruption markers).
    Returns flagged messages with their signal kinds, plus a verbatim-repeat
    check: the same normalized text re-sent within 10 minutes is the single
    strongest frustration signal (the user re-sent it because nothing visibly
    changed). `interruptions` is counted by the caller (tool-specific shape).

    `failed_turn_indices` (optional): JSONL line indices carrying positive
    evidence that a turn never produced a response — an API-error line
    (OAuth 401, rate limit, network). When one of those sits between two
    identical sends, the re-send is a retry, not frustration, and
    verbatim-repeat is suppressed. Absence of an assistant reply is NOT
    such evidence: an unanswered restatement is the frustration signal
    itself, and Claude writes auth failures as their own assistant line.

    `unflagged_indices` (optional): messages that count toward the total but
    are never flagged, such as a /reflect command's arguments.

    `extra_kinds` (optional): {index: [kind]} from typed transcript fields,
    such as restated-after-rejection. `judge` asks the llm-judge for the
    restated-rule kind; off, that check is recorded as unchecked.
    """
    user_msgs = [(idx, ts, text) for idx, ts, text in user_msgs
                 if isinstance(text, str) and text.strip()]
    restated_rule = judge_restated_rule(user_msgs, unflagged_indices, enabled=judge)
    restated_rule_summary = {k: restated_rule[k] for k in ("status", "unchecked", "rationale")}
    if not user_msgs:
        return {
            "count": None,
            "n_user_messages": 0,
            "interruptions": interruptions,
            "kinds": {},
            "peak_window": None,
            "flagged": [],
            "rationale": "no classifiable human rows; human-input checks could not run",
            "restated_rule": restated_rule_summary,
        }
    typed_kinds = _merge_kinds(extra_kinds, restated_rule["hits"])
    flagged = []
    seen = []
    _failed = sorted(failed_turn_indices) if failed_turn_indices else None
    for idx, ts, text in user_msgs:
        t = (text or "").strip()
        if not t:
            continue
        if unflagged_indices and idx in unflagged_indices:
            continue
        kinds = list(typed_kinds.get(idx, []))
        if _is_allcaps(t):
            kinds.append("allcaps")
        for kind, rx in FRUSTRATION_PATTERNS:
            if rx.search(t):
                kinds.append(kind)
        secs = _ts_seconds(ts)
        norm = re.sub(r"\s+", " ", t).casefold()
        if len(norm) >= 12:
            for prev_secs, prev_norm, prev_idx in seen:
                gap = None if (secs is None or prev_secs is None) else secs - prev_secs
                if prev_norm == norm and (gap is None or MIN_RESEND_GAP_SECS <= gap <= 600):
                    if _failed is not None and _has_index_between(_failed, prev_idx, idx):
                        continue
                    kinds.append("verbatim-repeat")
                    break
            seen.append((secs, norm, idx))
        if kinds:
            flagged.append({
                "index": idx,
                "ts": ts,
                "kinds": sorted(set(kinds)),
                "excerpt": redact_secrets(t)[:100],
            })
    peak = None
    stamped = [(f["ts"], _ts_seconds(f["ts"])) for f in flagged if _ts_seconds(f["ts"]) is not None]
    if stamped:
        stamped.sort(key=lambda x: x[1])
        peak = [stamped[0][0], stamped[-1][0]]
    kind_counts = Counter(k for f in flagged for k in f["kinds"])
    return {
        "count": len(flagged),
        "n_user_messages": len(user_msgs),
        "interruptions": interruptions,
        "kinds": dict(kind_counts),
        "peak_window": peak,
        "flagged": flagged,
        "restated_rule": restated_rule_summary,
    }


def intervention_must_automate(frustration):
    """Same-type complaint / forced iteration → reflect FAIL and must
    invoke automate-me. One told-you is a failure for the pass; two of
    the same class, two intervention kinds, or a verbatim re-send is the
    automate trigger. Returns (yes, count, rationale); yes and count are
    None when no human text could be classified. yes alone is None when no
    repeat was found but the restated-rule judge did not answer, because a
    check that could not run is not a clean no."""
    command_count = frustration.get("intervention_command_count", 0)
    if frustration.get("count") is None and not command_count:
        return None, None, frustration["rationale"]
    kinds = frustration.get("kinds") or {}
    reasons = []
    if command_count >= 2:
        reasons.append(f"intervention-commandsx{command_count}")
    if kinds.get("verbatim-repeat", 0):
        reasons.append("verbatim-repeat")
    for k in sorted(INTERVENTION_KINDS):
        n = kinds.get(k, 0)
        if n >= 2:
            reasons.append(f"{k}x{n}")
    distinct = sorted(k for k in INTERVENTION_KINDS if kinds.get(k, 0))
    if len(distinct) >= 2:
        reasons.append("+".join(distinct))
    yes = bool(reasons)
    count = (
        sum(kinds.get(k, 0) for k in INTERVENTION_KINDS)
        + kinds.get("verbatim-repeat", 0)
        + command_count
    )
    restated_rule = frustration.get("restated_rule") or {
        "status": "unchecked", "rationale": f"{RESTATED_RULE_CHECKER} not recorded",
    }
    if yes:
        return True, count, (
            "same-type complaint / iteration: " + ", ".join(reasons)
            + f"; {restated_rule['rationale']}"
        )
    rationale = (
        f"no repeated intervention class (intervention commands={command_count}; "
        f"one correction is not automate-me); {restated_rule['rationale']}"
    )
    if restated_rule["status"] != "judged":
        return None, count, rationale
    return False, count, rationale


def _omp_user_text(row):
    if row.get("type") != "message":
        return ""
    msg = row.get("message") or {}
    if msg.get("role") != "user":
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(
        b.get("text", "") for b in (content or [])
        if isinstance(b, dict) and b.get("type") == "text"
    )


def replay_frustration(rows):
    """Rows detector for scripts/test/backtest_detector.py: every human message of a
    Claude or OMP transcript with its frustration kinds, from the same
    human-message filter and frustration_signals() the audit uses."""
    failed_turn_indices = []
    omp_msgs = []

    claude_rows = []
    for position, (_, row) in enumerate(rows):
        if _is_api_error_line(row):
            failed_turn_indices.append(position)
        text = _omp_user_text(row)
        if text.strip():
            omp_msgs.append((position, row.get("timestamp"), text))
        claude_rows.append(row)

    claude_msgs, review_indices = _claude_frustration_messages(claude_rows)
    user_msgs = claude_msgs + omp_msgs
    frustration = frustration_signals(
        user_msgs, failed_turn_indices=failed_turn_indices, unflagged_indices=review_indices,
    )
    kinds = {f["index"]: f["kinds"] for f in frustration["flagged"]}
    for index, _, text in user_msgs:
        if text.strip():
            yield index, text, kinds.get(index)


def self_retraction_hits(assistant_texts):
    """Assistant-only first-person wrong-check admissions, scanned offline.

    The wrong-check-reflect hook asks the background judge instead of matching
    phrasings; this miner keeps a text scan so historical transcripts stay
    minable without model calls. Fail-open on import/scan errors.
    """
    try:
        import self_retraction_scan

        return [redact_secrets(hit) for hit in self_retraction_scan.scan_assistant_texts(assistant_texts)]
    except Exception:
        return []


def _self_retraction_flag(hits):
    return _flag(
        "self-retraction",
        "yes" if hits else "no",
        len(hits),
        (
            f"{len(hits)} assistant wrong-check admission(s): "
            + "; ".join(repr(h) for h in hits[:5])
            if hits
            else "no first-person wrong-check admissions in assistant text"
        ),
    )


def _frustration_flags(frustration):
    yes, count, rationale = intervention_must_automate(frustration)
    command_count = frustration.get("intervention_command_count", 0)
    command_counts = frustration.get("intervention_commands") or {}
    if yes is None and count is None:
        unchecked_rationale = (
            f"{rationale}; intervention_commands={command_count} {command_counts}"
        )
        return [
            _flag("frustration-signals", "unchecked", None, unchecked_rationale),
            _flag("intervention-must-automate", "unchecked", None, unchecked_rationale),
        ]
    frustration_value = (
        "unchecked" if frustration["count"] is None
        else ("yes" if frustration["count"] else "no")
    )
    frustration_count = frustration["count"]
    if frustration["count"] is None:
        frustration_rationale = (
            f"{frustration['rationale']}; intervention_commands={command_count} {command_counts}"
        )
    else:
        frustration_rationale = (
            f"{frustration['count']}/{frustration['n_user_messages']} user messages flagged "
            f"({frustration['kinds']}; intervention_commands={command_count} {command_counts}); "
            f"interruptions={frustration['interruptions']}"
            + (f"; peak window {frustration['peak_window'][0]} -> {frustration['peak_window'][1]}"
               if frustration["peak_window"] else "")
        )
    return [
        _flag(
            "frustration-signals",
            frustration_value,
            frustration_count,
            frustration_rationale,
        ),
        _flag(
            "intervention-must-automate",
            "unchecked" if yes is None else ("yes" if yes else "no"),
            None if yes is None else count,
            rationale,
        ),
    ]



def _print_frustration(frustration, *, details=True):
    flags = _frustration_flags(frustration)
    if frustration["count"] is None:
        print(f"{flags[0]['name']}: unchecked (count=None) {flags[0]['rationale']}")
        print(f"{flags[1]['name']}: {flags[1]['value']} (count={flags[1]['count']}) {flags[1]['rationale']}")
        return
    if details:
        print("-- frustration signals (user tone spikes; feed for the Frustration lens) --")
        for f_ in frustration["flagged"]:
            print(f"  [{f_['index']}] {f_['ts']} {f_['kinds']}: {f_['excerpt']!r}")
    command_count = frustration.get("intervention_command_count", 0)
    command_counts = frustration.get("intervention_commands") or {}
    summary = (
        f"frustration-flagged user messages: {frustration['count']}/{frustration['n_user_messages']} "
        f"(kinds={frustration['kinds']}; intervention_commands={command_count} {command_counts})"
    )
    if details:
        summary += f"; interruptions: {frustration['interruptions']}"
        if frustration["peak_window"]:
            summary += f"; peak window {frustration['peak_window'][0]} -> {frustration['peak_window'][1]}"
    print(summary)
    print(f"{flags[1]['name']}: {flags[1]['value']} (count={flags[1]['count']}) {flags[1]['rationale']}")


def read_jsonl(path):
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _flag(name, value, count, rationale):
    """One named yes/no/unchecked check with a rationale — same shape as an MLflow judge
    Feedback, without depending on MLflow."""
    return {"name": name, "value": value, "count": count, "rationale": rationale}


def _claude_tool_path(inp):
    """Read/Edit/Write take `file_path`, but some tool variants use plain
    `path` — normalize so aliasing can't hide a redundant read or split an
    edit streak across two names for the same file (ported from PR #1)."""
    return inp.get("file_path") or inp.get("path")


SUBAGENT_THRASH_FLAGS = (
    "redundant-reads",
    "recurring-failure-signatures",
    "no-verify-edit-streak",
    "self-retraction",
)


def _subagent_transcripts(path):
    """Sorted agent-*.jsonl paths under the session's subagents/ dir, via
    subagent_cost.resolve_subagents_dir so the two scripts cannot drift on
    where a session's fan-out lives. A subagent transcript itself has no
    children: returns [] for any path already under /subagents/."""
    if "/subagents/" in path.replace("\\", "/"):
        return []
    import subagent_cost
    subagents_dir = subagent_cost.resolve_subagents_dir(path)
    if not os.path.isdir(subagents_dir):
        return []
    return sorted(
        os.path.join(subagents_dir, f)
        for f in os.listdir(subagents_dir)
        if f.startswith("agent-") and f.endswith(".jsonl")
    )


def audit_subagents(path, audit_started_at=None):
    """Audit every subagent transcript of the session at `path` and fold the
    numbers into one section attributed to that parent session. Human
    frustration / intervention flags are deliberately not aggregated: the
    only role=user rows in a subagent file are the parent's instructions,
    and transcript_provenance already marks them provenance=subagent, so
    `human_messages` here must stay 0."""
    import subagent_cost
    from io import StringIO
    from contextlib import redirect_stdout

    files = _subagent_transcripts(path)
    totals = {"input": 0, "output": 0, "cache_read": 0, "cache_creation": 0, "total": 0}
    thrash = {
        "redundant_reads": 0,
        "redundant_read_files": [],
        "tool_errors": 0,
        "recurring_failure_signatures": 0,
        "recurring_failure_details": [],
        "longest_edit_streak_no_verify": 0,
        "self_retraction": 0,
        "by_agent": {},
    }
    rows = []
    human_messages = 0
    if audit_started_at is not None:
        active_files = [f for f in files if os.path.getmtime(f) >= audit_started_at]
        if active_files:
            return {
                "count": len(files),
                "files": files,
                "unchecked": True,
                "rationale": "subagent transcript file was modified at or after audit start; totals may be partial",
                "active_files": active_files,
                "totals": totals,
                "top": rows,
                "thrash": thrash,
                "human_messages": human_messages,
            }
    for agent_path in files:
        with redirect_stdout(StringIO()):
            stats = audit_claude(agent_path, include_subagents=False)
        if not stats:
            continue
        fname = os.path.basename(agent_path)
        meta = subagent_cost.load_meta(agent_path)
        for key in ("input", "output", "cache_read", "cache_creation", "total"):
            totals[key] += stats[key]
        human_messages += stats["frustration"]["n_user_messages"]
        flags = {f["name"]: f for f in stats["flags"]}
        fired = [name for name in SUBAGENT_THRASH_FLAGS if flags.get(name, {}).get("value") == "yes"]
        if fired:
            thrash["by_agent"][fname] = fired
        thrash["redundant_reads"] += flags["redundant-reads"]["count"] or 0
        for fp in stats.get("redundant_read_files", []):
            thrash["redundant_read_files"].append(f"{fname}:{fp}")
        thrash["tool_errors"] += stats["n_errors"]
        thrash["recurring_failure_signatures"] += stats["n_recurring_failures"]
        for detail in stats.get("recurring_failure_details", []):
            thrash["recurring_failure_details"].append(
                {"agent": fname, "tool": detail["tool"], "signature": detail["signature"],
                 "occurrences": detail["occurrences"]}
            )
        thrash["longest_edit_streak_no_verify"] = max(
            thrash["longest_edit_streak_no_verify"], stats["longest_edit_streak_no_verify"]
        )
        thrash["self_retraction"] += len(stats["self_retraction"])
        rows.append({
            "file": fname,
            "path": agent_path,
            "description": meta.get("description", "(no meta.json description)"),
            "total": stats["total"],
            "n_assistant": stats["n_assistant"],
            "n_errors": stats["n_errors"],
            "thrash_flags": fired,
        })
    rows.sort(key=lambda r: r["total"], reverse=True)
    return {
        "count": len(rows),
        "files": files,
        "unchecked": False,
        "totals": totals,
        "top": rows[:5],
        "thrash": thrash,
        "human_messages": human_messages,
    }


def _subagent_thrash_flag(subagents):
    if subagents and subagents.get("unchecked"):
        return _flag("subagent-thrash", "unchecked", None, subagents["rationale"])
    n = len(subagents["thrash"]["by_agent"]) if subagents else 0
    return _flag(
        "subagent-thrash",
        "yes" if n else "no",
        n,
        (
            f"{n}/{subagents['count']} subagent transcript(s) with a thrash flag: "
            + "; ".join(f"{k}={v}" for k, v in sorted(subagents["thrash"]["by_agent"].items()))
            if n
            else (
                f"no thrash flags across {subagents['count']} subagent transcript(s)"
                if subagents else "subagents not loaded (--no-subagents)"
            )
        ),
    )


def audit_claude(path, out_path=None, include_subagents=True, judge=False):
    """Token and thrash audit of one Claude transcript.

    Claude Code writes one JSONL line per content block (thinking/text/
    tool_use), but every block belonging to the same message.id carries a
    usage snapshot for that whole message. Summing every line
    triple/quadruple-counts tokens - verified against real transcripts, where
    299 raw assistant lines turned out to be only 141 unique messages. Dedupe
    by message.id before adding to any token total; still walk every line for
    tool_use extraction, since each line's content block is genuinely
    distinct.

    The snapshot is not always the same on every line: streamed lines can
    carry cumulative usage that grows (subagent transcripts' first line held
    ~5% of the real output). Keep the per-field maximum across a message's
    lines - not the first line, and not the sum, since the lines are
    cumulative. msg_usage maps a message id to that per-field maximum in
    first-seen order, and msg_first_seq to the tool_use seq at which the
    message first appeared.
    """
    audit_started_at = time.time()
    USAGE_FIELDS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    lines = read_jsonl(path)
    intervention_commands = _claude_intervention_command_counts(path, lines)
    brevity_diu_commands, brevity_eli5_only = _claude_brevity_follow_ups(path, lines)
    brevity_hook_blocks = _claude_hook_block_names(path, lines)[BREVITY_HOOK_NAME]
    msg_usage = {}
    msg_first_seq = {}
    models = Counter()
    tool_use = {}
    tool_calls_seq = []
    errors_detail = []  # (seq, tool_name, error_text) - for recurring-failure detection
    seq = 0
    simple_turns = 0  # turns whose only tool calls are Read/Grep/Glob - cheap-model candidates
    simple_turn_output_tokens = 0
    # Accumulate tool names per message.id across the multi-line Claude Code
    # layout (one JSONL line per content block). Judging simple_only per line
    # falsely flags a Read+Edit turn as lookup-only when Read and Edit land on
    # different lines of the same message — found by e2e sample fixtures.
    msg_tool_names = {}  # mid -> [tool name, ...]
    user_msgs, review_indices = _claude_frustration_messages(lines, path)
    n_interruptions = 0
    assistant_texts = []
    failed_turn_indices = []

    for line_idx, d in enumerate(lines):
        if _is_api_error_line(d):
            failed_turn_indices.append(line_idx)
        if d.get("type") == "assistant":
            msg = d.get("message", {})
            mid = msg.get("id")
            u = msg.get("usage", {})
            if mid not in msg_usage:
                msg_usage[mid] = {k: 0 for k in USAGE_FIELDS}
                msg_first_seq[mid] = seq
                models[msg.get("model", "?")] += 1
            peak = msg_usage[mid]
            for k in USAGE_FIELDS:
                peak[k] = max(peak[k], u.get(k, 0))
            for block in msg.get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    seq += 1
                    name = block.get("name")
                    msg_tool_names.setdefault(mid, []).append(name)
                    tool_use[block.get("id")] = (name, block.get("input"), seq)
                    tool_calls_seq.append((seq, name, block.get("input"), block.get("id")))
                elif isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text") or ""
                    if text.strip():
                        assistant_texts.append(text)
        elif d.get("type") == "user":
            content = d.get("message", {}).get("content")
            human_text = content if isinstance(content, str) else None
            if isinstance(content, list):
                has_tool_result = False
                texts = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        has_tool_result = True
                        if block.get("is_error"):
                            tid = block.get("tool_use_id")
                            name, inp, s = tool_use.get(tid, ("?", {}, None))
                            tool_calls_seq.append((s, "__ERROR__:" + str(name), inp, tid))
                            err_content = block.get("content")
                            if isinstance(err_content, list):
                                err_text = " ".join(b.get("text", "") for b in err_content if isinstance(b, dict))
                            else:
                                err_text = str(err_content or "")
                            errors_detail.append((s, name, err_text))
                    elif isinstance(block, dict) and block.get("type") == "text":
                        texts.append(block.get("text", ""))
                if not has_tool_result and texts:
                    human_text = "\n".join(texts)
            if human_text and "[Request interrupted by user" in human_text:
                n_interruptions += 1

    n_assistant = len(msg_usage)
    total_input = sum(u["input_tokens"] for u in msg_usage.values())
    total_output = sum(u["output_tokens"] for u in msg_usage.values())
    total_cache_read = sum(u["cache_read_input_tokens"] for u in msg_usage.values())
    total_cache_creation = sum(u["cache_creation_input_tokens"] for u in msg_usage.values())
    cache_points = [
        (msg_first_seq[mid], u["cache_creation_input_tokens"], u["cache_read_input_tokens"])
        for mid, u in msg_usage.items()
    ]

    LOOKUP_TOOLS = ("Read", "Grep", "Glob")
    for mid, names in msg_tool_names.items():
        if names and all(n in LOOKUP_TOOLS for n in names):
            simple_turns += 1
            simple_turn_output_tokens += msg_usage[mid]["output_tokens"]

    FILE_TOOLS = set(LOOKUP_TOOLS) | {"Edit", "Write"}
    used_tools = {n for names in msg_tool_names.values() for n in names if isinstance(n, str)}
    bash_only = "Bash" in used_tools and not (used_tools & FILE_TOOLS)
    lookup_blind = read_blind = edit_blind = bash_only
    BLIND_RATIONALE = (
        "all file access in this session went through Bash; this detector keys on the "
        "{} tool name(s) and cannot observe it"
    )

    grand = total_input + total_output + total_cache_read + total_cache_creation
    from_model = models.most_common(1)[0][0] if models else "claude-sonnet-5"
    tier_backtest = None
    if from_model in PRICING and simple_turn_output_tokens:
        actual, cheaper, saved = model_tier_savings(simple_turn_output_tokens, from_model=from_model)
        tier_backtest = {"actual": actual, "cheaper": cheaper, "saved": saved, "from_model": from_model}

    # Verified against 3 independent real-session audits: comparing file_path alone
    # flags windowed paging of a large file (different offset/limit each call) as
    # "redundant" when it's normal incremental exploration - one session had 64/67
    # flagged pairs turn out to be different windows of the same file. Only a call
    # with the IDENTICAL (offset, limit) as a prior read of the same file, unedited
    # since, is a genuine duplicate.
    last_read_seq, edited_since, redundant = {}, set(), []
    for s, name, inp, ident in sorted(tool_calls_seq, key=lambda x: x[0] or 0):
        if name in ("Edit", "Write") and isinstance(inp, dict):
            edited_since.add(_claude_tool_path(inp))
        elif name == "Read" and isinstance(inp, dict):
            fp = _claude_tool_path(inp)
            window = (inp.get("offset"), inp.get("limit"))
            key = (fp, window)
            if key in last_read_seq and fp not in edited_since:
                redundant.append((fp, window, last_read_seq[key], s))
            last_read_seq[key] = s
            edited_since.discard(fp)

    errors = [(s, name, inp) for s, name, inp, ident in tool_calls_seq if isinstance(name, str) and name.startswith("__ERROR__:")]
    tool_error_counts = Counter(name[len("__ERROR__:"):] for s, name, inp in errors)
    file_error_counts = Counter(
        _claude_tool_path(inp) for s, name, inp in errors if isinstance(inp, dict) and _claude_tool_path(inp)
    )

    # Same-problem-thrash detectors
    sig_groups = {}
    for s, name, text in errors_detail:
        if "doesn't want to proceed" in text:
            continue  # user rejection, not a stuck-on-the-same-problem signal
        norm = re.sub(r"\d+", "#", text.strip())[:120]
        sig_groups.setdefault((name, norm), []).append(s)
    recurring = {k: v for k, v in sig_groups.items() if len(v) > 1}

    edits_since_verify, file_streak_max = {}, {}
    global_streak = global_streak_max = verify_count = direct_run_verify_count = 0
    THRESH = 3
    for s, name, inp, ident in sorted(tool_calls_seq, key=lambda x: x[0] or 0):
        if name == "Bash" and isinstance(inp, dict) and VERIFY_RE.search(inp.get("command") or ""):
            verify_count += 1
            edits_since_verify.clear()
            global_streak = 0
        elif name == "Bash" and isinstance(inp, dict):
            targets = _direct_run_targets(inp.get("command") or "")
            edited_basenames = {os.path.basename(fp) for fp in edits_since_verify if fp}
            hit = targets & edited_basenames
            if hit:
                direct_run_verify_count += 1
                edits_since_verify.clear()
                global_streak = 0
        elif name in ("Edit", "Write") and isinstance(inp, dict):
            fp = _claude_tool_path(inp)
            edits_since_verify[fp] = edits_since_verify.get(fp, 0) + 1
            file_streak_max[fp] = max(file_streak_max.get(fp, 0), edits_since_verify[fp])
            global_streak += 1
            global_streak_max = max(global_streak_max, global_streak)
    flagged_files = {fp: n for fp, n in file_streak_max.items() if n >= THRESH}

    creations = sorted(c for _, c, r in cache_points if c > 0)
    spikes = []
    median = 0
    if creations:
        median = creations[len(creations)//2]
        threshold = max(50_000, median * 5)
        seen = set()
        for s, c, r in cache_points:
            if c >= threshold and c not in seen:
                seen.add(c)
                spikes.append((s, c, r))

    frustration = frustration_signals(
        user_msgs, n_interruptions, failed_turn_indices=failed_turn_indices,
        unflagged_indices=review_indices,
        extra_kinds=claude_restated_after_rejection(lines, user_msgs),
        judge=judge,
    )
    if intervention_commands:
        frustration["intervention_commands"] = dict(intervention_commands)
        frustration["intervention_command_count"] = sum(intervention_commands.values())

    flags = [
        _flag(
            "model-tier-candidates",
            "unchecked" if lookup_blind else ("yes" if simple_turns else "no"),
            None if lookup_blind else simple_turns,
            BLIND_RATIONALE.format("Read/Grep/Glob") if lookup_blind else
            (
                f"{simple_turns}/{n_assistant} turns called only Read/Grep/Glob "
                f"({simple_turn_output_tokens:,} output tokens on those turns)"
                + (
                    f"; output-side backtest ${tier_backtest['actual']:.4f} at "
                    f"{tier_backtest['from_model']} vs ${tier_backtest['cheaper']:.4f} at "
                    f"claude-haiku-4-5 -> ${tier_backtest['saved']:.4f} saved (lower bound)"
                    if tier_backtest else ""
                )
            ),
        ),
        _flag(
            "redundant-reads",
            "unchecked" if read_blind else ("yes" if redundant else "no"),
            None if read_blind else len(redundant),
            BLIND_RATIONALE.format("Read") if read_blind else
            f"{len(redundant)} redundant re-read(s) of an identical file+offset/limit window with no edit in between",
        ),
        _flag(
            "recurring-failure-signatures",
            "yes" if recurring else "no",
            len(recurring),
            f"{len(recurring)} recurring failure signature(s) (same error shape repeating across attempts)",
        ),
        _flag(
            "no-verify-edit-streak",
            "unchecked" if edit_blind else ("yes" if flagged_files or global_streak_max >= THRESH else "no"),
            None if edit_blind else global_streak_max,
            BLIND_RATIONALE.format("Edit/Write") if edit_blind else
            (
                f"longest edit streak with zero verification: {global_streak_max}; "
                f"{len(flagged_files)} file(s) at or above threshold {THRESH}; "
                f"verify Bash calls={verify_count}, direct-run verifies={direct_run_verify_count}"
            ),
        ),
        _flag(
            "cache-creation-spikes",
            "yes" if spikes else "no",
            len(spikes),
            (
                f"{len(spikes)} cache-creation spike(s) at/above max(50k, 5x median={median:,})"
                if creations else "no cache-creation events in session"
            ),
        ),
    ]
    flags.extend(_frustration_flags(frustration))
    flags.append(_brevity_follow_ups_flag(brevity_eli5_only, brevity_diu_commands))
    flags.append(_brevity_hook_blocks_flag(
        brevity_hook_blocks, brevity_eli5_only + brevity_diu_commands,
    ))
    retraction_hits = self_retraction_hits(assistant_texts)
    flags.append(_self_retraction_flag(retraction_hits))
    subagents = audit_subagents(path, audit_started_at=audit_started_at) if include_subagents else None
    context_cost = None
    if include_subagents:
        import subagent_cost
        context_cost = subagent_cost.analyze_context_cost(path, parent_spend=grand)
    flags.append(_subagent_thrash_flag(subagents))
    combined_total = None if subagents and subagents.get("unchecked") else grand + (subagents["totals"]["total"] if subagents else 0)

    redundant_read_files = sorted({fp for fp, _, _, _ in redundant})
    recurring_failure_details = [
        {"tool": name, "signature": norm, "occurrences": len(seqs)}
        for (name, norm), seqs in sorted(recurring.items(), key=lambda x: -len(x[1]))
    ]

    result = {
        "input": total_input,
        "output": total_output,
        "cache_read": total_cache_read,
        "cache_creation": total_cache_creation,
        "total": grand,
        "n_assistant": n_assistant,
        "models": dict(models),
        "n_errors": len(errors),
        "n_recurring_failures": len(recurring),
        "longest_edit_streak_no_verify": global_streak_max,
        "direct_run_verify_count": direct_run_verify_count,
        "flags": flags,
        "frustration": frustration,
        "self_retraction": retraction_hits,
        "subagents": subagents,
        "context_cost": context_cost,
        "combined_total": combined_total,
        "redundant_read_files": redundant_read_files,
        "recurring_failure_details": recurring_failure_details,
    }

    if out_path:
        report = {
            "path": path,
            "basename": os.path.basename(path),
            "totals": {
                "input": total_input,
                "output": total_output,
                "cache_read": total_cache_read,
                "cache_creation": total_cache_creation,
                "total": grand,
                "combined_total": combined_total,
                "n_assistant": n_assistant,
                "models": dict(models),
                "cache_read_share": (total_cache_read / grand) if grand else 0,
                "n_errors": len(errors),
                "n_recurring_failures": len(recurring),
                "longest_edit_streak_no_verify": global_streak_max,
            },
            "flags": flags,
            "frustration": frustration,
            "subagents": subagents,
            "context_cost": context_cost,
        }
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        print(f"=== CLAUDE CODE token audit: {os.path.basename(path)} ===")
        print(f"report: {out_path}")
        print(f"total={grand:,} turns={n_assistant} errors={len(errors)}")
        if subagents and subagents.get("unchecked"):
            print(f"subagents=unchecked reason={subagents['rationale']}")
        elif subagents:
            print(f"subagents={subagents['count']} subagent_total={subagents['totals']['total']:,} "
                  f"combined_total={combined_total:,}")
        for fl in flags:
            reason = f" {fl['rationale']}" if fl["value"] == "unchecked" else ""
            print(f"  {fl['name']}: {fl['value']} (count={fl['count']}){reason}")
        return result

    print(f"=== CLAUDE CODE token audit: {os.path.basename(path)} ===")
    print(f"assistant turns: {n_assistant}, models used: {dict(models)}")
    print(f"input={total_input:,} output={total_output:,} cache_read={total_cache_read:,} "
          f"cache_creation={total_cache_creation:,} total={grand:,}")
    if grand:
        print(f"cache_read share: {total_cache_read/grand:.1%}")

    print(f"-- model-tier candidates: {simple_turns}/{n_assistant} turns called only "
          f"Read/Grep/Glob ({simple_turn_output_tokens:,} output tokens on those turns) --")
    print("   (lookup-only turns like these are the ones worth checking against a cheaper")
    print("    model or a delegated subagent - this script only flags the shape, a human")
    print("    or the Cost lens still has to judge whether the turn needed full-model reasoning)")
    if tier_backtest:
        print(f"   backtest: those turns' OUTPUT tokens cost ${tier_backtest['actual']:.4f} at "
              f"{tier_backtest['from_model']} rates, ${tier_backtest['cheaper']:.4f} at claude-haiku-4-5 "
              f"rates -> ${tier_backtest['saved']:.4f} saved (output side only; "
              f"input/cache-read tokens for those turns aren't tracked per-turn, so this is a lower bound)")

    print("-- redundant reads (same file, same offset/limit window, no edit in between) --")
    for fp, window, s1, s2 in redundant:
        print(f"  {fp} offset/limit={window} (seq {s1} -> {s2})")
    print(f"redundant re-reads (identical window): {len(redundant)}")

    print(f"-- tool errors: {len(errors)} --")
    for s, name, inp in errors:
        print(f"  seq {s}: {name[len('__ERROR__:'):]} failed")

    if errors:
        print("-- tool errors by tool --")
        for tool, cnt in tool_error_counts.most_common():
            print(f"  {tool}: {cnt}")
        if file_error_counts:
            print("-- tool errors by file --")
            for fp, cnt in file_error_counts.most_common():
                print(f"  {fp}: {cnt}")

    print("-- feedback-loop check: recurring failure signatures (same error shape repeating) --")
    print("   (same-shaped failure recurring suggests the fix attempt didn't address the root")
    print("    cause, or wasn't verified before the next attempt - a slow feedback loop, not")
    print("    necessarily a broken one)")
    for (name, norm), seqs in sorted(recurring.items(), key=lambda x: -len(x[1])):
        print(f"  x{len(seqs)}  {name}: {norm!r} (seq {seqs})")
    print(f"recurring failure signatures: {len(recurring)}")

    print("-- feedback-loop check: edits without a verification run in between --")
    print("   (a Bash call matching test/build/lint/typecheck keywords counts as verification;")
    print("    heuristic only - doesn't confirm the right check ran or that it passed)")
    for fp, n in sorted(flagged_files.items(), key=lambda x: -x[1]):
        print(f"  {fp}: {n} edits in a row with no verification call in between")
    print(f"verification calls found (test/build/lint/typecheck-shaped Bash commands): {verify_count}")
    print(f"verification calls found (direct execution of the just-edited file, e.g. "
          f"`python3 foo.py`): {direct_run_verify_count}")
    print(f"longest edit streak with zero verification in between: {global_streak_max}")

    print("-- cache-creation spikes (fresh write, not cache read - expensive path) --")
    for s, c, r in spikes:
        print(f"  seq~{s}: cache_creation={c:,} cache_read={r:,} (session median creation={median:,})")

    _print_frustration(frustration)

    print("-- self-retraction (assistant admits prior check/claim was wrong) --")
    for hit in retraction_hits:
        print(f"  {hit!r}")
    print(f"self-retraction: {'yes' if retraction_hits else 'no'} (count={len(retraction_hits)})")

    if subagents is not None:
        _print_subagents_section(subagents, combined_total)
        _print_context_cost(context_cost)

    return result


def _print_subagents_section(subagents, combined_total):
    print("-- subagents (Task-tool fan-out; tokens and thrash belong to this session) --")
    if subagents.get("unchecked"):
        print(f"subagents: unchecked (count=None) {subagents['rationale']}")
        for path in subagents.get("active_files", []):
            print(f"   active: {os.path.basename(path)}")
        return
    print(f"subagents (attributed to this session): {subagents['count']}")
    if not subagents["count"]:
        return
    t = subagents["totals"]
    print(f"subagent_total={t['total']:,} (input={t['input']:,} output={t['output']:,} "
          f"cache_read={t['cache_read']:,} cache_creation={t['cache_creation']:,}); "
          f"combined_total={combined_total:,}")
    print("   top by tokens:")
    for r in subagents["top"]:
        fired = f"  flags={','.join(r['thrash_flags'])}" if r["thrash_flags"] else ""
        print(f"     {r['total']:>13,}  {r['n_assistant']:>4} turns  {r['n_errors']:>2} errors  "
              f"{r['file']}{fired}")
        print(f"         {r['description']}")
    th = subagents["thrash"]
    print(f"   thrash inside subagents: redundant_reads={th['redundant_reads']} "
          f"tool_errors={th['tool_errors']} recurring_failure_signatures={th['recurring_failure_signatures']} "
          f"longest_edit_streak_no_verify={th['longest_edit_streak_no_verify']} "
          f"self_retraction={th['self_retraction']}")
    print(f"   human messages inside subagents: {subagents['human_messages']} "
          "(a subagent's role=user rows are the parent's prompts, never counted as interventions)")


def _print_context_cost(report):
    print("-- subagent context-cost eval (token attribution; no provider pricing) --")
    for key in ("parent_spend", "child_spend", "child_output", "child_cache_read",
                "child_cache_creation", "child_count", "child_turns", "bash_turns",
                "non_bash_turns", "first_trigger_text"):
        print(f"   {key}={report[key]}")


def audit_codex(path, out_path=None, judge=False):
    lines = read_jsonl(path)
    models = Counter()
    last_usage = None
    turn_ends = []
    user_msgs = [
        (index, utterance.timestamp, utterance.text)
        for index, utterance in enumerate(
            transcript_provenance.direct_human_utterances(path, "codex")
        )
    ]
    assistant_texts = []
    n_interruptions = 0
    call_id_to_name = {}
    call_id_to_seq = {}
    tool_calls_seq = []
    errors_detail = []
    n_errors = 0
    seq = 0

    for d in lines:
        dtype = d.get("type")
        if dtype == "turn_context":
            m = d.get("payload", {}).get("model")
            if m:
                models[m] += 1
        elif dtype == "event_msg":
            payload = d.get("payload", {})
            ptype = payload.get("type")
            if ptype == "token_count":
                info = payload.get("info") or {}
                last_usage = info.get("total_token_usage")
                lu = info.get("last_token_usage")
                if lu:
                    turn_ends.append(lu)
            elif ptype in ("turn_aborted", "error"):
                # Best-effort: no interrupted session with either event type
                # has been observed in a real rollout yet, but codex-rs's
                # EventMsg protocol defines both for a turn cut short by the
                # user or a fatal error - counted the same way Claude's
                # "[Request interrupted by user]" marker is, so this stays
                # a no-op (0) rather than a crash if the shape is wrong.
                n_interruptions += 1
        elif dtype == "response_item":
            payload = d.get("payload", {})
            ptype = payload.get("type")
            if ptype == "message":
                role = payload.get("role")
                text = _codex_message_text(payload)
                if role == "assistant" and text.strip():
                    assistant_texts.append(text)
            elif ptype in ("function_call", "custom_tool_call"):
                call_id = payload.get("call_id")
                call_id_to_name[call_id] = payload.get("name")
                command = _codex_bash_command(payload)
                patch_paths = _codex_patch_paths(payload)
                if command:
                    seq += 1
                    call_id_to_seq[call_id] = seq
                    tool_calls_seq.append((seq, "Bash", {"command": command}, call_id))
                for file_path in patch_paths:
                    seq += 1
                    call_id_to_seq.setdefault(call_id, seq)
                    tool_calls_seq.append((seq, "Edit", {"file_path": file_path}, call_id))
            elif ptype in ("function_call_output", "custom_tool_call_output"):
                out_text = payload.get("output")
                if isinstance(out_text, dict):
                    out_text = out_text.get("content")
                if _codex_output_is_error(str(out_text or "")):
                    n_errors += 1
                    call_id = payload.get("call_id")
                    errors_detail.append(
                        (
                            call_id_to_seq.get(call_id),
                            call_id_to_name.get(call_id) or "?",
                            str(out_text or ""),
                        )
                    )

    cached_share = 0.0
    if turn_ends:
        cached_share = sum(t.get("cached_input_tokens", 0) for t in turn_ends) / max(
            1, sum(t.get("input_tokens", 0) for t in turn_ends)
        )

    frustration = frustration_signals(user_msgs, n_interruptions, judge=judge)
    flags = _frustration_flags(frustration)
    brevity_requests = sum(1 for _, _, text in user_msgs if _is_brevity_trigger_text(text))
    flags.append(_brevity_follow_ups_flag(brevity_requests))
    flags.append(_brevity_hook_blocks_flag(None, brevity_requests))
    retraction_hits = self_retraction_hits(assistant_texts)
    flags.append(_self_retraction_flag(retraction_hits))

    sig_groups = {}
    for s, name, text in errors_detail:
        norm = re.sub(r"\d+", "#", text.strip())[:120]
        sig_groups.setdefault((name, norm), []).append(s)
    recurring = {k: v for k, v in sig_groups.items() if len(v) > 1}

    edits_since_verify, file_streak_max = {}, {}
    global_streak = global_streak_max = verify_count = direct_run_verify_count = 0
    for s, name, inp, ident in sorted(tool_calls_seq, key=lambda x: x[0] or 0):
        if name == "Bash" and isinstance(inp, dict) and VERIFY_RE.search(inp.get("command") or ""):
            verify_count += 1
            edits_since_verify.clear()
            global_streak = 0
        elif name == "Bash" and isinstance(inp, dict):
            targets = _direct_run_targets(inp.get("command") or "")
            edited_basenames = {os.path.basename(fp) for fp in edits_since_verify if fp}
            if targets & edited_basenames:
                direct_run_verify_count += 1
                edits_since_verify.clear()
                global_streak = 0
        elif name == "Edit" and isinstance(inp, dict):
            fp = inp.get("file_path")
            edits_since_verify[fp] = edits_since_verify.get(fp, 0) + 1
            file_streak_max[fp] = max(file_streak_max.get(fp, 0), edits_since_verify[fp])
            global_streak += 1
            global_streak_max = max(global_streak_max, global_streak)
    flagged_files = {fp: n for fp, n in file_streak_max.items() if n >= 3}
    flags.extend([
        _flag(
            "recurring-failure-signatures",
            "yes" if recurring else "no",
            len(recurring),
            f"{len(recurring)} recurring failure signature(s) (same Codex tool-output error shape repeating across attempts)",
        ),
        _flag(
            "no-verify-edit-streak",
            "yes" if flagged_files or global_streak_max >= 3 else "no",
            global_streak_max,
            (
                f"longest edit streak with zero verification: {global_streak_max}; "
                f"{len(flagged_files)} file(s) at or above threshold 3; "
                f"verify Bash calls={verify_count}, direct-run verifies={direct_run_verify_count}"
            ),
        ),
    ])

    result = {
        "models": dict(models),
        "last_usage": last_usage,
        "n_turns": len(turn_ends),
        "cache_read_share": cached_share,
        "total": (last_usage or {}).get("total_tokens", 0),
        "n_errors": n_errors,
        "n_recurring_failures": len(recurring),
        "longest_edit_streak_no_verify": global_streak_max,
        "flags": flags,
        "frustration": frustration,
        "self_retraction": retraction_hits,
    }

    if out_path:
        report = {
            "path": path,
            "basename": os.path.basename(path),
            "totals": {
                "input": (last_usage or {}).get("input_tokens", 0),
                "output": (last_usage or {}).get("output_tokens", 0),
                "cached_input": (last_usage or {}).get("cached_input_tokens", 0),
                "total": (last_usage or {}).get("total_tokens", 0),
                "n_turns": len(turn_ends),
                "models": dict(models),
                "cache_read_share": cached_share,
                "n_errors": n_errors,
                "n_recurring_failures": len(recurring),
                "longest_edit_streak_no_verify": global_streak_max,
            },
            "flags": flags,
            "frustration": frustration,
            "self_retraction": retraction_hits,
        }
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        print(f"=== CODEX token audit: {os.path.basename(path)} ===")
        print(f"report: {out_path}")
        print(f"total={(last_usage or {}).get('total_tokens', 0):,} turns={len(turn_ends)}")
        if frustration["count"] is None:
            _print_frustration(frustration)
        return result

    print(f"=== CODEX token audit: {os.path.basename(path)} ===")
    print(f"models used: {dict(models) if models else 'unknown (no turn_context in this file)'}")
    if last_usage:
        print(f"cumulative session usage: {last_usage}")
    if turn_ends:
        print(f"per-turn cache hit rate (cached/input averaged over {len(turn_ends)} turns): {cached_share:.1%}")
        biggest = sorted(turn_ends, key=lambda t: -t.get("total_tokens", 0))[:5]
        print("-- most expensive individual turns --")
        for t in biggest:
            print(f"  {t}")
    else:
        print("no token_count events found in this file")

    print("-- per-turn growth (last_total_tokens per turn) --")
    for i, t in enumerate(turn_ends):
        print(f"  turn {i}: {t.get('total_tokens', 0):,}")

    print(f"-- tool errors: {n_errors} --")

    _print_frustration(frustration)

    print("-- self-retraction (assistant admits prior check/claim was wrong) --")
    for hit in retraction_hits:
        print(f"  {hit!r}")
    print(f"self-retraction: {'yes' if retraction_hits else 'no'} (count={len(retraction_hits)})")

    return result


_OMP_EDIT_PATH_RE = re.compile(r"\[([^\]#]+)")


def _omp_tool_call_path(name, arguments):
    """OMP's three file-touching tools name the path differently, verified
    against real sessions: read/write take a plain `path` argument; edit
    takes an `input` field in apple-patch format with the path embedded as
    the first bracketed header line (`[/path/to/file.ts#E3AC]`)."""
    if name in ("read", "write"):
        return arguments.get("path")
    if name == "edit":
        m = _OMP_EDIT_PATH_RE.search(arguments.get("input", "") or "")
        return m.group(1) if m else None
    return None


def audit_omp(path, out_path=None, judge=False):
    lines = read_jsonl(path)
    models = Counter()
    turns = []
    tool_calls = []  # (seq, name, path, call_id)
    call_id_to_name = {}
    user_msgs = []  # (ordinal, iso_timestamp, text) — human messages only
    n_interruptions = 0  # interrupted-thinking events + skipped-tool markers
    seq = 0
    for d in lines:
        if d.get("type") == "model_change":
            m = d.get("model")
            if m:
                models[m] += 1
        # OMP marks a user interjection cutting off in-flight work with a
        # dedicated event type — verified against a real session (7 events
        # matched 7 visible mid-turn interruptions).
        if d.get("customType") == "interrupted-thinking":
            n_interruptions += 1
        if d.get("type") == "message":
            msg = d.get("message", {})
            if msg.get("role") == "user":
                text = _omp_user_text(d)
                if text.strip():
                    user_msgs.append((len(user_msgs), d.get("timestamp"), text))
            if msg.get("role") == "toolResult":
                # Tool calls cancelled because the user queued a new message —
                # the other interruption shape OMP records.
                blob = json.dumps(msg.get("content")) if not isinstance(msg.get("content"), str) else msg.get("content")
                if "Skipped due to queued user message" in (blob or ""):
                    n_interruptions += 1
            if msg.get("role") == "assistant" and msg.get("usage"):
                turns.append((msg.get("model"), msg.get("usage")))
            if msg.get("role") == "assistant":
                for b in msg.get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "toolCall":
                        seq += 1
                        name = b.get("name")
                        call_id = b.get("id")
                        fp = _omp_tool_call_path(name, b.get("arguments", {}) or {})
                        call_id_to_name[call_id] = name
                        tool_calls.append((seq, name, fp, call_id))

    print(f"=== OMP token audit: {os.path.basename(path)} ===")
    print(f"model_change events: {dict(models) if models else 'none'}")
    print(f"assistant turns with usage: {len(turns)}")
    total_input = sum(u.get("input", 0) for _, u in turns)
    total_output = sum(u.get("output", 0) for _, u in turns)
    total_cache_read = sum(u.get("cacheRead", 0) for _, u in turns)
    total_cache_write = sum(u.get("cacheWrite", 0) for _, u in turns)
    total_cost = sum((u.get("cost") or {}).get("total", 0) for _, u in turns)
    grand = total_input + total_output + total_cache_read + total_cache_write
    print(f"input={total_input:,} output={total_output:,} cacheRead={total_cache_read:,} "
          f"cacheWrite={total_cache_write:,} total={grand:,}")
    print(f"OMP-reported dollar cost for this session: ${total_cost:.4f}")
    turn_models = Counter(m for m, u in turns)
    print(f"per-turn model mix: {dict(turn_models)}")
    biggest = sorted(turns, key=lambda t: -(t[1].get("totalTokens", 0)))[:5]
    print("-- most expensive individual turns --")
    for m, u in biggest:
        print(f"  model={m} totalTokens={u.get('totalTokens') or 0:,} cost=${(u.get('cost') or {}).get('total', 0):.4f}")

    print("-- redundant reads (same file via `read`, no `edit`/`write` in between) --")
    last_read_seq, edited_since, redundant = {}, set(), []
    for s, name, fp, call_id in tool_calls:
        if name in ("edit", "write") and fp:
            edited_since.add(fp)
        elif name == "read" and fp:
            if fp in last_read_seq and fp not in edited_since:
                redundant.append((fp, last_read_seq[fp], s))
            last_read_seq[fp] = s
            edited_since.discard(fp)
    for fp, s1, s2 in redundant:
        print(f"  {fp} (seq {s1} -> {s2})")
    print(f"redundant re-reads: {len(redundant)}")

    print("-- tool errors --")
    n_errors = 0
    for d in lines:
        if d.get("type") != "message":
            continue
        msg = d.get("message", {})
        if msg.get("role") == "toolResult" and msg.get("isError"):
            n_errors += 1
            name = call_id_to_name.get(msg.get("toolCallId"), msg.get("toolName", "?"))
            print(f"  {name} failed")
    print(f"tool errors: {n_errors}")

    frustration = frustration_signals(user_msgs, n_interruptions, judge=judge)
    _print_frustration(frustration)

    flags = [
        _flag(
            "redundant-reads",
            "yes" if redundant else "no",
            len(redundant),
            f"{len(redundant)} redundant re-read(s) of the same file with no edit in between",
        ),
        _flag(
            "tool-errors",
            "yes" if n_errors else "no",
            n_errors,
            f"{n_errors} tool result(s) marked isError",
        ),
    ]
    flags.extend(_frustration_flags(frustration))
    brevity_requests = sum(1 for _, _, text in user_msgs if _is_brevity_trigger_text(text))
    flags.append(_brevity_follow_ups_flag(brevity_requests))
    flags.append(_brevity_hook_blocks_flag(None, brevity_requests))
    result = {
        "input": total_input,
        "output": total_output,
        "cache_read": total_cache_read,
        "cache_write": total_cache_write,
        "total": grand,
        "cost_total": total_cost,
        "n_turns": len(turns),
        "n_errors": n_errors,
        "flags": flags,
        "frustration": frustration,
    }
    if out_path:
        report = {
            "path": path,
            "basename": os.path.basename(path),
            "totals": {
                "input": total_input,
                "output": total_output,
                "cache_read": total_cache_read,
                "cache_write": total_cache_write,
                "total": grand,
                "cost_total": total_cost,
                "n_turns": len(turns),
                "cache_read_share": (total_cache_read / grand) if grand else 0,
                "n_errors": n_errors,
                "models": dict(Counter(m for m, u in turns)),
            },
            "flags": flags,
            "frustration": frustration,
        }
        with open(out_path, "w") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
        print(f"report: {out_path}")
    return result


def audit_cursor(path, judge=False):
    lines = read_jsonl(path)
    user_msgs = [
        (index, utterance.timestamp, utterance.text)
        for index, utterance in enumerate(
            transcript_provenance.direct_human_utterances(path, "cursor")
        )
    ]
    frustration = frustration_signals(user_msgs, judge=judge)
    flags = _frustration_flags(frustration)
    brevity_requests = sum(1 for _, _, text in user_msgs if _is_brevity_trigger_text(text))
    flags.append(_brevity_follow_ups_flag(brevity_requests))
    flags.append(_brevity_hook_blocks_flag(None, brevity_requests))
    print(f"=== CURSOR thrash audit: {os.path.basename(path)} ===")
    print("NOTE: Cursor's local agent-transcripts carry no token/usage/model fields")
    print("(verified by scanning real transcripts) - no cost numbers are possible from")
    print("this file. Thrash (redundant tool calls) is still detectable:")
    tool_calls = []
    for d in lines:
        msg = d.get("message") if isinstance(d, dict) else None
        if not msg:
            continue
        for block in msg.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls.append((block.get("name"), block.get("input")))
    counts = Counter()
    for name, inp in tool_calls:
        h, s = sig(name, inp)
        counts[(name, h)] += 1
    dupes = [(k, v) for k, v in counts.items() if v > 1]
    dupes.sort(key=lambda x: -x[1])
    print(f"distinct tool calls: {len(counts)}, calls with exact repeats: {len(dupes)}")
    for (name, h), cnt in dupes[:10]:
        print(f"  x{cnt}  {name}")
    _print_frustration(frustration, details=False)
    return {
        "flags": flags,
        "frustration": frustration,
        "duplicate_tool_calls": dupes,
    }


def list_remotes():
    cfg_path = os.path.expanduser("~/.invoker/config.json")
    if not os.path.exists(cfg_path):
        print(f"no invoker config at {cfg_path} - skipping remote scan capability")
        return
    with open(cfg_path) as f:
        cfg = json.load(f)
    targets = list((cfg.get("remoteTargets") or {}).keys())
    print(f"remote targets found in {cfg_path} (names only, no hosts printed):")
    for t in targets:
        print(f"  - {t}")
    print(f"{len(targets)} remote machine(s) could be scanned for ~/.claude, ~/.codex, ~/.cursor")
    print("session data over SSH, using the sshKeyPath/host/user already in that config.")
    print("This script does not do that scan itself - it requires an explicit, confirmed")
    print("SSH step per target, since that touches remote/shared infrastructure.")


def _parse_argv(argv):
    """Parse `mode [path] [--out path] [--no-subagents] [--judge]`. Unknown
    flags exit non-zero. Returns (mode, path, out_path, include_subagents, judge)."""
    if len(argv) < 2:
        return None, None, None, True, False
    if argv[1] in ("--help", "-h"):
        print(__doc__)
        sys.exit(0)
    mode = argv[1]
    out_path = None
    path = None
    include_subagents = True
    judge = False
    i = 2
    while i < len(argv):
        if argv[i] == "--out":
            if i + 1 >= len(argv):
                print("--out requires a path", file=sys.stderr)
                sys.exit(1)
            out_path = argv[i + 1]
            i += 2
        elif argv[i] == "--no-subagents":
            include_subagents = False
            i += 1
        elif argv[i] == "--judge":
            judge = True
            i += 1
        elif argv[i].startswith("-"):
            print(f"unknown flag: {argv[i]}", file=sys.stderr)
            sys.exit(1)
        else:
            if path is not None:
                print(f"unexpected argument: {argv[i]}", file=sys.stderr)
                sys.exit(1)
            path = argv[i]
            i += 1
    return mode, path, out_path, include_subagents, judge


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        sys.exit(1)
    mode, path, out_path, include_subagents, judge = _parse_argv(sys.argv)
    if mode != "claude" and not include_subagents:
        print("--no-subagents is only supported for claude mode", file=sys.stderr)
        sys.exit(1)
    if mode == "remotes" and judge:
        print("--judge is only supported for claude, omp, codex, and cursor modes", file=sys.stderr)
        sys.exit(1)
    if mode == "remotes":
        if out_path:
            print("--out is only supported for claude, omp, and codex modes", file=sys.stderr)
            sys.exit(1)
        list_remotes()
    elif mode == "claude":
        if not path:
            print("claude mode requires a session path", file=sys.stderr)
            sys.exit(1)
        audit_claude(path, out_path=out_path, include_subagents=include_subagents, judge=judge)
    elif mode == "omp":
        if not path:
            print("omp mode requires a session path", file=sys.stderr)
            sys.exit(1)
        audit_omp(path, out_path=out_path, judge=judge)
    elif mode == "codex":
        if not path:
            print("codex mode requires a session path", file=sys.stderr)
            sys.exit(1)
        audit_codex(path, out_path=out_path, judge=judge)
    elif mode == "cursor":
        if out_path:
            print("--out is only supported for claude, omp, and codex modes", file=sys.stderr)
            sys.exit(1)
        if not path:
            print("cursor mode requires a session path", file=sys.stderr)
            sys.exit(1)
        audit_cursor(path, judge=judge)
    else:
        print(f"unknown mode: {mode}", file=sys.stderr)
        sys.exit(1)
