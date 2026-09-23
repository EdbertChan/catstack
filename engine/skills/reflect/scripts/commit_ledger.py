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

CATSTACK_ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
LLM_JUDGE_DIR = os.path.join(CATSTACK_ROOT, "engine", "hooks", "llm-judge")
sys.path.insert(0, LLM_JUDGE_DIR)
from judge import run_runner, runners

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
ASK_STATUSES = ("agreed", "no_ask", "disagree", "one_judge", "unchecked")


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


def validate_outside_catstack(out: str) -> None:
    root_real = os.path.realpath(CATSTACK_ROOT)
    out_real = os.path.realpath(out)
    try:
        inside = os.path.commonpath([root_real, out_real]) == root_real
    except ValueError:
        inside = False
    if inside:
        print(f"refusing --out inside catstack checkout: out={out_real} checkout={root_real}", file=sys.stderr)
        raise SystemExit(2)


def write_jsonl(path: str, rows: list[dict[str, Any]]) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def ask_messages(row: dict[str, Any]) -> list[str]:
    messages = []
    links = row.get("links")
    for link in links if isinstance(links, list) else []:
        prior = link.get("prior_human_messages") if isinstance(link, dict) else None
        for message in prior if isinstance(prior, list) else []:
            messages.append(text_from_value(message))
    return messages


def ask_prompt(row: dict[str, Any], messages: list[str]) -> str:
    lines = [
        "Choose the prior human message that is the real ask for this linked commit.",
        'Return exactly one JSON line: {"ask_index": <int or null>, "reason": "<one sentence>"}',
        f"Commit subject: {text_from_value(row.get('subject'))}",
    ]
    title = text_from_value(row.get("pr_title") or row.get("title")).strip()
    if title:
        lines.append(f"PR title: {title}")
    lines.append("Prior human messages:")
    for index, message in enumerate(messages):
        lines.append(f"{index}: {message}")
    return "\n".join(lines)


def selected_runner_entries(raw: str | None) -> list[tuple[str, list[str]]]:
    """No --runners means every runner llm-judge offers right now, not a name list frozen at import.

    The default used to be a string built from the DEFAULT_RUNNERS constant when
    this module was imported. That made CATSTACK_LLM_JUDGE_RUNNERS half-useful:
    it could change which runners exist, but not which ones this default picked,
    so putting a second judge back through the environment still judged with one.
    Reading the live set means the same override the llm-judge README documents
    restores the cross-check here too.
    """
    available = runners()
    if raw is None:
        return available
    selected = [item.strip() for item in raw.split(",") if item.strip()]
    by_name = {name: argv for name, argv in available}
    missing = [name for name in selected if name not in by_name]
    if missing:
        print(f"unknown --runners: {', '.join(missing)}", file=sys.stderr)
        raise SystemExit(2)
    return [(name, by_name[name]) for name in selected]


def warn_on_single_judge(runner_entries: list[tuple[str, list[str]]]) -> None:
    """A cross-check needs two judges; say so rather than quietly grading every row one_judge.

    agreed, no_ask and disagree are all decided by comparing one judge's
    ask_index against another's. With a single runner selected none of them can
    ever be reached, so every linked row lands on one_judge. That is a real loss
    of signal, and a silent one -- the counts line looks like an answer either
    way. Name the cause and the fix instead.
    """
    if len(runner_entries) >= 2:
        return
    selected = ", ".join(name for name, _ in runner_entries) or "none"
    print(
        f"commit_ledger: {len(runner_entries)} judge selected ({selected}); "
        "agreed, no_ask and disagree need two judges to compare, so every linked "
        "row can only reach one_judge. Add a second runner with "
        "CATSTACK_LLM_JUDGE_RUNNERS, or name two with --runners, "
        "to restore the cross-check.",
        file=sys.stderr,
    )


def judge_answer(name: str, argv: list[str], prompt: str, message_count: int) -> dict[str, Any]:
    attempt, answer = run_runner(name, argv, prompt)
    if answer is None:
        return {"outcome": "unchecked", "ask_index": None, "reason": str(attempt.get("reason") or "runner did not answer")}
    index = answer.get("ask_index")
    reason = text_from_value(answer.get("reason")).strip()
    if isinstance(index, bool) or not (index is None or isinstance(index, int)):
        return {"outcome": "unchecked", "ask_index": None, "reason": "invalid ask_index"}
    if index is not None and not 0 <= index < message_count:
        return {"outcome": "unchecked", "ask_index": None, "reason": "index out of range"}
    return {"outcome": "answered", "ask_index": index, "reason": reason}


def ask_result(judges: dict[str, dict[str, Any]], messages: list[str]) -> dict[str, Any]:
    answered = [judge for judge in judges.values() if judge.get("outcome") == "answered"]
    if not answered:
        return {"status": "unchecked", "reason": "no judge answered", "judges": judges}
    if len(answered) == 1:
        result = {"status": "one_judge", "reason": "exactly one judge answered", "judges": judges}
        index = answered[0].get("ask_index")
        if isinstance(index, int) and not isinstance(index, bool):
            result["index"] = index
            result["text"] = messages[index]
        return result
    choices = {judge.get("ask_index") for judge in answered}
    if len(choices) == 1:
        index = next(iter(choices))
        if index is None:
            return {"status": "no_ask", "reason": "judges agreed there is no ask", "judges": judges}
        return {
            "status": "agreed",
            "reason": "judges agreed on an ask",
            "index": index,
            "text": messages[index],
            "judges": judges,
        }
    return {"status": "disagree", "reason": "judges answered differently", "judges": judges}


def add_judged_ask(row: dict[str, Any], runner_entries: list[tuple[str, list[str]]]) -> dict[str, Any]:
    judged = dict(row)
    if row.get("status") != "linked":
        judged["ask"] = {"status": "unchecked", "reason": "row not linked", "judges": {}}
        return judged
    messages = ask_messages(row)
    prompt = ask_prompt(row, messages)
    judges = {}
    for name, argv in runner_entries:
        judges[name] = judge_answer(name, argv, prompt, len(messages))
    judged["ask"] = ask_result(judges, messages)
    return judged


def print_ask_failures(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        sha = text_from_value(row.get("commit"))
        ask = row.get("ask") if isinstance(row.get("ask"), dict) else {}
        for name, judge in (ask.get("judges") or {}).items():
            if isinstance(judge, dict) and judge.get("outcome") == "unchecked":
                print(f"{sha}: {name}: {judge.get('reason')}", file=sys.stderr)
        if ask.get("status") in ("unchecked", "disagree", "one_judge"):
            print(f"{sha}: {ask.get('status')}: {ask.get('reason')}", file=sys.stderr)


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
    judge = sub.add_parser("judge")
    judge.add_argument("--in", dest="in_path", required=True)
    judge.add_argument("--out", required=True)
    judge.add_argument("--runners", default=None)
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


def run_judge(args: argparse.Namespace) -> int:
    validate_outside_catstack(args.out)
    rows = read_jsonl(args.in_path)
    runner_entries = selected_runner_entries(args.runners)
    warn_on_single_judge(runner_entries)
    judged = [add_judged_ask(row, runner_entries) for row in rows]
    write_jsonl(args.out, judged)
    counts = {status: 0 for status in ASK_STATUSES}
    for row in judged:
        ask = row.get("ask") if isinstance(row.get("ask"), dict) else {}
        status = ask.get("status")
        if status in counts:
            counts[status] += 1
    print(" ".join(f"{status}={counts[status]}" for status in ASK_STATUSES))
    print_ask_failures(judged)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "link":
        return run_link(args)
    if args.command == "judge":
        return run_judge(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
