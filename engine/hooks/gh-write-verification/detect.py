"""gh-write-verification: a write's report is not the write's effect.

Five detectors, one principle. A command that changes remote state has to
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

2b. PIPED-AWAY EXIT CODE (`piped_away_mutations`). A pipeline reports only
   its last stage's status, so a mutation piped into `tail`/`head`/`grep`
   reports the reader's 0 whatever the write did. Pipefail set earlier in the
   same shell, or the dialect's status array read by the very next command,
   counts as a check; `${PIPESTATUS[0]}` does not in zsh, where it is empty.
   This one lexes the command with `shlex` instead of scanning raw text, and
   a command it cannot lex is unchecked, not clean.

4. UNVERIFIED LANDING (`merges_missing_landing_proof`). `gh pr merge`
   reporting MERGED means the PR closed against *its own base ref*, which is
   not necessarily the trunk. Saltzer, Reed and Clark's end-to-end argument
   (ACM TOCS 2(4), 1984) is the established form: an intermediate
   acknowledgement cannot stand in for the end-to-end property, which here is
   "the merge commit is reachable from the trunk." Only
   `git merge-base --is-ancestor <merge_commit> origin/<trunk>` decides that.

KNOWN FALSE POSITIVE: for 1-3, matching is a raw-text scan over the whole hook
payload, not a shell parser, and unlike the sibling pr-schema-gate this one
deliberately does *not* strip heredoc bodies -- a heredoc that writes a shell
script containing a silenced mutation is the exact shape of the incident, and
`bash script.sh` is opaque to a PreToolUse hook afterwards. The cost is that
documenting or testing these detectors with an inline heredoc trips them.
Write such text to a file with the Write tool instead.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Optional, Tuple

SDK_DIR = Path(__file__).resolve().parents[1] / "_sdk"
if str(SDK_DIR) not in sys.path:
    sys.path.insert(0, str(SDK_DIR))

from finding import Finding

TRUST_PR_EDIT_ENV = "GH_WRITE_VERIFICATION_TRUST_PR_EDIT"
HOOK_NAME = "gh-write-verification"

RULE_BROKEN_PR_EDIT = f"{HOOK_NAME}.broken-pr-edit"
RULE_SILENCED_MUTATION = f"{HOOK_NAME}.silenced-mutation"
RULE_SELF_MATCHING_PROCESS = f"{HOOK_NAME}.self-matching-process"
RULE_PIPED_AWAY_EXIT_CODE = f"{HOOK_NAME}.piped-away-exit-code"
RULE_UNVERIFIED_LANDING = f"{HOOK_NAME}.unverified-landing"

SHELL_LIKE_TOOL_NAMES = (
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
)

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
    r"|\bgit\s+(?:merge|rebase|cherry-pick|revert)\b(?!-)"
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
LANDING_OK_RE = re.compile(r"(?m)^\s*OK:")
VERIFY_SCRIPT_RELPATH = "gh-write-verification/verify_pr_landed_on_trunk.sh"

UNVERIFIED_MERGE_MESSAGE = (
    "gh-write-verification: this turn merged {subjects} and never checked "
    "where the merge commit landed. `gh pr merge` reporting MERGED only means "
    "the PR closed against its own base ref, which is not necessarily the "
    "trunk -- a PR whose base was never retargeted merges into its own stack "
    "branch and reports exactly the same MERGED state.\n"
    "Run the end-to-end check before finishing:\n"
    '  bash "$HOME/.claude/hooks/' + VERIFY_SCRIPT_RELPATH + '" --repo <owner/name> <pr-number>\n'
    "It resolves the merge commit through `gh api` and asserts "
    "`git merge-base --is-ancestor <merge_commit> origin/<trunk>` from a clone "
    "of that repo. Exit 0 (OK) is the only pass; exit 1 (FAIL) means merged "
    "but not on the trunk, and exit 3 (UNCHECKED) means the check could not "
    "run and proves nothing."
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


SHELL_NAMES = frozenset({"bash", "zsh", "sh", "dash", "ksh"})
PIPE_TOKENS = frozenset({"|", "|&"})
SEPARATOR_CHARS = frozenset("();&|")
HEAD_KEYWORDS = frozenset({"!", "{", "}", "do", "then", "else", "elif", "if", "while", "until", "time"})
HEAD_WRAPPERS = frozenset({"command", "env", "nice", "nohup", "sudo", "exec"})
PIPEFAIL_RE = re.compile(r"^(?:set|setopt)$")
STATUS_ARRAY = {"bash": "PIPESTATUS", "zsh": "pipestatus"}
LEX_INCOMPLETE = frozenset({"No closing quotation", "No escaped character"})

PIPED_MESSAGE = (
    "gh-write-verification: a pipe throws away this state-changing command's "
    "exit code:\n{hits}\n"
    "A pipeline reports only its last stage's status, so `$?` after it is the "
    "reader's 0 even when the write failed -- a push can print `failed to push` "
    "and still report `push=0`. Run `set -o pipefail` first (bash and zsh both "
    "accept it), or read the write's own status on the very next command: "
    "`${{pipestatus[1]}}` in zsh, `${{PIPESTATUS[0]}}` in bash. Or send the "
    "output to a file and read both: `cmd > /tmp/out.log 2>&1; echo rc=$?; "
    "tail -2 /tmp/out.log`.{zsh_note}"
)
ZSH_PIPESTATUS_NOTE = (
    "\n`${PIPESTATUS[0]}` is empty in zsh, which is the shell running this "
    "command, so reading it checks nothing."
)


class PipeScan:
    def __init__(self) -> None:
        self.hits: list[str] = []
        self.unchecked: list[str] = []
        self.zsh_pipestatus = False


def shell_dialect(environ: dict) -> str:
    name = os.path.basename(str(environ.get("SHELL") or ""))
    return name if name in STATUS_ARRAY else "bash"


def _lex(text: str) -> list[str] | None:
    lexer = shlex.shlex(text, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        return list(lexer)
    except ValueError as exc:
        if str(exc) in LEX_INCOMPLETE:
            return None
        raise


def _logical_lines(script: str) -> list[str]:
    lines: list[str] = []
    pending = ""
    for raw in script.split("\n"):
        if raw.endswith("\\") and not raw.endswith("\\\\"):
            pending += raw[:-1] + " "
            continue
        lines.append(pending + raw)
        pending = ""
    if pending:
        lines.append(pending)
    return lines


def _heredoc_opens(tokens: list[str]) -> list[tuple[str, bool, str | None]]:
    """Each heredoc a line opens: its delimiter, tab stripping, and the dialect that runs its body.

    A body runs as shell only when a shell reads it on stdin or it is written to a
    `.sh` file; any other body (Python, a PR description) is data and is skipped.
    """
    opens = []
    for index, token in enumerate(tokens[:-1]):
        if token not in ("<<", "<<-"):
            continue
        delimiter = tokens[index + 1]
        strip_tabs = token == "<<-"
        if delimiter.startswith("-"):
            delimiter, strip_tabs = delimiter[1:], True
        words = tokens[:index]
        dialect = None
        for word in words:
            base = os.path.basename(word)
            if base in SHELL_NAMES:
                dialect = base
            elif word.endswith(".sh"):
                dialect = "bash"
        if not dialect:
            for word in tokens[index + 2:]:
                if word.endswith(".sh"):
                    dialect = "bash"
        if delimiter:
            opens.append((delimiter, strip_tabs, dialect))
    return opens


def _shell_units(script: str, dialect: str) -> tuple[list[tuple[list[str], str]], list[str]]:
    """Token lines of the script and of every shell-run heredoc or `-c` script inside it."""
    units: list[tuple[list[str], str]] = []
    unchecked: list[str] = []
    waiting: list[tuple[str, bool, str | None]] = []
    body: list[str] = []
    open_quote: str | None = None
    for line in _logical_lines(script):
        if waiting:
            delimiter, strip_tabs, body_dialect = waiting[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate.strip() != delimiter:
                body.append(line)
                continue
            waiting.pop(0)
            if body_dialect:
                inner, inner_unchecked = _shell_units("\n".join(body), body_dialect)
                units.extend(inner)
                unchecked.extend(inner_unchecked)
            body = []
            continue
        text = line if open_quote is None else open_quote + "\n" + line
        tokens = _lex(text)
        if tokens is None:
            open_quote = text
            continue
        open_quote = None
        waiting.extend(_heredoc_opens(tokens))
        units.append((tokens, dialect))
        for index, token in enumerate(tokens[:-2]):
            base = os.path.basename(token)
            if base in SHELL_NAMES and tokens[index + 1] in ("-c", "-lc", "-ec", "-ic"):
                inner, inner_unchecked = _shell_units(tokens[index + 2], base)
                units.extend(inner)
                unchecked.extend(inner_unchecked)
    if open_quote is not None:
        unchecked.append(f"unbalanced quote in: {open_quote.strip()[:120]}")
    if waiting:
        unchecked.append(f"heredoc never closed: {waiting[0][0]}")
    return units, unchecked


def _is_separator(token: str) -> bool:
    return bool(token) and set(token) <= SEPARATOR_CHARS and token not in PIPE_TOKENS and not token.endswith("|")


def _is_pipe(token: str) -> bool:
    return token in PIPE_TOKENS or (bool(token) and set(token) <= SEPARATOR_CHARS and token.endswith("|") and "||" not in token)


def _command_words(words: list[str]) -> list[str]:
    index = 0
    while index < len(words):
        word = words[index]
        if word in HEAD_KEYWORDS or _is_assignment(word) or set(word) <= set("(){}"):
            index += 1
        elif word in HEAD_WRAPPERS:
            index += 1
        elif word == "timeout" and index + 1 < len(words):
            index += 2
        else:
            break
    return words[index:]


def _is_assignment(word: str) -> bool:
    name, eq, _ = word.partition("=")
    return bool(eq) and bool(name) and name.replace("_", "a").isalnum() and not name[0].isdigit()


def _sets_pipefail(words: list[str]) -> bool:
    command = _command_words(words)
    return bool(command) and bool(PIPEFAIL_RE.match(command[0])) and "pipefail" in " ".join(command[1:])


def _pipelines(units: list[tuple[list[str], str]]) -> list[tuple[list[list[str]], str]]:
    """Every pipeline in order, each a list of stages (word lists), tagged with its dialect."""
    found: list[tuple[list[list[str]], str]] = []
    for tokens, dialect in units:
        stages: list[list[str]] = [[]]
        for token in tokens + [";"]:
            if _is_pipe(token):
                stages.append([])
            elif _is_separator(token):
                if any(stages):
                    found.append(([s for s in stages if s], dialect))
                stages = [[]]
            else:
                stages[-1].append(token)
    return found


REDIRECT_GLUE_RE = re.compile(r"\b(\d) (>&|>>|>|<) ?(?=\S)")
HIT_WIDTH = 100


def _render(words: list[str]) -> str:
    text = REDIRECT_GLUE_RE.sub(r"\1\2", " ".join(words))
    return text if len(text) <= HIT_WIDTH else text[:HIT_WIDTH] + "..."


def piped_away_mutations(raw_text: str, dialect: str) -> PipeScan:
    """Mutations whose exit code a later pipeline stage replaces, with no pipefail or status-array read.

    Three outcomes: `hits` found, neither (clean), or `unchecked` when part of
    the command could not be lexed.
    """
    scan = PipeScan()
    units, scan.unchecked = _shell_units(unescape_payload(raw_text), dialect)
    pipelines = _pipelines(units)
    pipefail_by_dialect: set[str] = set()
    for position, (stages, shell) in enumerate(pipelines):
        if len(stages) == 1 and _sets_pipefail(stages[0]):
            pipefail_by_dialect.add(shell)
            continue
        if shell in pipefail_by_dialect or len(stages) < 2:
            continue
        for stage_index, stage in enumerate(stages[:-1]):
            command = _command_words(stage)
            if not command or not MUTATING_RE.match(" ".join(command)):
                continue
            following = " ".join(" ".join(s) for s in pipelines[position + 1][0]) if position + 1 < len(pipelines) else ""
            if STATUS_ARRAY.get(shell, "PIPESTATUS") in following and shell in STATUS_ARRAY:
                continue
            if shell == "zsh" and "PIPESTATUS" in following:
                scan.zsh_pipestatus = True
            hit = f"{_render(command)} | {_render(stages[stage_index + 1])}"
            if hit not in scan.hits:
                scan.hits.append(hit)
    return scan


def piped_message(scan: PipeScan) -> str:
    return PIPED_MESSAGE.format(
        hits="\n".join(f"    {hit}" for hit in scan.hits),
        zsh_note=ZSH_PIPESTATUS_NOTE if scan.zsh_pipestatus else "",
    )


CommandRecord = Tuple[str, Optional[str]]


def _proves_landing(command: str, number: str | None, result: str | None) -> bool:
    """True when this command checks where a merge commit actually landed.

    An invocation of the shipped verification script must name the PR it is
    vouching for, and the paired tool result must report the passing verdict.
    """
    command = command or ""
    if not LANDING_PROOF_RE.search(command):
        return False
    if "verify_pr_landed_on_trunk" in command and number is not None:
        if number not in command:
            return False
    return bool(result and LANDING_OK_RE.search(result))


def _command_text(record: str | CommandRecord) -> str:
    return record[0] if isinstance(record, tuple) else record


def _command_result(record: str | CommandRecord) -> str | None:
    return record[1] if isinstance(record, tuple) else None


def merges_missing_landing_proof(commands: list[str | CommandRecord]) -> list[str]:
    """PR subjects merged in this turn with no landing check run afterwards.

    Returns the merged subjects (a PR number, or "the current branch's PR"
    when the command omitted one) when no later command in the turn proves
    the merge commit reached the trunk. Empty when nothing merged or when the
    proof ran after the merge.
    """
    subjects: list[str] = []
    for index, record in enumerate(commands):
        command = _command_text(record)
        match = GH_PR_MERGE_RE.search(command or "")
        if not match:
            continue
        number = match.group("number")
        subject = f"PR #{number}" if number else "the current branch's PR"
        if any(
            _proves_landing(_command_text(later), number, _command_result(later))
            for later in commands[index + 1:]
        ):
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


def _tool_result_text(block: dict) -> str:
    content = block.get("content")
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


def bash_commands_this_turn(raw_lines) -> list[CommandRecord]:
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
    records = parsed[turn_start:]
    results: dict[str, str] = {}
    for data in records:
        message = data.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id")
            if tool_id:
                results[str(tool_id)] = _tool_result_text(block)
    commands: list[CommandRecord] = []
    for data in records:
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
                tool_id = block.get("id") or block.get("tool_use_id")
                result = results.get(str(tool_id)) if tool_id else None
                commands.append((str(tool_input.get("command") or ""), result))
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


def detect(event: dict[str, object]) -> list[Finding]:
    """SDK detector entrypoint: return findings, leaving mode/output to runtime."""
    hook_event_name = _hook_event_name(event)
    if hook_event_name == "PreToolUse" or hook_event_name == "preToolUse":
        return _detect_pretooluse(event)
    if hook_event_name in {"Stop", "SubagentStop", "stop"}:
        return _detect_stop(event)
    if _tool_name(event) in SHELL_LIKE_TOOL_NAMES:
        return _detect_pretooluse(event)
    if event.get("transcript_path") or event.get("transcriptPath"):
        return _detect_stop(event)
    return []


def _detect_pretooluse(event: dict[str, object]) -> list[Finding]:
    if _tool_name(event) not in SHELL_LIKE_TOOL_NAMES:
        return []

    raw = str(event.get("_raw_payload") or "")
    findings: list[Finding] = []

    pr_edit = broken_pr_edit(raw)
    if pr_edit:
        findings.append(_finding(RULE_BROKEN_PR_EDIT, pr_edit, PR_EDIT_MESSAGE, pr_edit))

    silenced = silenced_mutations(raw)
    if silenced:
        findings.append(
            _finding(RULE_SILENCED_MUTATION, "\n".join(silenced), silenced_message(silenced), "\n".join(silenced))
        )

    waits = self_matching_process_waits(raw)
    if waits:
        findings.append(
            _finding(RULE_SELF_MATCHING_PROCESS, "\n".join(waits), self_match_message(waits), "\n".join(waits))
        )

    command = _command_string(event)
    if isinstance(command, str):
        scan = piped_away_mutations(command, shell_dialect(os.environ))
        if scan.hits:
            findings.append(
                _finding(
                    RULE_PIPED_AWAY_EXIT_CODE,
                    "\n".join(scan.hits),
                    piped_message(scan),
                    "\n".join(scan.hits),
                )
            )
        if scan.unchecked and not findings:
            _set_unchecked(event, "; ".join(scan.unchecked))
    elif not findings:
        _set_unchecked(event, "no command string in tool_input")

    return findings


def _detect_stop(event: dict[str, object]) -> list[Finding]:
    if event.get("stop_hook_active"):
        return []
    transcript_path = event.get("transcript_path") or event.get("transcriptPath") or ""
    if not transcript_path:
        return []
    try:
        with open(str(transcript_path), encoding="utf-8") as handle:
            commands = bash_commands_this_turn(handle)
    except OSError:
        return []
    subjects = merges_missing_landing_proof(commands)
    if not subjects:
        return []
    subject_text = ", ".join(subjects)
    return [
        _finding(
            RULE_UNVERIFIED_LANDING,
            subject_text,
            unverified_merge_message(subjects),
            subject_text,
        )
    ]


def _hook_event_name(event: dict[str, object]) -> str:
    for key in ("hook_event_name", "hookEventName", "event"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return ""


def _tool_name(event: dict[str, object]) -> str:
    for key in ("tool_name", "toolName", "tool", "name"):
        value = event.get(key)
        if isinstance(value, str):
            return value
    return ""


def _command_string(event: dict[str, object]) -> str | None:
    tool_input = event.get("tool_input") or event.get("toolInput") or {}
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command") or tool_input.get("cmd")
    return command if isinstance(command, str) else None


def _finding(rule_id: str, subject: str, message: str, evidence: str) -> Finding:
    return Finding(
        rule_id=rule_id,
        subject=f"sha256:{_digest(subject)}",
        message=message,
        evidence=evidence,
    )


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _set_unchecked(event: dict[str, object], reason: str) -> None:
    event["_payload_error"] = f"pipe exit-code check unchecked, allowing: {reason}"
