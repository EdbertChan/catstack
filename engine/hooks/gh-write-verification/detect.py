"""gh-write-verification: a write's report is not the write's effect.

Three detectors, one principle. A command that changes remote state has to
leave behind evidence the agent actually looked at, and that evidence has to
be the effect itself -- not the tool's own claim about it.

1. BROKEN WRITER (`broken_pr_edit`). `gh pr edit` eagerly queries
   `repository.pullRequest.projectCards`, a sunset Projects-classic field, so
   it fails on *every* flag -- `--base`, `--add-label`, `--title`, `--body` --
   before it writes anything. The equivalent `gh api` REST calls work. This
   is fail-fast applied to the tool choice: the reliably-broken path is
   refused up front and the working one is named, rather than letting each
   session rediscover the GraphQL error. Set
   `GH_WRITE_VERIFICATION_TRUST_PR_EDIT=1` to lift the block once the CLI or
   the API stops erroring.

2. SILENCED MUTATION (`silenced_mutations`). A state-changing command whose
   stdout *and* stderr both go to /dev/null with no exit-code check destroys
   the only report of its own failure. Jim Shore, "Fail Fast," IEEE Software
   21(5) 2004 (https://martinfowler.com/ieeeSoftware/failFast.pdf), names the
   defect class: a failure that is discarded surfaces later, somewhere else,
   with the diagnostic evidence already gone. Read-only commands with
   discarded output (`grep -q`, `command -v`, `git cat-file -e`) are
   legitimate and extremely common, so the mutating set is an explicit
   allowlist of danger -- anything not on it is silent by construction.

3. SELF-MATCHING PROCESS WAIT (`self_matching_process_waits`). `pgrep -f` and
   `pkill -f` match full command lines, and the pattern sits in the argv of the
   very shell that runs them, so the match is never empty. An agent harness
   that runs each tool call as `bash -c '<the whole command>'` puts the pattern
   in a live process cmdline before the search even starts, which makes a
   one-shot `pgrep -f <service>` report present for a service that is not
   running anywhere. A wait negated on `pgrep -f <name>` therefore can never
   exit, and `pkill -f <name>` kills its own wrapper. There is no correct plain
   `-f` spelling under such a harness, so the detector does not wait for a loop
   before objecting. The pattern occurring exactly once is enough -- being the pgrep
   argument *is* the occurrence -- so a test for "the pattern appears elsewhere
   in the command" misses the canonical loop. A bracket character class is the
   standard workaround, and it holds only while the plain spelling appears
   nowhere else in the same command. This gap matters here because catstack's
   own `wait-needs-wakeup` pushes agents toward polling loops without saying
   how to write one that terminates. No formal prior art found; the named folk
   pattern is the `ps | grep` self-match and its `[f]oo` bracket idiom.

4. UNVERIFIED LANDING (`merges_missing_landing_proof`). `gh pr merge`
   reporting MERGED means the PR closed against *its own base ref*, which is
   not necessarily the trunk. Saltzer, Reed and Clark's end-to-end argument
   (ACM TOCS 2(4), 1984) is the established form: an intermediate
   acknowledgement cannot stand in for the end-to-end property, which here is
   "the merge commit is reachable from the trunk." Only
   `git merge-base --is-ancestor <merge_commit> origin/<trunk>` decides that.

KNOWN FALSE POSITIVE: matching is a raw-text scan over the whole hook
payload, not a shell parser, and unlike the sibling pr-schema-gate this one
deliberately does *not* strip heredoc bodies -- a heredoc that writes a shell
script containing a silenced mutation is the exact shape of the incident, and
`bash script.sh` is opaque to a PreToolUse hook afterwards. The cost is that
documenting or testing these detectors with an inline heredoc trips them.
Write such text to a file with the Write tool instead.
"""
from __future__ import annotations

import json
import os
import re

TRUST_PR_EDIT_ENV = "GH_WRITE_VERIFICATION_TRUST_PR_EDIT"

GH_PR_EDIT_RE = re.compile(r"\bgh\s+pr\s+edit\b")

PR_EDIT_MESSAGE = (
    "gh-write-verification: `gh pr edit` fails on every flag -- it eagerly "
    "queries the sunset `repository.pullRequest.projectCards` GraphQL field "
    "and exits 1 before writing anything. Use the REST API instead:\n"
    "  base / title / body:  gh api -X PATCH repos/<owner>/<repo>/pulls/<n> "
    "-f base=<branch>\n"
    "  labels:               gh api -X POST repos/<owner>/<repo>/issues/<n>/labels "
    "-f 'labels[]=<label>'\n"
    "Read the result back with `gh api repos/<owner>/<repo>/pulls/<n> --jq "
    ".base.ref` -- from the response, not from a cached earlier read. Set "
    f"{TRUST_PR_EDIT_ENV}=1 to lift this once the CLI stops erroring."
)

MUTATING_RE = re.compile(
    r"\bgh\s+pr\s+(?:merge|edit|create|close|reopen|ready|comment|review)\b"
    r"|\bgh\s+issue\s+(?:create|edit|close|reopen|comment|delete)\b"
    r"|\bgh\s+release\s+(?:create|edit|delete|upload)\b"
    r"|\bgh\s+api\b[^\n]*?(?:-X|--method)[=\s]+(?:POST|PATCH|PUT|DELETE)\b"
    r"|\bgit\s+push\b"
    r"|\bgit\s+(?:merge|rebase|cherry-pick|revert)\b"
    r"|\bgit\s+reset\s+--hard\b"
    r"|\bgit\s+branch\s+-[dD]\b"
    r"|\bgit\s+tag\s+-d\b"
    r"|\bmergify\s+(?:stack\s+push|queue)\b"
    r"|\bcurl\b[^\n]*?(?:-X|--request)[=\s]+(?:POST|PUT|PATCH|DELETE)\b"
    r"|\bnpm\s+publish\b"
    r"|\bdocker\s+push\b"
    r"|\bkubectl\s+(?:apply|create|delete|patch|replace)\b"
    r"|\bsystemctl\s+(?:start|stop|restart|reload|enable|disable)\b"
    r"|\bterraform\s+(?:apply|destroy)\b",
    re.IGNORECASE,
)

DISCARD_BOTH_RE = re.compile(
    r"&>>?\s*/dev/null"
    r"|>&\s*/dev/null"
    r"|1?>>?\s*/dev/null\s+2>&1(?![0-9-])"
    r"|1?>>?\s*/dev/null[^\n|;&]*?\s2>>?\s*/dev/null"
    r"|2>>?\s*/dev/null[^\n|;&]*?\s1?>>?\s*/dev/null"
)

SEGMENT_SPLIT_RE = re.compile(r"(\|\||&&|\||;|\n)")
CONDITIONAL_HEAD_RE = re.compile(r"(?:^|\W)(?:if|while|until|elif)\s+!?\s*\S")
EXIT_STATUS_RE = re.compile(r"\$\?|\bset\s+-[a-z]*e[a-z]*\b|\bpipefail\b")

SILENCED_MESSAGE = (
    "gh-write-verification: this discards both stdout and stderr from a "
    "state-changing command and never checks its exit code:\n{hits}\n"
    "A mutation that fails silently is reported as success by the next stale "
    "read-back. Either drop the redirect and read the output, or check the "
    "status explicitly (`|| {{ echo failed; exit 1; }}`, `if ! cmd; then`, or "
    "`set -e`), then verify the effect rather than the command's own report."
)

PROC_TOOL_RE = re.compile(r"\b(?P<tool>pgrep|pkill)\b")
PROC_VALUE_FLAGS = frozenset({
    "-u", "-U", "-g", "-G", "-P", "-s", "-t", "-d", "-F", "--signal",
    "--delimiter", "--uid", "--euid", "--parent", "--session", "--terminal",
    "--pidfile", "--ns", "--nslist",
})
PROC_TOKEN_RE = re.compile(r"'[^']*'|\"[^\"]*\"|[^\s;&|()]+")
PROC_FULL_FLAG_RE = re.compile(r"^-[A-Za-z]*f[A-Za-z]*$|^--full$")
BRACKET_CLASS_RE = re.compile(r"\[([^\]]+)\]")
REGEX_ESCAPE_RE = re.compile(r"\\(.)")

SELF_MATCH_MESSAGE = (
    "gh-write-verification: this matches on a process pattern that also matches "
    "the shell asking the question:\n{hits}\n"
    "`pgrep -f` / `pkill -f` compare full command lines, and this command runs "
    "inside a wrapper shell whose cmdline carries the whole command text -- so "
    "the pattern is already in a live process before the search starts. The "
    "match is never empty even outside a loop: a one-shot `pgrep -f <service>` "
    "reports present for a service that is running nowhere, a wait negated on it "
    "never exits, and `pkill -f` kills its own wrapper. Match on a pid you "
    "captured (`kill -0 \"$PID\" 2>/dev/null`), wait on something the watched "
    "process writes (`grep -q '^EXIT=' out.log` in the loop condition), or hide "
    "the pattern from the cmdline with a bracket class such as `[p]ostgres` -- "
    "which holds only while the plain spelling appears nowhere else in the "
    "command."
)


def _process_match_pattern(text: str, start: int) -> str | None:
    """The full-command-line pattern this pgrep/pkill matches on, or None.

    None when the invocation carries no `-f`/`--full` flag: without it the tool
    compares process names only, and a shell named `bash` cannot self-match.
    """
    rest = re.split(r"[<>]", text[start:], maxsplit=1)[0]
    tokens = PROC_TOKEN_RE.findall(rest)[1:]
    matches_full = False
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("-"):
            break
        if PROC_FULL_FLAG_RE.match(token):
            matches_full = True
        if token in PROC_VALUE_FLAGS:
            index += 1
        index += 1
    if not matches_full or index >= len(tokens):
        return None
    return tokens[index].strip("'\"")


def _bracket_class_still_collides(pattern: str, text: str) -> bool:
    """Whether a bracketed pattern's plain spelling survives elsewhere in the text.

    The bracket idiom holds only while nothing else in the same command line
    spells the token out; one plain mention anywhere brings the self-match back.
    """
    plain = REGEX_ESCAPE_RE.sub(r"\1", BRACKET_CLASS_RE.sub(lambda m: m.group(1), pattern))
    return plain in text.replace(pattern, "", 1)


def self_matching_process_waits(raw_text: str) -> list[str]:
    """pgrep/pkill invocations whose pattern matches their own command line."""
    text = unescape_payload(raw_text)
    hits: list[str] = []
    for match in PROC_TOOL_RE.finditer(text):
        pattern = _process_match_pattern(text, match.start())
        if pattern is None:
            continue
        if "$" in pattern or "`" in pattern:
            continue
        if BRACKET_CLASS_RE.search(pattern) and not _bracket_class_still_collides(pattern, text):
            continue
        hit = f"{match.group('tool')} -f {pattern}"
        if hit not in hits:
            hits.append(hit)
    return hits


def self_match_message(hits: list[str]) -> str:
    return SELF_MATCH_MESSAGE.format(hits="\n".join(f"    {hit}" for hit in hits))


GH_PR_MERGE_RE = re.compile(r"\bgh\s+pr\s+merge\b(?:\s+(?P<number>\d+))?")
LANDING_PROOF_RE = re.compile(
    r"\bverify_pr_landed_on_trunk\b"
    r"|\bgit\s+merge-base\s+--is-ancestor\b"
    r"|\bgit\s+branch\s+-r\s+--contains\b"
    r"|\bgit\s+branch\s+--contains\b[^\n]*\s-r\b"
)
VERIFY_SCRIPT_RELPATH = "gh-write-verification/verify_pr_landed_on_trunk.sh"

UNVERIFIED_MERGE_MESSAGE = (
    "gh-write-verification: this turn merged {subjects} and never checked "
    "where the merge commit landed. `gh pr merge` reporting MERGED only means "
    "the PR closed against its own base ref, which is not necessarily the "
    "trunk -- a PR whose base was never retargeted merges into its own stack "
    "branch and reports exactly the same MERGED state.\n"
    "Run the end-to-end check before finishing:\n"
    '  bash "$HOME/.claude/hooks/' + VERIFY_SCRIPT_RELPATH + '" <pr-number>\n'
    "It resolves the merge commit through `gh api` and asserts "
    "`git merge-base --is-ancestor <merge_commit> origin/<trunk>`, exiting "
    "non-zero when the commit is not on the trunk."
)


def unescape_payload(raw_text: str) -> str:
    """Turn a JSON payload's two-character escapes into real whitespace.

    Used only to search. Heredoc bodies are kept: a heredoc that writes a
    shell script is how a silenced mutation reaches a later opaque
    `bash script.sh`, which no PreToolUse hook can inspect.
    """
    return (raw_text or "").replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"')


def broken_pr_edit(raw_text: str) -> str | None:
    """Return the offending `gh pr edit` text, or None when it is absent."""
    if os.environ.get(TRUST_PR_EDIT_ENV):
        return None
    match = GH_PR_EDIT_RE.search(unescape_payload(raw_text))
    return match.group(0) if match else None


def _segments(text: str) -> list[tuple[str, str]]:
    parts = SEGMENT_SPLIT_RE.split(text)
    pairs: list[tuple[str, str]] = []
    for index in range(0, len(parts), 2):
        separator = parts[index + 1] if index + 1 < len(parts) else ""
        pairs.append((parts[index], separator))
    return pairs


def _status_is_checked(segment: str, separator: str, whole: str) -> bool:
    if separator in ("||", "&&"):
        return True
    if CONDITIONAL_HEAD_RE.search(segment):
        return True
    return bool(EXIT_STATUS_RE.search(whole))


def silenced_mutations(raw_text: str) -> list[str]:
    """Mutating commands in the payload whose failure output is thrown away.

    A hit needs all three: an allowlisted state-changing command, a redirect
    that discards stdout *and* stderr, and no exit-code check anywhere that
    could surface the failure.
    """
    text = unescape_payload(raw_text)
    hits: list[str] = []
    for segment, separator in _segments(text):
        mutation = MUTATING_RE.search(segment)
        if not mutation:
            continue
        discard = DISCARD_BOTH_RE.search(segment, mutation.start())
        if not discard:
            continue
        if _status_is_checked(segment, separator, text):
            continue
        hits.append(segment[mutation.start():discard.end()].strip())
    return hits


def _proves_landing(command: str, number: str | None) -> bool:
    """True when this command checks where a merge commit actually landed.

    An invocation of the shipped verification script must name the PR it is
    vouching for; a hand-rolled ancestry check is accepted as written, since
    it takes a commit sha rather than a PR number.
    """
    command = command or ""
    if not LANDING_PROOF_RE.search(command):
        return False
    if "verify_pr_landed_on_trunk" in command and number is not None:
        return number in command
    return True


def merges_missing_landing_proof(commands: list[str]) -> list[str]:
    """PR subjects merged in this turn with no landing check run afterwards.

    Returns the merged subjects (a PR number, or "the current branch's PR"
    when the command omitted one) when no later command in the turn proves
    the merge commit reached the trunk. Empty when nothing merged or when the
    proof ran after the merge.
    """
    subjects: list[str] = []
    for index, command in enumerate(commands):
        match = GH_PR_MERGE_RE.search(command or "")
        if not match:
            continue
        number = match.group("number")
        subject = f"PR #{number}" if number else "the current branch's PR"
        if any(_proves_landing(later, number) for later in commands[index + 1:]):
            continue
        if subject not in subjects:
            subjects.append(subject)
    return subjects


def unverified_merge_message(subjects: list[str]) -> str:
    return UNVERIFIED_MERGE_MESSAGE.format(subjects=", ".join(subjects))


def silenced_message(hits: list[str]) -> str:
    return SILENCED_MESSAGE.format(hits="\n".join(f"    {hit}" for hit in hits))


def pretooluse_problems(raw_text: str) -> list[str]:
    """Every blocking message this payload earns, in reporting order."""
    problems: list[str] = []
    if broken_pr_edit(raw_text):
        problems.append(PR_EDIT_MESSAGE)
    hits = silenced_mutations(raw_text)
    if hits:
        problems.append(silenced_message(hits))
    waits = self_matching_process_waits(raw_text)
    if waits:
        problems.append(self_match_message(waits))
    return problems


def _text_content(data: dict) -> str:
    message = data.get("message")
    content = message.get("content") if isinstance(message, dict) else data.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _is_human_user_line(data: dict) -> bool:
    if data.get("type") != "user":
        return False
    text = _text_content(data)
    return bool(text.strip()) and not text.lstrip().startswith("<")


def bash_commands_this_turn(raw_lines) -> list[str]:
    """Bash tool commands issued since the last authored user message."""
    parsed: list[dict] = []
    for raw in raw_lines:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(data, dict):
            parsed.append(data)
    turn_start = 0
    for index, data in enumerate(parsed):
        if _is_human_user_line(data):
            turn_start = index
    commands: list[str] = []
    for data in parsed[turn_start:]:
        if data.get("type") != "assistant":
            continue
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            if block.get("name") not in ("Bash", "bash"):
                continue
            tool_input = block.get("input")
            if isinstance(tool_input, dict):
                commands.append(str(tool_input.get("command") or ""))
    return commands


def decide_stop(payload: dict) -> str | None:
    """Blocking feedback for the Stop event, or None to let the turn finish.

    Fails open on a missing or unreadable transcript: a check we could not
    run must never wedge a turn.
    """
    if payload.get("stop_hook_active"):
        return None
    transcript_path = payload.get("transcript_path") or payload.get("transcriptPath") or ""
    if not transcript_path:
        return None
    try:
        with open(transcript_path, encoding="utf-8") as handle:
            commands = bash_commands_this_turn(handle)
    except OSError:
        return None
    subjects = merges_missing_landing_proof(commands)
    if not subjects:
        return None
    return unverified_merge_message(subjects)
