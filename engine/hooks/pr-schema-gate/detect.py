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
body. A repo with no scripts/create-pr.mjs gets no block at all (fail-open
-- we have no sanctioned tool to point to there).

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

import os
import re

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
