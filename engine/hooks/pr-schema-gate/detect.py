"""pr-schema-gate: enforce the repo's PR style on direct PR text writes, never block.

Decisions are made on `shell_model.Command` values (the words of each
command the shell will run), not on the raw payload text. A direct write is
`gh pr create`, `gh pr edit` with a body flag, or `gh api` on a `pulls`
endpoint with a `body=` field. When the text comes from a file, the hook
runs the repo's own `scripts/validate-pr-body.mjs` on that file and hands the
result to the agent: silent when the text passes, the validator's error
lines when it fails, and an explicit "could not check" with the reason when
the check cannot run (inline text, a missing or unreadable file, no
validator, a crash, a timeout, a command the parser cannot read). The
command runs in every case. The rules live in the repo's validator, so this
hook never carries a second copy of them.

`mergify stack push` publishes PRs with a bare body, and the style body only
lands when a follow-up writes it. The push arms a bounded pending flag and
reminds the agent which follow-up is owed; a later push while the flag is
armed repeats the reminder. `scripts/create-pr.mjs`, or a direct body write
whose file passes the validator, clears it. A repo with no
scripts/create-pr.mjs is out of scope entirely.

PreToolUse fires before the command, so the hook cannot see the push's exit
status; pending is recorded when the push is let through. A push that then
fails leaves one stale reminder, cleared by the next follow-up or the TTL.
The state is bounded three ways: one small JSON file per repo root holding a
single timestamp, written outside the worktree so it never dirties
`git status`; a TTL, so a forgotten flag cannot nag forever; and fail-open
reads and writes, so missing, unreadable, malformed, future-dated or expired
state all mean "nothing owed".

Incident: PR #10737 (Neko-Catpital-Labs/Invoker) was left with a bare
`Depends-On: #10736` body for ~2 hours because a Codex session ran
`mergify stack push` and never followed up with `create-pr.mjs
--update-existing` before moving on.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass

from shell_model import Command

VALIDATOR_RELATIVE_PATH = os.path.join("scripts", "validate-pr-body.mjs")
VALIDATOR_TIMEOUT_SECONDS = 3.0
VALIDATOR_OUTPUT_MAX_LINES = 20

PENDING_TTL_SECONDS = 2 * 60 * 60
STATE_DIR_ENV = "PR_SCHEMA_GATE_STATE_DIR"
GITHUB_CHECKOUTS_ROOT_ENV = "PR_SCHEMA_GATE_CHECKOUTS_ROOT"

STACK_PUSH_LABEL = "mergify stack push"

STYLE_FAILED_MESSAGE = (
    "pr-schema-gate: the PR text in {path} does not follow this repo's PR style "
    "(scripts/validate-pr-body.mjs exited 1). The command is not blocked. Fix the "
    "file and write it to the PR again so the live PR matches:\n{details}"
)
STYLE_UNCHECKED_MESSAGE = (
    "pr-schema-gate: could not check this PR text against the repo's PR style: "
    "{reason}. The command is not blocked. Check it yourself with "
    "`node scripts/validate-pr-body.mjs --body-file <file>`, or write it with "
    "`node scripts/create-pr.mjs`, which checks before writing."
)
UNPARSEABLE_MESSAGE = (
    "pr-schema-gate: could not parse this shell command, so any PR text it "
    "writes was not checked against the repo's PR style. The command is not blocked."
)
FOLLOWUP_OWED_MESSAGE = (
    "pr-schema-gate: '{cmd}' publishes PRs with a bare body. Follow up on each "
    "PR with `node scripts/create-pr.mjs --title \"...\" --base <branch> "
    "--body-file <file> --update-existing`, or a direct body write whose file "
    "passes scripts/validate-pr-body.mjs. Either one clears this reminder."
)
FOLLOWUP_STILL_OWED_MESSAGE = (
    "pr-schema-gate: the follow-up for the last '{cmd}' in this repository has "
    "not run yet, so those PRs may still have a bare body. The command is not "
    "blocked. Run `node scripts/create-pr.mjs ... --update-existing`, or a "
    "direct body write whose file passes scripts/validate-pr-body.mjs."
)

GH_BODY_FILE_FLAGS = frozenset({"--body-file", "-F"})
GH_BODY_INLINE_FLAGS = frozenset({"--body", "-b"})
GH_REPO_FLAGS = frozenset({"--repo", "-R"})
GH_API_VALUE_FLAGS = frozenset({
    "-X", "--method", "-H", "--header", "--input", "-q", "--jq", "-t",
    "--template", "--hostname", "--cache", "-p", "--preview",
})
GH_API_FIELD_FLAGS = frozenset({"-f", "--raw-field", "-F", "--field"})
GH_API_FILE_FIELD_FLAGS = frozenset({"-F", "--field"})


@dataclass(frozen=True)
class PrTextWrite:
    label: str
    body_ref: str | None
    repo_spec: str | None
    command: Command

    @property
    def cwd(self) -> str:
        return self.command.cwd

    @property
    def body_file(self) -> str | None:
        return self.command.expand(self.body_ref) if self.body_ref else None


def _flag_values(args: tuple[str, ...], names: frozenset[str]) -> list[str]:
    values = []
    for index, arg in enumerate(args):
        if arg in names and index + 1 < len(args):
            values.append(args[index + 1])
            continue
        name, eq, value = arg.partition("=")
        if eq and name in names:
            values.append(value)
    return values


def _has_flag(args: tuple[str, ...], names: frozenset[str]) -> bool:
    return any(arg in names or arg.partition("=")[0] in names for arg in args)


def _program(argv: tuple[str, ...]) -> str:
    return os.path.basename(argv[0]) if argv else ""


def _gh_pr_write(command: Command) -> PrTextWrite | None:
    argv = command.argv
    if len(argv) < 3 or argv[1] != "pr" or argv[2] not in ("create", "edit"):
        return None
    args = argv[3:]
    body_files = _flag_values(args, GH_BODY_FILE_FLAGS)
    has_body = bool(body_files) or _has_flag(args, GH_BODY_INLINE_FLAGS)
    if argv[2] == "edit" and not has_body:
        return None
    body_file = body_files[-1] if body_files and body_files[-1] != "-" else None
    repos = _flag_values(args, GH_REPO_FLAGS)
    label = "gh pr create" if argv[2] == "create" else "gh pr edit --body"
    return PrTextWrite(label, body_file, repos[-1] if repos else None, command)


def _gh_api_endpoint(args: tuple[str, ...]) -> str | None:
    skip = False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg in GH_API_VALUE_FLAGS or arg in GH_API_FIELD_FLAGS:
            skip = True
            continue
        if not arg.startswith("-"):
            return arg
    return None


def _gh_api_write(command: Command) -> PrTextWrite | None:
    argv = command.argv
    if len(argv) < 2 or argv[1] != "api":
        return None
    args = argv[2:]
    endpoint = _gh_api_endpoint(args)
    if endpoint is None or "pulls" not in endpoint.strip("/").split("/"):
        return None
    body_file = None
    has_body = False
    for index, arg in enumerate(args):
        name, eq, inline = arg.partition("=")
        if eq and name in GH_API_FIELD_FLAGS:
            flag, value = name, inline
        elif arg in GH_API_FIELD_FLAGS and index + 1 < len(args):
            flag, value = arg, args[index + 1]
        else:
            continue
        if not value.startswith("body="):
            continue
        has_body = True
        raw = value[len("body="):]
        if flag in GH_API_FILE_FIELD_FLAGS and raw.startswith("@") and raw != "@-":
            body_file = raw[1:]
    if not has_body:
        return None
    return PrTextWrite("gh api pulls body", body_file, _api_repo_spec(endpoint), command)


def _api_repo_spec(endpoint: str) -> str | None:
    """`owner/repo` from a `repos/<owner>/<repo>/...` endpoint; None for gh's `{owner}/{repo}` placeholders."""
    parts = endpoint.strip("/").split("/")
    if len(parts) < 3 or parts[0] != "repos" or parts[1].startswith("{") or parts[2].startswith("{"):
        return None
    return f"{parts[1]}/{parts[2]}"


def classify_pr_text_write(command: Command) -> PrTextWrite | None:
    """Return the direct PR text write this command performs, or None."""
    if _program(command.argv) != "gh":
        return None
    return _gh_pr_write(command) or _gh_api_write(command)


def is_stack_push(command: Command) -> bool:
    """A real `mergify stack push`. A `--dry-run` publishes nothing and never arms state."""
    argv = command.argv
    words = argv[1:] if _program(argv) in ("npx", "pnpm", "yarn") else argv
    if len(words) < 3 or os.path.basename(words[0]) != "mergify" or tuple(words[1:3]) != ("stack", "push"):
        return False
    return "--dry-run" not in words


def is_create_pr_followup(command: Command) -> bool:
    """The repo's own create-pr.mjs, which validates the body before it writes."""
    argv = command.argv
    if _program(argv) == "create-pr.mjs":
        return True
    return _program(argv) == "node" and len(argv) > 1 and os.path.basename(argv[1]) == "create-pr.mjs"


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


def scope_root(cwd: str, repo_spec: str | None) -> str | None:
    """The repo this command acts on, when that repo has scripts/create-pr.mjs.

    A `--repo` naming a repo with no local checkout resolves to None: out of
    scope, never a guess.
    """
    if repo_spec is not None:
        sibling = sibling_repo_dir(repo_spec)
        return repo_root_with_create_pr_tool(sibling) if sibling else None
    return repo_root_with_create_pr_tool(cwd)


def check_body_file(repo_root: str, body_path: str | None, start_dir: str) -> tuple[str, str]:
    """Run the repo's validator on the PR text. Return (outcome, detail).

    Three outcomes: "clean" (validator exit 0), "failed" (exit 1, detail is
    its error lines) and "unchecked" (the check could not run, detail is why).
    "unchecked" is never reported as clean.
    """
    if body_path is None:
        return "unchecked", "the PR text is inline or piped, not in a file the hook can read"
    path = body_path if os.path.isabs(body_path) else os.path.join(start_dir, body_path)
    if not os.path.isfile(path):
        return "unchecked", f"body file not found or not a regular file: {path}"
    try:
        with open(path, "r", encoding="utf-8") as fh:
            fh.read(1)
    except (OSError, UnicodeDecodeError) as exc:
        return "unchecked", f"body file unreadable: {path}: {exc}"
    validator = os.path.join(repo_root, VALIDATOR_RELATIVE_PATH)
    if not os.path.isfile(validator):
        return "unchecked", f"this repo has no {VALIDATOR_RELATIVE_PATH}"
    try:
        proc = subprocess.run(
            ["node", validator, "--body-file", path],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=VALIDATOR_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return "unchecked", "node is not on PATH, so the validator could not run"
    except subprocess.TimeoutExpired:
        return "unchecked", f"the validator timed out after {VALIDATOR_TIMEOUT_SECONDS:g}s"
    lines = [line for line in (proc.stdout + "\n" + proc.stderr).splitlines() if line.strip()]
    lines = lines[:VALIDATOR_OUTPUT_MAX_LINES]
    if proc.returncode == 0:
        return "clean", ""
    if proc.returncode == 1:
        return "failed", "\n".join(lines)
    return "unchecked", f"the validator crashed (exit {proc.returncode}): " + " | ".join(lines[:3])


def style_message(outcome: str, detail: str, body_path: str | None) -> str | None:
    if outcome == "failed":
        return STYLE_FAILED_MESSAGE.format(path=body_path, details=detail)
    if outcome == "unchecked":
        return STYLE_UNCHECKED_MESSAGE.format(reason=detail)
    return None


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
    timestamp is reported as "no follow-up owed". A future-dated stamp is
    treated the same as an expired one -- both mean the state is stale.
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

    An unwritable state directory is reported on stderr and then ignored.
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
    """Drop the owed follow-up. A missing file is already the cleared state.

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


def followup_message(already_owed: bool) -> str:
    template = FOLLOWUP_STILL_OWED_MESSAGE if already_owed else FOLLOWUP_OWED_MESSAGE
    return template.format(cmd=STACK_PUSH_LABEL)
