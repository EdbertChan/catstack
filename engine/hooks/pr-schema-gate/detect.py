"""pr-schema-gate: block direct `gh pr create` / `gh pr edit --body*`.

Both commands write a PR title/body straight to GitHub, skipping the
make-pr/draft-pr schema (Summary, Review Claim, Review Lane, Safety
Invariant, ...) and its `validate-pr-body.mjs` gate. `scripts/create-pr.mjs`
is the sanctioned path: it validates the body, then writes via
`gh api repos/.../pulls` (POST) / `gh api .../pulls/<n>` (PATCH) -- neither
of which this hook matches, so the sanctioned tool is never self-blocked.

`mergify stack push` is intentionally NOT blocked: create-pr.mjs's own docs
name it as legitimate step 1 (publish the branch), with `create-pr.mjs
--update-existing` as the required step 2 that actually writes the schema
body. It does, however, arm a bounded pending-follow-up flag: the *next*
publication action is blocked until create-pr.mjs has run (see "Stack
follow-up guard" below). A repo with no scripts/create-pr.mjs gets no block
at all (fail-open -- we have no sanctioned tool to point to there).

STACK FOLLOW-UP GUARD: pushing is allowed; forgetting the follow-up is not.
Once a publication action has been let through in a repo, the *next*
publication action there is blocked until `scripts/create-pr.mjs` has run,
which clears the requirement. PreToolUse fires before the command, so the
hook cannot see the push's exit status; pending is recorded when the push is
allowed, treating "we let the publish through" as "the publish happened". A
push that then fails leaves one stale flag, cleared by the next
create-pr.mjs run or by the TTL -- over-requiring the follow-up is the safe
direction, under-requiring it is the incident below. The state is bounded
three ways: one small JSON file per repo root holding a single timestamp,
written outside the worktree so it never dirties `git status`; a TTL, so a
forgotten flag cannot wedge a repo; and fail-open reads and writes, so
missing, unreadable, malformed, future-dated or expired state all mean
"nothing owed", never "blocked".

Incident: PR #10737 (Neko-Catpital-Labs/Invoker) was left with a bare
`Depends-On: #10736` body for ~2 hours because a Codex session ran
`mergify stack push` and never followed up with `create-pr.mjs
--update-existing` before moving on.

KNOWN FALSE POSITIVE: matching is a raw-text regex over the whole hook
payload, not a shell parser, so a Bash command whose text merely *contains*
"gh pr create"/"gh pr edit --body" as inert data -- a heredoc, a quoted
string, a grep pattern, this file's own tests -- blocks too, identically to
a real invocation. Confirmed live: piping a JSON test payload containing
that text through this hook's own stdin (to smoke-test it) tripped the
gate on the *outer* diagnostic command, not on any real `gh` call. Most
likely to bite when testing or documenting this exact hook. If it fires on
something that isn't actually running `gh`, that's this known limitation,
not a new bug -- split the offending text into a file write instead of an
inline heredoc/string.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time

# Plain \b word-boundary match, deliberately NOT narrowed to exclude a
# preceding quote/brace/colon. A real Claude/Cursor PreToolUse payload wraps
# the command in JSON exactly the same way a self-referential false positive
# would (`"command":"gh pr create ..."` either way) -- there is no raw-text
# shape that distinguishes "the command about to run" from "a string that
# looks like one" without a real shell parser. Tried excluding quote-adjacent
# matches; confirmed live it also silences the real case (a JSON-wrapped
# tool_input.command is *always* quote-adjacent), so reverted. See KNOWN
# FALSE POSITIVE in the module docstring instead of pretending this is exact.
GH_PR_CREATE = re.compile(r"\bgh\s+pr\s+create\b")
GH_PR_EDIT_BODY = re.compile(r"\bgh\s+pr\s+edit\b[^\n]*(--body\b|--body-file\b)")

BLOCK_MESSAGE = (
    "Direct '{cmd}' bypasses the make-pr/draft-pr PR-body schema (Summary, "
    "Review Claim, Review Lane, Safety Invariant, Slice Rationale, Non-goals, "
    "Test Plan, Revert Plan) and its validate-pr-body.mjs gate. Use "
    "`node scripts/create-pr.mjs --title \"...\" --base <branch> "
    "--body-file <file> [--update-existing]` instead -- it validates the body "
    "before writing to GitHub via `gh api`. If you already ran `mergify stack "
    "push`, this is the required follow-up step, not an alternative to it."
)


_LEADING_CD = re.compile(r'^\s*cd\s+(?P<path>"[^"]+"|\'[^\']+\'|\S+)\s*(?:&&|;)')
_NESTED_WORKDIR = re.compile(
    r'["\']workdir["\']\s*:\s*(?P<quote>["\'])(?P<path>.*?)(?P=quote)'
)


def effective_start_dir(cwd: str, command: str) -> str:
    """A command that opens with `cd <dir> &&`/`cd <dir>;` targets <dir>, not
    the hook payload's `cwd` (the session's launch directory, unaffected by
    a `cd` written *inside* the command text). Caught live: `cd catstack &&
    gh pr edit ...` still evaluated against the session's Invoker cwd
    without this, since PreToolUse fires before the command runs and can't
    otherwise know a `cd` is coming.
    """
    m = _LEADING_CD.match(command)
    if not m:
        return cwd
    target = m.group("path").strip("'\"")
    return target if os.path.isabs(target) else os.path.join(cwd, target)


def effective_tool_start_dir(cwd: str, tool_input: dict) -> str:
    """Resolve the filesystem target of direct and Codex-wrapped shell calls.

    Codex's orchestration tool can put ``workdir`` inside the JavaScript held
    by ``tool_input.input`` instead of exposing it as a top-level hook field.
    That target must outrank the session launch cwd or the gate can apply one
    repository's publication policy to a command running in another.
    """
    command = str(tool_input.get("command") or tool_input.get("cmd") or "")
    explicit = tool_input.get("workdir") or tool_input.get("cwd")
    if not explicit:
        source = str(tool_input.get("input") or "")
        match = _NESTED_WORKDIR.search(source)
        explicit = match.group("path") if match else ""
    base = str(explicit or cwd)
    if not os.path.isabs(base):
        base = os.path.join(cwd, base)
    return effective_start_dir(base, command)


_REPO_FLAG = re.compile(
    r"\bgh\s+(?:pr|issue)\s+(?:edit|create)\b[^\n]*?"
    r"(?:--repo(?:=|\s+)|-R\s+)(?P<spec>\"[^\"]+\"|'[^']+'|\S+)"
)

GITHUB_CHECKOUTS_ROOT_ENV = "PR_SCHEMA_GATE_CHECKOUTS_ROOT"


def find_repo_flag(raw_text: str) -> str | None:
    match = _REPO_FLAG.search(raw_text)
    if not match:
        return None
    spec = match.group("spec").strip("'\"")
    return spec or None


def github_checkouts_root() -> str:
    return os.environ.get(GITHUB_CHECKOUTS_ROOT_ENV) or os.path.join(
        os.path.expanduser("~"), "Documents", "GitHub"
    )


def sibling_repo_dir(repo_spec: str) -> str | None:
    name = repo_spec.strip().rstrip("/").split("/")[-1] if repo_spec else ""
    if not name:
        return None
    candidate = os.path.join(github_checkouts_root(), name)
    return candidate if os.path.isdir(candidate) else None


def repo_root_with_create_pr_tool(start_dir: str) -> str | None:
    """Walk up from start_dir; return the dir containing scripts/create-pr.mjs, or None.

    Stops at a .git boundary (repo root) or filesystem root, whichever comes first.
    """
    cur = os.path.abspath(start_dir) if start_dir else os.getcwd()
    for _ in range(12):
        if os.path.isfile(os.path.join(cur, "scripts", "create-pr.mjs")):
            return cur
        if os.path.isdir(os.path.join(cur, ".git")):
            return None
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def find_blocked_command(raw_text: str) -> str | None:
    """Regex-match the raw hook payload text for a schema-bypassing command.

    Matching the whole raw payload text (not a parsed tool_input field) is
    deliberate: Claude/Cursor put the shell command in tool_input.command,
    but Codex's exec tool wraps it inside a JS-source `input` string
    (`tools.exec_command({cmd: "..."})`). One substring/regex pass over the
    raw text works across all three without per-harness field parsing.
    """
    if GH_PR_CREATE.search(raw_text):
        return "gh pr create"
    if GH_PR_EDIT_BODY.search(raw_text):
        return "gh pr edit --body"
    return None


def block_message_for(cmd: str) -> str:
    return BLOCK_MESSAGE.format(cmd=cmd)


MERGIFY_STACK_PUSH = re.compile(r"\bmergify\s+stack\s+push\b")
CREATE_PR_TOOL = re.compile(r"\bcreate-pr\.mjs\b")

PENDING_TTL_SECONDS = 2 * 60 * 60

STATE_DIR_ENV = "PR_SCHEMA_GATE_STATE_DIR"

FOLLOWUP_REQUIRED_MESSAGE = (
    "'{cmd}' already published a branch in this repository and the required "
    "follow-up never ran, so another publication action is blocked. Run "
    "`node scripts/create-pr.mjs --title \"...\" --base <branch> --body-file "
    "<file> --update-existing` first -- it validates the PR body against the "
    "make-pr/draft-pr schema (Summary, Review Claim, Review Lane, Safety "
    "Invariant, Slice Rationale, Non-goals, Test Plan, Revert Plan) before "
    "writing to GitHub. Running it clears this state. Incident this prevents: "
    "PR #10737 sat for ~2 hours with a bare 'Depends-On:' body after exactly "
    "this sequence."
)


def find_publication_command(raw_text: str) -> str | None:
    """Return the branch-publishing command in the payload text, or None.

    Publication actions are allowed to run -- they are only the events that
    arm and re-check the follow-up requirement.
    """
    if MERGIFY_STACK_PUSH.search(raw_text):
        return "mergify stack push"
    return None


def is_sanctioned_followup(raw_text: str) -> bool:
    """True when the payload invokes the repo's validated create-pr.mjs path."""
    return bool(CREATE_PR_TOOL.search(raw_text))


def pending_state_path(repo_root: str) -> str:
    """Per-repo state file, keyed by a digest of the repo root's absolute path.

    Kept in the temp dir (or STATE_DIR_ENV) rather than inside the repo, so
    the guard never adds an untracked file to the worktree it is policing.
    """
    base = os.environ.get(STATE_DIR_ENV) or os.path.join(
        tempfile.gettempdir(), "catstack-pr-schema-gate"
    )
    key = hashlib.sha1(os.path.abspath(repo_root).encode("utf-8")).hexdigest()[:16]
    return os.path.join(base, key + ".json")


def read_pending(repo_root: str, now: float | None = None) -> float | None:
    """Return the pending timestamp, or None if absent, expired or malformed.

    Fail-open by construction: anything not readable as a fresh numeric
    timestamp is reported as "no follow-up owed". A corrupt state file must
    never be able to block a command. A future-dated stamp is treated the
    same as an expired one -- both mean the state is stale, not live.
    """
    now = time.time() if now is None else now
    try:
        with open(pending_state_path(repo_root), "r", encoding="utf-8") as fh:
            record = json.load(fh)
        stamp = record["pending_since"]
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)):
            return None
        stamp = float(stamp)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None
    if stamp > now or now - stamp > PENDING_TTL_SECONDS:
        return None
    return stamp


def mark_pending(repo_root: str, now: float | None = None) -> None:
    """Record that a publication action ran and its follow-up is now owed.

    An unwritable state directory is reported on stderr and then ignored:
    bookkeeping we could not persist must not block the command.
    """
    now = time.time() if now is None else now
    path = pending_state_path(repo_root)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pending_since": now, "repo": os.path.abspath(repo_root)}, fh)
    except OSError as exc:
        sys.stderr.write(f"pr-schema-gate: could not record pending state at {path}: {exc}\n")


def clear_pending(repo_root: str) -> None:
    """Drop the follow-up requirement -- the sanctioned path just ran.

    Absent state is already the cleared state, so a missing file is a no-op.
    Any other removal failure is reported and ignored; read_pending's TTL is
    the backstop.
    """
    path = pending_state_path(repo_root)
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
    except OSError as exc:
        sys.stderr.write(f"pr-schema-gate: could not clear pending state at {path}: {exc}\n")


def followup_required_message(cmd: str) -> str:
    return FOLLOWUP_REQUIRED_MESSAGE.format(cmd=cmd)
