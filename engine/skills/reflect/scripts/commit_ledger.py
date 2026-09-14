from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcript_provenance

DEFAULT_ROOTS = (
    "~/.claude/projects",
    "~/.codex/sessions",
    "~/.cursor/projects",
    "~/.omp/agent/sessions",
)
EXCLUDED_PATH_PARTS = ("llm" + "-judge", "/.invoker/", "merge-clones", "/subagents/")
WF_RE = re.compile(r"wf-\d{10,}-\d+")
TRAILING_PR_RE = re.compile(r"\(#(?P<number>\d+)\)\s*$")
CREATION_NEEDLES = (
    "gh pr create",
    "mergify stack push",
    "create-pr.mjs",
    "safe-stack-push",
)


@dataclass(frozen=True)
class Commit:
    sha: str
    date: str
    subject: str
    body: str


@dataclass(frozen=True)
class CandidateChat:
    path: str
    harness: str


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def text_from_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="ignore")
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(text_from_value(item) for item in value)
    if isinstance(value, dict):
        parts = []
        for item in value.values():
            part = text_from_value(item)
            if part:
                parts.append(part)
        return "\n".join(parts)
    return str(value)


def command_matches(text: str, name: str = "") -> bool:
    haystack = text.lower()
    tool_name = name.lower()
    if any(needle in haystack for needle in CREATION_NEEDLES):
        return True
    if "gh api" in haystack and "/pulls" in haystack:
        return True
    if "invoker-cli" in haystack and " run" in haystack:
        return True
    return "invoker_submit_plan" in tool_name


def read_jsonl(path: str) -> list[dict[str, Any]]:
    rows = []
    with open(path, encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            if not line.strip():
                continue
            row = json.loads(line)
            if isinstance(row, dict):
                rows.append(row)
    return rows


def run_checked(cmd: list[str], cwd: str | None = None) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return result.stdout


def load_commits(repo: str, rev: str, paths: list[str]) -> list[Commit]:
    output = run_checked([
        "git",
        "-C",
        repo,
        "log",
        "--format=%H%x1f%ad%x1f%s%x1f%B%x1e",
        "--date=short",
        rev,
        "--",
        *paths,
    ])
    commits = []
    for raw in output.split("\x1e"):
        record = raw.strip("\n")
        if not record:
            continue
        parts = record.split("\x1f", 3)
        if len(parts) != 4:
            continue
        commits.append(Commit(parts[0], parts[1], parts[2], parts[3]))
    return commits


def load_prs(repo: str, prs_json: str | None) -> list[dict[str, Any]]:
    if prs_json:
        with open(prs_json, encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, list) else []
    data = run_checked([
        "gh",
        "pr",
        "list",
        "--state",
        "all",
        "--limit",
        "1000",
        "--json",
        "number,title,headRefName,body,mergeCommit",
    ], cwd=repo)
    parsed = json.loads(data)
    return parsed if isinstance(parsed, list) else []


def repo_slug(repo: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    data = run_checked(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=repo)
    parsed = json.loads(data)
    slug = parsed.get("nameWithOwner")
    if not isinstance(slug, str) or not slug:
        raise SystemExit("gh repo view did not return nameWithOwner")
    return slug


def pr_number_for_commit(commit: Commit, prs: list[dict[str, Any]]) -> int | None:
    for pr in prs:
        merge = pr.get("mergeCommit")
        oid = merge.get("oid") if isinstance(merge, dict) else None
        if oid == commit.sha and isinstance(pr.get("number"), int):
            return pr["number"]
    match = TRAILING_PR_RE.search(commit.subject)
    return int(match.group("number")) if match else None


def pr_body(number: int | None, prs: list[dict[str, Any]]) -> str:
    if number is None:
        return ""
    for pr in prs:
        if pr.get("number") == number:
            return text_from_value(pr.get("body"))
    return ""


def keys_for_commit(commit: Commit, prs: list[dict[str, Any]], slug: str) -> tuple[int | None, list[str]]:
    number = pr_number_for_commit(commit, prs)
    keys = []
    if number is not None:
        keys.append(f"github.com/{slug}/pull/{number}")
    seen = set(keys)
    for text in (commit.body, pr_body(number, prs)):
        for wf in WF_RE.findall(text):
            if wf not in seen:
                keys.append(wf)
                seen.add(wf)
    return number, keys


def expanded_roots(roots: list[str] | None) -> list[str]:
    raw_roots = roots if roots else list(DEFAULT_ROOTS)
    return [os.path.realpath(os.path.expanduser(root)) for root in raw_roots]


def excluded_chat(path: str) -> bool:
    normalized = os.path.realpath(path).replace("\\", "/")
    return any(part in normalized for part in EXCLUDED_PATH_PARTS)


def harness_for_path(path: str, roots: list[str]) -> str:
    normalized = os.path.realpath(path).replace("\\", "/")
    for root in roots:
        root_norm = root.replace("\\", "/")
        try:
            if os.path.commonpath([os.path.realpath(path), root]) != root:
                continue
        except ValueError:
            continue
        if "/.claude/projects" in root_norm:
            return "claude"
        if "/.codex/sessions" in root_norm:
            return "codex"
        if "/.cursor/projects" in root_norm:
            return "cursor"
        return "unsupported"
    if "/.claude/projects/" in normalized:
        return "claude"
    if "/.codex/sessions/" in normalized:
        return "codex"
    if "/.cursor/projects/" in normalized:
        return "cursor"
    return "unsupported"


def python_scan(roots: list[str], keys: list[str]) -> list[str]:
    matches = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for current, _, files in os.walk(root):
            for filename in files:
                if not filename.endswith(".jsonl"):
                    continue
                path = os.path.join(current, filename)
                try:
                    with open(path, encoding="utf-8", errors="ignore") as handle:
                        text = handle.read()
                except OSError:
                    continue
                if any(key in text for key in keys):
                    matches.append(path)
    return matches


def rg_scan(roots: list[str], keys: list[str]) -> list[str]:
    cmd = ["rg", "-l", "-F", "--glob", "*.jsonl"]
    for key in keys:
        cmd.extend(["-e", key])
    cmd.extend(root for root in roots if os.path.isdir(root))
    if len(cmd) == 5 + 2 * len(keys):
        return []
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode not in (0, 1):
        sys.stderr.write(result.stderr)
        raise SystemExit(result.returncode)
    return [line for line in result.stdout.splitlines() if line]


def discover_chats(roots: list[str], keys: list[str]) -> tuple[list[CandidateChat], int]:
    if not keys:
        return [], 0
    if shutil.which("rg"):
        print("chat discovery: rg", file=sys.stderr)
        paths = rg_scan(roots, keys)
    else:
        print("chat discovery: python", file=sys.stderr)
        paths = python_scan(roots, keys)
    candidates = []
    excluded = 0
    for path in sorted(set(paths)):
        if excluded_chat(path):
            excluded += 1
            continue
        candidates.append(CandidateChat(path, harness_for_path(path, roots)))
    return candidates, excluded


def chat_contains_any(path: str, keys: list[str]) -> str | None:
    with open(path, encoding="utf-8", errors="ignore") as handle:
        text = handle.read()
    for key in keys:
        if key in text:
            return key
    return None


def tool_results_by_id(rows: list[dict[str, Any]]) -> dict[str, str]:
    results = {}
    for row in rows:
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else row.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_id = block.get("tool_use_id")
            if isinstance(tool_id, str):
                results[tool_id] = text_from_value(block.get("content"))
    return results


def claude_creation_calls(rows: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    results = tool_results_by_id(rows)
    calls = []
    for index, row in enumerate(rows):
        message = row.get("message")
        content = message.get("content") if isinstance(message, dict) else row.get("content")
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_id = block.get("id")
            name = str(block.get("name") or "")
            call_text = text_from_value(block.get("input"))
            if isinstance(tool_id, str) and command_matches(call_text, name):
                calls.append((index, call_text or name, results.get(tool_id, "")))
    return calls


def codex_outputs_by_id(rows: list[dict[str, Any]]) -> dict[str, str]:
    outputs = {}
    for row in rows:
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") not in ("function_call_output", "custom_tool_call_output"):
            continue
        call_id = payload.get("call_id")
        if isinstance(call_id, str):
            outputs[call_id] = text_from_value(payload.get("output"))
    return outputs


def codex_creation_calls(rows: list[dict[str, Any]]) -> list[tuple[int, str, str]]:
    outputs = codex_outputs_by_id(rows)
    calls = []
    for index, row in enumerate(rows):
        if row.get("type") != "response_item":
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if payload.get("type") not in ("function_call", "custom_tool_call"):
            continue
        call_id = payload.get("call_id")
        call_text = text_from_value(payload.get("arguments") or payload.get("input"))
        name = str(payload.get("name") or "")
        if isinstance(call_id, str) and command_matches(call_text, name):
            calls.append((index, call_text or name, outputs.get(call_id, "")))
    return calls


def prior_human_messages(path: str, harness: str, row_index: int) -> list[str]:
    utterances = transcript_provenance.direct_human_utterances(path, harness)
    return [clip(item.text, 2000) for item in utterances if item.index < row_index][-6:]


def links_for_chat(path: str, harness: str, keys: list[str]) -> list[dict[str, Any]]:
    rows = read_jsonl(path)
    if harness == "claude":
        calls = claude_creation_calls(rows)
    elif harness == "codex":
        calls = codex_creation_calls(rows)
    else:
        return []
    links = []
    for row_index, call_text, output in calls:
        for key in keys:
            if key in output:
                links.append({
                    "chat": path,
                    "harness": harness,
                    "creation_call": clip(call_text, 300),
                    "key": key,
                    "prior_human_messages": prior_human_messages(path, harness, row_index),
                })
                break
    return links


def ledger_rows(commits: list[Commit], prs: list[dict[str, Any]], slug: str, roots: list[str]) -> tuple[list[dict[str, Any]], int]:
    keyed = []
    all_keys = []
    for commit in commits:
        number, keys = keys_for_commit(commit, prs, slug)
        keyed.append((commit, number, keys))
        all_keys.extend(keys)
    candidates, excluded = discover_chats(roots, sorted(set(all_keys)))
    rows = []
    for commit, number, keys in keyed:
        links = []
        unchecked = []
        for candidate in candidates:
            try:
                matched_key = chat_contains_any(candidate.path, keys)
            except Exception as exc:
                unchecked.append({
                    "chat": candidate.path,
                    "reason": str(exc),
                })
                continue
            if not matched_key:
                continue
            if candidate.harness in ("cursor", "unsupported"):
                unchecked.append({
                    "chat": candidate.path,
                    "reason": "tool-call shape not parsed",
                })
                continue
            try:
                links.extend(links_for_chat(candidate.path, candidate.harness, keys))
            except Exception as exc:
                unchecked.append({
                    "chat": candidate.path,
                    "reason": str(exc),
                })
        if links:
            status = "linked"
            reason = "creation tool output matched key"
        elif unchecked:
            status = "unchecked"
            reason = "candidate chats could not be checked"
        else:
            status = "unlinked"
            reason = "no creation tool output matched keys"
        rows.append({
            "commit": commit.sha,
            "date": commit.date,
            "subject": commit.subject,
            "pr": number,
            "keys": keys,
            "status": status,
            "reason": reason,
            "links": links,
            "unchecked_chats": unchecked,
        })
    return rows, excluded


def validate_outside_repo(repo: str, out: str) -> None:
    repo_real = os.path.realpath(repo)
    out_real = os.path.realpath(out)
    try:
        inside = os.path.commonpath([repo_real, out_real]) == repo_real
    except ValueError:
        inside = False
    if inside:
        print(f"refusing --out inside --repo: out={out_real} repo={repo_real}", file=sys.stderr)
        raise SystemExit(2)


def write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    link = sub.add_parser("link")
    link.add_argument("--repo", required=True)
    link.add_argument("--paths", nargs="+", required=True)
    link.add_argument("--out", required=True)
    link.add_argument("--rev", default="origin/main")
    link.add_argument("--prs-json")
    link.add_argument("--repo-slug")
    link.add_argument("--roots", nargs="+")
    return parser


def run_link(args: argparse.Namespace) -> int:
    validate_outside_repo(args.repo, args.out)
    repo = os.path.realpath(args.repo)
    roots = expanded_roots(args.roots)
    prs = load_prs(repo, args.prs_json)
    slug = repo_slug(repo, args.repo_slug)
    commits = load_commits(repo, args.rev, args.paths)
    rows, excluded = ledger_rows(commits, prs, slug, roots)
    write_jsonl(args.out, rows)
    linked = sum(1 for row in rows if row["status"] == "linked")
    unchecked = sum(1 for row in rows if row["status"] == "unchecked")
    unlinked = sum(1 for row in rows if row["status"] == "unlinked")
    print(
        f"commits={len(rows)} linked={linked} unlinked={unlinked} "
        f"unchecked={unchecked} excluded_chats={excluded}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "link":
        return run_link(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
