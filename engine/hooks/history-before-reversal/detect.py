#!/usr/bin/env python3
"""Detector for history-before-reversal.

Blocks `git revert <commit>` (and a hand-written `git commit -m "Revert ..."`)
until the session has both read the change being reversed and searched the
history of the code around it. Three outcomes: block, allow, unchecked.
"""
from __future__ import annotations

import glob
import json
import os
import re
import shlex
from dataclasses import dataclass, field

SHELL_LIKE_TOOL_NAMES = (
    "Bash", "bash", "shell", "Shell", "exec", "exec_command",
    "run_terminal_cmd", "local_shell", "run_command", "shell_call",
)
REVERT_CONTROL_FLAGS = {"--abort", "--continue", "--quit", "--skip"}
HISTORY_SEARCH_LOG_FLAGS = ("-S", "-G", "--follow", "-L")
MAX_TRANSCRIPT_BYTES = 64 * 1024 * 1024
SEGMENT_SPLIT = re.compile(r"&&|\|\||;|\||\n")
HEREDOC = re.compile(r"<<-?\s*['\"]?(\w+)['\"]?[^\n]*\n.*?\n\s*\1\s*(?:\n|$)", re.S)
ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
SHA_TOKEN = re.compile(r"^[0-9a-fA-F]{7,40}$")


@dataclass
class Reversal:
    command: str
    targets: list[str] = field(default_factory=list)


@dataclass
class Evidence:
    read_shas: set[str] = field(default_factory=set)
    read_pr: bool = False
    searched_history: bool = False


@dataclass
class Verdict:
    outcome: str
    message: str = ""


def _segments(command: str) -> list[list[str]]:
    without_heredocs = HEREDOC.sub("\n", command)
    segments: list[list[str]] = []
    for raw in SEGMENT_SPLIT.split(without_heredocs):
        raw = raw.strip()
        if not raw:
            continue
        try:
            tokens = shlex.split(raw, comments=True)
        except ValueError:
            tokens = raw.split()
        while tokens and ENV_ASSIGNMENT.match(tokens[0]):
            tokens = tokens[1:]
        if tokens:
            segments.append(tokens)
    return segments


def _git_subcommand(tokens: list[str]) -> tuple[str, list[str]] | None:
    if not tokens or os.path.basename(tokens[0]) != "git":
        return None
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in ("-C", "-c", "--git-dir", "--work-tree"):
            index += 2
            continue
        if token.startswith("-"):
            index += 1
            continue
        return token, tokens[index + 1:]
    return None


def _commit_message(args: list[str]) -> str:
    for index, token in enumerate(args):
        if token in ("-m", "--message") and index + 1 < len(args):
            return args[index + 1]
        if token.startswith("--message="):
            return token.split("=", 1)[1]
        if token.startswith("-m") and len(token) > 2:
            return token[2:]
    return ""


def find_reversals(command: str) -> list[Reversal]:
    found: list[Reversal] = []
    for tokens in _segments(command):
        parsed = _git_subcommand(tokens)
        if not parsed:
            continue
        sub, args = parsed
        if sub == "revert":
            if any(arg in REVERT_CONTROL_FLAGS for arg in args):
                continue
            targets = [arg for arg in args if not arg.startswith("-")]
            found.append(Reversal(command=" ".join(tokens), targets=targets))
        elif sub == "commit" and _commit_message(args).lstrip().startswith('Revert "'):
            found.append(Reversal(command=" ".join(tokens), targets=[]))
    return found


def _evidence_from_command(command: str, evidence: Evidence) -> None:
    for tokens in _segments(command):
        if tokens[:3] == ["gh", "pr", "view"] or tokens[:3] == ["gh", "api", "graphql"]:
            evidence.read_pr = True
            continue
        if tokens[:2] == ["gh", "api"] and any("/pulls/" in token or "/commits/" in token for token in tokens):
            evidence.read_pr = True
            continue
        parsed = _git_subcommand(tokens)
        if not parsed:
            continue
        sub, args = parsed
        if sub == "show":
            evidence.read_shas.update(arg.split(":", 1)[0] for arg in args if SHA_TOKEN.match(arg.split(":", 1)[0]))
        elif sub == "blame":
            evidence.searched_history = True
        elif sub == "log" and any(
            arg == flag or arg.startswith(flag + "=") or (flag in ("-S", "-G", "-L") and arg.startswith(flag))
            for arg in args
            for flag in HISTORY_SEARCH_LOG_FLAGS
        ):
            evidence.searched_history = True


def session_logs(transcript_path: str) -> list[str]:
    path = os.path.abspath(transcript_path)
    parent_dir = os.path.dirname(path)
    if os.path.basename(parent_dir) == "subagents":
        session_dir = os.path.dirname(parent_dir)
        main_log = session_dir + ".jsonl"
    else:
        session_dir = path[: -len(".jsonl")] if path.endswith(".jsonl") else path
        main_log = path
    helpers = sorted(glob.glob(os.path.join(session_dir, "subagents", "*.jsonl")))
    return [main_log] + [helper for helper in helpers if helper != main_log]


def _commands_in_log(transcript_path: str) -> list[str] | None:
    try:
        if os.path.getsize(transcript_path) > MAX_TRANSCRIPT_BYTES:
            return None
        with open(transcript_path, encoding="utf-8", errors="replace") as handle:
            lines = handle.readlines()
    except OSError:
        return None
    commands: list[str] = []
    parsed_lines = 0
    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        parsed_lines += 1
        content = (record.get("message") or {}).get("content") if isinstance(record, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if (
                isinstance(block, dict)
                and block.get("type") == "tool_use"
                and block.get("name") in SHELL_LIKE_TOOL_NAMES
            ):
                command = (block.get("input") or {}).get("command")
                if isinstance(command, str):
                    commands.append(command)
    if lines and parsed_lines == 0:
        return None
    return commands


def _prior_commands(transcript_path: str) -> list[str] | None:
    logs = session_logs(transcript_path)
    commands = _commands_in_log(transcript_path)
    if commands is None:
        return None
    for log in logs:
        if os.path.abspath(log) == os.path.abspath(transcript_path) or not os.path.exists(log):
            continue
        helper_commands = _commands_in_log(log)
        if helper_commands is not None:
            commands.extend(helper_commands)
    return commands


def _sha_was_read(target: str, read_shas: set[str]) -> bool:
    if not SHA_TOKEN.match(target):
        return False
    target = target.lower()
    return any(target.startswith(sha.lower()) or sha.lower().startswith(target) for sha in read_shas)


def decide(command: str, transcript_path: str | None) -> Verdict:
    reversals = find_reversals(command)
    if not reversals:
        return Verdict("allow")
    if not transcript_path:
        return Verdict("unchecked", "history-before-reversal: UNCHECKED, no transcript_path in the payload; allowing this reversal.")
    prior = _prior_commands(transcript_path)
    if prior is None:
        return Verdict("unchecked", f"history-before-reversal: UNCHECKED, could not read the transcript at {transcript_path}; allowing this reversal.")
    evidence = Evidence()
    for earlier in prior:
        if earlier == command:
            continue
        _evidence_from_command(earlier, evidence)
    missing: list[str] = []
    for reversal in reversals:
        unread = [t for t in reversal.targets if not _sha_was_read(t, evidence.read_shas)]
        if reversal.targets and unread and not evidence.read_pr:
            missing.append(
                f"read the change you are reversing: `git show {unread[0]}` (its message carries the PR body) or `gh pr view <number>`"
            )
        if not reversal.targets and not (evidence.read_shas or evidence.read_pr):
            missing.append("read the change you are reversing: `git show <sha>` or `gh pr view <number>`")
        if not evidence.searched_history:
            missing.append(
                "search the history of the code that conflicts with it: `git log -S <token>` / `git log -G <regex>` "
                "on the guard, check, or test that is failing, or `git blame` / `git log --follow` on its file, "
                "then read the PR that added it"
            )
    if not missing:
        return Verdict("allow")
    steps = "\n".join(f"  {index}. {item}" for index, item in enumerate(dict.fromkeys(missing), 1))
    return Verdict(
        "block",
        "history-before-reversal: this undoes merged work, and this session has not yet:\n"
        f"{steps}\n"
        "A reversal throws away the reason the change was made. Find out whether the thing it conflicts with "
        "is the real bug before undoing it, and say which PR you are reversing and why. See the `why` skill.",
    )
