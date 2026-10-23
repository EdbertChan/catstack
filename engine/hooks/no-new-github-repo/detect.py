"""no-new-github-repo: refuse a shell command that would create a GitHub repository.

The command is parsed into the commands it runs, and each one is judged by
its program name and parsed arguments: `gh repo create`, `gh repo fork`, a
`gh api` POST to a repo-creating path, an HTTP client POST to the same
paths on api.github.com, or a GraphQL body carrying a repository-creating
mutation. Wrapped scripts (`bash -c`, `eval`, a heredoc fed to a shell) are
parsed again. A command the hook cannot read is refused, not allowed.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk"))

from finding import Finding  # noqa: E402
from runtime import run_hook  # noqa: E402

HOOK = "no-new-github-repo"
RULE_GH_REPO_CREATE = f"{HOOK}.gh-repo-create"
RULE_GH_REPO_FORK = f"{HOOK}.gh-repo-fork"
RULE_GH_API = f"{HOOK}.gh-api-repo-create"
RULE_HTTP = f"{HOOK}.http-repo-create"
RULE_GRAPHQL = f"{HOOK}.graphql-create-repository"
RULE_UNCHECKED = f"{HOOK}.unchecked"

RULE_TEXT = (
    "No new GitHub repositories from this machine; this project stays local. "
    "Ask the user where the code should live."
)
HIT_MESSAGE = f"{HOOK}: {RULE_TEXT} Matched: {{matched}} ({{what}})."
UNCHECKED_MESSAGE = (
    f"{HOOK}: could not read the command; refusing ({{reason}}). "
    f"A check that cannot run never returns clean. {RULE_TEXT}"
)
STDIN_ERROR_KEY = "_catstack_stdin_error"
MATCH_PREVIEW_CHARS = 200
MAX_NESTING = 6

SHELL_TOOL_NAMES = frozenset({
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
})
SHELLS = frozenset({"bash", "sh", "zsh", "dash", "ksh"})
WRAPPERS = frozenset({"sudo", "env", "command", "exec", "nohup", "time", "nice", "builtin"})
HTTP_CLIENTS = frozenset({"curl", "wget", "http", "https", "xh"})
SEPARATORS = frozenset(";|&\n()`")
WRITE_METHODS = frozenset({"POST"})
GRAPHQL_MUTATIONS = ("createRepository", "cloneTemplateRepository")
ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_]\w*=")
HEREDOC_TAG_RE = re.compile(r"<<-?\s*(['\"]?)([\w.-]+)\1")
URL_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*://)?(?:[^/@\s]+@)?([^/:\s]+)(?::\d+)?(/[^\s?#]*)?", re.IGNORECASE)
GH_API_VALUE_FLAGS = frozenset({
    "-H", "--header", "--jq", "-q", "--template", "-t", "--hostname",
    "-p", "--preview", "--cache",
})
GH_API_FIELD_FLAGS = frozenset({"-f", "-F", "--field", "--raw-field"})
CURL_DATA_FLAGS = frozenset({
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode",
    "--data-ascii", "--json", "-F", "--form", "--form-string",
})
CURL_VALUE_FLAGS = frozenset({
    "-H", "--header", "-u", "--user", "-o", "--output", "-A", "--user-agent",
    "-e", "--referer", "-b", "--cookie", "-c", "--cookie-jar", "-w",
    "--write-out", "--connect-timeout", "-m", "--max-time", "--retry",
    "-x", "--proxy", "-K", "--config", "--cacert", "--cert", "--key",
    "-T", "--upload-file", "--resolve", "--interface",
})
WGET_POST_PREFIXES = ("--post-data", "--post-file", "--body-data", "--body-file")
HTTPIE_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
HTTPIE_VALUE_FLAGS = frozenset({
    "-a", "--auth", "-A", "--auth-type", "-o", "--output", "--pretty",
    "-p", "--print", "-s", "--style", "--timeout", "--cert", "--cert-key",
    "--verify", "--proxy", "--session", "--session-read-only",
})


@dataclass(frozen=True)
class Command:
    argv: tuple[str, ...]
    text: str
    stdin_text: str


@dataclass(frozen=True)
class Verdict:
    rule_id: str
    what: str
    unchecked: bool = False


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


def _unquoted_heredoc_tags(line: str) -> list[tuple[str, bool, bool]]:
    """Each heredoc the line opens: (tag, strip tabs, a shell runs the body)."""
    tags: list[tuple[str, bool, bool]] = []
    quote = ""
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif line.startswith("<<", index) and not line.startswith("<<<", index):
            match = HEREDOC_TAG_RE.match(line, index)
            if match:
                introducer = line[:index]
                tags.append((match.group(2), line.startswith("<<-", index), _shell_runs(introducer)))
                index = match.end()
                continue
        index += 1
    return tags


def _shell_runs(introducer: str) -> bool:
    for word in introducer.replace("|", " ").replace(";", " ").replace("&", " ").split():
        base = os.path.basename(word.strip("\"'"))
        if base in SHELLS or base.endswith(".sh"):
            return True
    return False


def _split_heredocs(script: str) -> list[tuple[str, list[str], list[str]]]:
    """Each logical line with its data heredoc bodies and its shell-run heredoc bodies."""
    out: list[tuple[str, list[str], list[str]]] = []
    waiting: list[tuple[str, bool, bool]] = []
    body: list[str] = []
    for line in _logical_lines(script):
        if waiting:
            tag, strip_tabs, shell_runs = waiting[0]
            candidate = line.lstrip("\t") if strip_tabs else line
            if candidate.strip() != tag:
                body.append(line)
                continue
            _attach_body(out, "\n".join(body), shell_runs)
            body = []
            waiting.pop(0)
            continue
        out.append((line, [], []))
        waiting = _unquoted_heredoc_tags(line)
    if waiting:
        _attach_body(out, "\n".join(body), waiting[0][2])
    return out


def _attach_body(out: list[tuple[str, list[str], list[str]]], text: str, shell_runs: bool) -> None:
    if not out:
        out.append(("", [], []))
    _line, data_bodies, shell_bodies = out[-1]
    (shell_bodies if shell_runs else data_bodies).append(text)


def _split_segments(text: str) -> list[tuple[str, str]]:
    """Quote-aware split into (separator before, text); `$(` and backticks split even inside double quotes."""
    pieces: list[tuple[str, str]] = []
    current: list[str] = []
    separator = ""
    quote = ""
    saved_quotes: list[str] = []
    index = 0

    def flush(next_separator: str) -> None:
        nonlocal current, separator
        pieces.append((separator, "".join(current)))
        current = []
        separator = next_separator

    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'":
            current.append(text[index:index + 2])
            index += 2
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            current.append(char)
        elif quote == '"':
            if char == '"':
                quote = ""
                current.append(char)
            elif text.startswith("$(", index):
                saved_quotes.append(quote)
                quote = ""
                flush("$(")
                index += 1
            elif char == "`":
                saved_quotes.append(quote)
                quote = ""
                flush("`")
            else:
                current.append(char)
        elif char in "'\"":
            quote = char
            current.append(char)
        elif char == "`" and saved_quotes and saved_quotes[-1] == '"':
            quote = saved_quotes.pop()
            flush("`")
        elif char == ")" and saved_quotes:
            quote = saved_quotes.pop()
            flush(")")
        elif char in SEPARATORS:
            run = char
            while index + 1 < len(text) and text[index + 1] in "|&" and char in "|&":
                index += 1
                run += text[index]
            flush(run)
        else:
            current.append(char)
        index += 1
    flush("")
    return pieces


def _argvs(text: str) -> list[tuple[str, ...]]:
    """The piece as one argv, or, when shlex refuses it, re-split on separators with quotes ignored."""
    try:
        return [tuple(shlex.split(text, comments=False, posix=True))]
    except ValueError:
        return [
            tuple(re.findall(r"[^\s\"']+", piece))
            for piece in re.split(r"[;|&\n()`]+", text)
            if piece.strip()
        ]


def _strip_wrappers(argv: tuple[str, ...]) -> tuple[str, ...]:
    words = list(argv)
    while words and ENV_ASSIGN_RE.match(words[0]):
        words.pop(0)
    while words and os.path.basename(words[0]) in WRAPPERS:
        words.pop(0)
        while words and (words[0].startswith("-") or ENV_ASSIGN_RE.match(words[0])):
            words.pop(0)
    return tuple(words)


def _nested_script(argv: tuple[str, ...]) -> str | None:
    if not argv:
        return None
    head = os.path.basename(argv[0])
    if head == "eval":
        return " ".join(argv[1:]) or None
    if head not in SHELLS:
        return None
    for index, word in enumerate(argv[1:], start=1):
        if word.startswith("-") and not word.startswith("--") and "c" in word[1:] and index + 1 < len(argv):
            return argv[index + 1]
    return None


def commands(script: str, depth: int = 0) -> list[Command]:
    """Every command the script runs, including those inside wrappers and shell heredocs."""
    if depth > MAX_NESTING:
        return []
    out: list[Command] = []
    for line, data_bodies, shell_bodies in _split_heredocs(script):
        previous_words: tuple[str, ...] = ()
        for separator, raw in _split_segments(line):
            text = raw.strip()
            if not text:
                continue
            for argv in _argvs(text):
                argv = _strip_wrappers(argv)
                piped = " ".join(previous_words) if separator in ("|", "|&") else ""
                stdin_text = "\n".join([piped, *data_bodies]).strip()
                out.append(Command(argv, text, stdin_text))
                nested = _nested_script(argv)
                if nested:
                    out.extend(commands(nested, depth + 1))
                previous_words = argv
        for body in shell_bodies:
            out.extend(commands(body, depth + 1))
    return out


def _api_path(raw: str) -> str | None:
    """The GitHub REST path a `gh api` endpoint or an HTTP URL names, or None when it is not GitHub."""
    candidate = raw.strip().strip("\"'")
    if "://" in candidate or candidate.lower().startswith("api.github.com"):
        match = URL_RE.match(candidate)
        if not match:
            return None
        host = match.group(1).lower()
        path = match.group(2) or ""
        if host == "api.github.com":
            return _clean_path(path)
        if path.lower().startswith("/api/v3/"):
            return _clean_path(path[len("/api/v3"):])
        return None
    return _clean_path(candidate)


def _clean_path(path: str) -> str:
    return path.split("?", 1)[0].split("#", 1)[0].strip("/")


def _creates_repo(path: str) -> str | None:
    parts = path.split("/")
    if parts == ["user", "repos"]:
        return "POST user/repos creates a repository"
    if len(parts) == 3 and parts[0] == "orgs" and parts[2] == "repos":
        return f"POST {path} creates an organization repository"
    if len(parts) == 4 and parts[0] == "repos" and parts[3] == "forks":
        return f"POST {path} forks a repository"
    if len(parts) == 4 and parts[0] == "repos" and parts[3] == "generate":
        return f"POST {path} creates a repository from a template"
    return None


def _graphql_verdict(path: str | None, bodies: list[str], file_bodies: list[str], stdin_text: str) -> Verdict | None:
    if path != "graphql":
        return None
    inline = " ".join(bodies)
    if any(mutation in inline for mutation in GRAPHQL_MUTATIONS):
        return Verdict(RULE_GRAPHQL, "GraphQL body carries a repository-creating mutation")
    if file_bodies or any(body in ("-", "@-") for body in bodies):
        if any(mutation in stdin_text for mutation in GRAPHQL_MUTATIONS):
            return Verdict(RULE_GRAPHQL, "piped GraphQL body carries a repository-creating mutation")
        if not stdin_text:
            return Verdict(RULE_UNCHECKED, "GraphQL body comes from a file or stdin the hook cannot read", unchecked=True)
    return None


def _gh_verdict(argv: tuple[str, ...], stdin_text: str) -> Verdict | None:
    positional = [word for word in argv[1:] if not word.startswith("-")]
    if len(positional) >= 2 and positional[0] == "repo":
        if positional[1] == "create":
            return Verdict(RULE_GH_REPO_CREATE, "gh repo create")
        if positional[1] == "fork":
            return Verdict(RULE_GH_REPO_FORK, "gh repo fork")
    if not positional or positional[0] != "api":
        return None
    args = list(argv[argv.index("api") + 1:])
    method: str | None = None
    fields = False
    bodies: list[str] = []
    file_bodies: list[str] = []
    endpoint: str | None = None
    index = 0
    while index < len(args):
        word = args[index]
        nxt = args[index + 1] if index + 1 < len(args) else ""
        if word in ("-X", "--method"):
            method, index = nxt.upper(), index + 2
        elif word.startswith("--method="):
            method, index = word.split("=", 1)[1].upper(), index + 1
        elif word.startswith("-X") and len(word) > 2:
            method, index = word[2:].upper(), index + 1
        elif word in GH_API_FIELD_FLAGS:
            fields, index = True, index + 2
            bodies.append(nxt)
        elif any(word.startswith(flag + "=") for flag in GH_API_FIELD_FLAGS if flag.startswith("--")):
            fields, index = True, index + 1
            bodies.append(word.split("=", 1)[1])
        elif word == "--input":
            fields, index = True, index + 2
            (bodies if nxt == "-" else file_bodies).append(nxt)
        elif word.startswith("--input="):
            fields, index = True, index + 1
            value = word.split("=", 1)[1]
            (bodies if value == "-" else file_bodies).append(value)
        elif word in GH_API_VALUE_FLAGS:
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            endpoint = endpoint if endpoint is not None else word
            index += 1
    path = _api_path(endpoint) if endpoint is not None else None
    graphql = _graphql_verdict(path, bodies, file_bodies, stdin_text)
    if graphql:
        return graphql
    effective = method or ("POST" if fields else "GET")
    if path is None or effective not in WRITE_METHODS:
        return None
    reason = _creates_repo(path)
    return Verdict(RULE_GH_API, f"gh api {reason}") if reason else None


def _curl_verdict(argv: tuple[str, ...], stdin_text: str) -> Verdict | None:
    method: str | None = None
    data = False
    forced_get = False
    urls: list[str] = []
    bodies: list[str] = []
    file_bodies: list[str] = []
    index = 1
    while index < len(argv):
        word = argv[index]
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if word in ("-X", "--request"):
            method, index = nxt.upper(), index + 2
        elif word.startswith("--request="):
            method, index = word.split("=", 1)[1].upper(), index + 1
        elif word.startswith("-X") and len(word) > 2:
            method, index = word[2:].upper(), index + 1
        elif word in CURL_DATA_FLAGS:
            data, index = True, index + 2
            (file_bodies if nxt.startswith("@") and nxt != "@-" else bodies).append(nxt)
        elif any(word.startswith(flag + "=") for flag in CURL_DATA_FLAGS if flag.startswith("--")):
            data, index = True, index + 1
            bodies.append(word.split("=", 1)[1])
        elif word in ("-G", "--get"):
            forced_get, index = True, index + 1
        elif word == "--url":
            urls.append(nxt)
            index += 2
        elif word.startswith("--url="):
            urls.append(word.split("=", 1)[1])
            index += 1
        elif word in CURL_VALUE_FLAGS:
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            urls.append(word)
            index += 1
    effective = "GET" if forced_get else (method or ("POST" if data else "GET"))
    return _http_verdict("curl", urls, effective, bodies, file_bodies, stdin_text)


def _wget_verdict(argv: tuple[str, ...], stdin_text: str) -> Verdict | None:
    method: str | None = None
    data = False
    urls: list[str] = []
    bodies: list[str] = []
    file_bodies: list[str] = []
    index = 1
    while index < len(argv):
        word = argv[index]
        nxt = argv[index + 1] if index + 1 < len(argv) else ""
        if word == "--method":
            method, index = nxt.upper(), index + 2
        elif word.startswith("--method="):
            method, index = word.split("=", 1)[1].upper(), index + 1
        elif word in WGET_POST_PREFIXES:
            data, index = True, index + 2
            (file_bodies if word.endswith("file") else bodies).append(nxt)
        elif word.startswith(WGET_POST_PREFIXES):
            data, index = True, index + 1
            name, value = word.split("=", 1)
            (file_bodies if name.endswith("file") else bodies).append(value)
        elif word in ("-O", "--output-document", "-o", "--output-file", "--header", "-U", "--user-agent", "-P", "-T", "--timeout", "-t", "--tries"):
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            urls.append(word)
            index += 1
    effective = method or ("POST" if data else "GET")
    return _http_verdict("wget", urls, effective, bodies, file_bodies, stdin_text)


def _httpie_verdict(argv: tuple[str, ...], stdin_text: str) -> Verdict | None:
    positional: list[str] = []
    index = 1
    while index < len(argv):
        word = argv[index]
        if word in HTTPIE_VALUE_FLAGS:
            index += 2
        elif word.startswith("-"):
            index += 1
        else:
            positional.append(word)
            index += 1
    if not positional:
        return None
    method: str | None = None
    if positional[0].upper() in HTTPIE_METHODS:
        method = positional.pop(0).upper()
    if not positional:
        return None
    url = positional.pop(0)
    items = positional
    bodies = [item for item in items if "=" in item and not item.split("=", 1)[0].endswith(":")]
    file_bodies = [item for item in items if "@" in item.split("=", 1)[0]]
    effective = method or ("POST" if bodies or file_bodies else "GET")
    return _http_verdict(os.path.basename(argv[0]), [url], effective, bodies, file_bodies, stdin_text)


def _http_verdict(client: str, urls: list[str], method: str, bodies: list[str], file_bodies: list[str], stdin_text: str) -> Verdict | None:
    for url in urls:
        path = _api_path(url)
        if path is None:
            continue
        if method in WRITE_METHODS:
            graphql = _graphql_verdict(path, bodies, file_bodies, stdin_text)
            if graphql:
                return graphql
            reason = _creates_repo(path)
            if reason:
                return Verdict(RULE_HTTP, f"{client} {reason}")
    return None


def classify(command: Command) -> Verdict | None:
    if not command.argv:
        return None
    head = os.path.basename(command.argv[0])
    if head == "gh":
        return _gh_verdict(command.argv, command.stdin_text)
    if head == "curl":
        return _curl_verdict(command.argv, command.stdin_text)
    if head == "wget":
        return _wget_verdict(command.argv, command.stdin_text)
    if head in HTTP_CLIENTS:
        return _httpie_verdict(command.argv, command.stdin_text)
    return None


def _subject(text: str) -> str:
    return "command:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= MATCH_PREVIEW_CHARS:
        return f"`{flat}`"
    return f"`{flat[:MATCH_PREVIEW_CHARS]}...`"


def decide(script: str) -> list[Finding]:
    """Every repo-creating command in the script, each as its own finding; empty when clean."""
    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for command in commands(script):
        verdict = classify(command)
        if verdict is None or (verdict.rule_id, command.text) in seen:
            continue
        seen.add((verdict.rule_id, command.text))
        if verdict.unchecked:
            findings.append(Finding(
                rule_id=RULE_UNCHECKED,
                subject=_subject(command.text),
                message=UNCHECKED_MESSAGE.format(reason=f"{verdict.what}: {_preview(command.text)}"),
                evidence=command.text,
            ))
            continue
        findings.append(Finding(
            rule_id=verdict.rule_id,
            subject=_subject(command.text),
            message=HIT_MESSAGE.format(matched=_preview(command.text), what=verdict.what),
            evidence=command.text,
        ))
    return findings


def _unchecked(reason: str) -> list[Finding]:
    return [Finding(
        rule_id=RULE_UNCHECKED,
        subject="payload:unreadable",
        message=UNCHECKED_MESSAGE.format(reason=reason),
        evidence=reason,
    )]


def _tool_name(event: dict) -> str:
    return str(event.get("tool_name") or event.get("toolName") or event.get("tool") or event.get("name") or "")


def _tool_input(event: dict) -> object:
    for key in ("tool_input", "toolInput", "arguments"):
        if key in event:
            return event[key]
    return None


def script_from_tool_input(tool_input: object) -> str | None:
    """The shell text a tool input will run, or None when there is no readable command."""
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    if command is None:
        command = tool_input.get("cmd")
    if isinstance(command, list) and all(isinstance(word, str) for word in command):
        if len(command) >= 3 and os.path.basename(command[0]) in SHELLS and command[1] in ("-c", "-lc"):
            return command[2]
        return shlex.join(command)
    if isinstance(command, str):
        return command
    return None


def detect(event: dict) -> list[Finding]:
    payload_error = event.get("_payload_error")
    if payload_error:
        return _unchecked(str(payload_error))
    stdin_error = event.get(STDIN_ERROR_KEY)
    if stdin_error:
        return _unchecked(str(stdin_error))
    tool_input = _tool_input(event)
    script = script_from_tool_input(tool_input)
    if script is None:
        tool = _tool_name(event)
        if tool and tool not in SHELL_TOOL_NAMES:
            return []
        if isinstance(tool_input, dict) and ("command" in tool_input or "cmd" in tool_input):
            return _unchecked("the command field is not text")
        return _unchecked("the payload has no command field")
    return decide(script)


def run(harness: str, hook_event_name: str) -> None:
    """Read stdin as bytes so a non-UTF-8 payload is refused instead of crashing open."""
    buffer = getattr(sys.stdin, "buffer", None)
    raw = buffer.read() if buffer is not None else sys.stdin.read().encode("utf-8", "surrogateescape")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        text = json.dumps({"tool_name": "Bash", STDIN_ERROR_KEY: f"the hook input is not UTF-8: {exc}"})
    sys.stdin = io.StringIO(text)
    run_hook(HOOK, harness, detect, hook_event_name=hook_event_name, inspect_raw_payload=True)
