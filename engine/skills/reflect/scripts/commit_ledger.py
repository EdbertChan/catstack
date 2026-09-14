#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import transcript_provenance

CREATION_MARKERS = (
    "gh pr create",
    "mergify stack push",
    "create-pr.mjs",
    "safe-stack-push",
    "gh api",
    "invoker-cli",
    "invoker_submit_plan",
)
WORKFLOW_RE = re.compile(r"wf-\d{10,}-\d+")
EXCLUDED_MARKERS = ("llm-judge", "/.invoker/", "merge-clones", "/subagents/")
DEFAULT_ROOTS = (
    "~/.claude/projects",
    "~/.codex/sessions",
    "~/.cursor/projects",
    "~/.omp/agent/sessions",
)


def _text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_text(item.get("text", item.get("content", ""))) if isinstance(item, dict) else _text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(_text(item) for item in value.values())
    return ""


def _creation_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _is_creation(value):
    text = _creation_text(value).lower()
    return any(marker in text for marker in CREATION_MARKERS) and (
        "gh api" not in text or "/pulls" in text
    ) and ("invoker-cli" not in text or " run" in text)


def _harness(path):
    normalized = os.path.realpath(path).replace("\\", "/")
    if "/.claude/projects/" in normalized:
        return "claude"
    if "/.codex/sessions/" in normalized:
        return "codex"
    if "/.cursor/projects/" in normalized:
        return "cursor"
    return None


def _output_by_id(rows, harness):
    outputs = {}
    for row in rows:
        if harness == "claude":
            content = row.get("message", {}).get("content", []) if isinstance(row.get("message"), dict) else []
            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    outputs[block.get("tool_use_id")] = _text(block.get("content"))
        else:
            payload = row.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("type") in ("function_call_output", "custom_tool_call_output"):
                outputs[payload.get("call_id")] = _text(payload.get("output", payload.get("content", "")))
    return outputs


def _creation_calls(rows, harness):
    outputs = _output_by_id(rows, harness)
    calls = []
    for index, row in enumerate(rows):
        if harness == "claude":
            content = row.get("message", {}).get("content", []) if isinstance(row.get("message"), dict) else []
            blocks = content if isinstance(content, list) else []
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_use" and _is_creation(block):
                    calls.append((index, block.get("id"), _creation_text(block), outputs.get(block.get("id"), "")))
        else:
            payload = row.get("payload")
            if isinstance(payload, dict) and payload.get("type") in ("function_call", "custom_tool_call") and _is_creation(payload):
                calls.append((index, payload.get("call_id"), _creation_text(payload), outputs.get(payload.get("call_id"), "")))
    return calls


def _load_rows(path):
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            rows.append(json.loads(line))
    return rows


def _discover(keys, roots):
    paths = []
    rg = shutil.which("rg")
    if rg:
        print("chat discovery: rg", file=sys.stderr)
        for root in roots:
            if not os.path.isdir(root):
                continue
            command = [rg, "-l", "-F", "--hidden", "--glob", "*.jsonl"]
            for key in keys:
                command.extend(("-e", key))
            command.append(root)
            result = subprocess.run(command, capture_output=True, text=True, check=False)
            if result.returncode not in (0, 1):
                raise RuntimeError(result.stderr.strip() or "rg failed")
            paths.extend(result.stdout.splitlines())
    else:
        print("chat discovery: python", file=sys.stderr)
        for root in roots:
            for path in Path(root).rglob("*.jsonl") if os.path.isdir(root) else ():
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                if any(key in text for key in keys):
                    paths.append(str(path))
    return sorted(set(paths))


def _git(repo, args):
    result = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git failed")
    return result.stdout


def _commits(repo, paths, rev):
    raw = _git(repo, ["log", "--format=%H%x1f%ad%x1f%s%x1f%B%x1e", "--date=short", rev, "--", *paths])
    commits = []
    for record in raw.split("\x1e"):
        fields = record.strip("\n").split("\x1f", 3)
        if len(fields) == 4 and fields[0]:
            commits.append({"commit": fields[0], "date": fields[1], "subject": fields[2], "body": fields[3]})
    return commits


def _pr_data(repo, prs_json):
    if prs_json:
        with open(prs_json, encoding="utf-8") as handle:
            return json.load(handle)
    result = subprocess.run(["gh", "pr", "list", "--state", "all", "--limit", "1000", "--json", "number,title,headRefName,body,mergeCommit"], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "gh pr list failed")
    return json.loads(result.stdout)


def _slug(repo, explicit):
    if explicit:
        return explicit
    result = subprocess.run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=repo, capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "gh repo view failed")
    return json.loads(result.stdout)["nameWithOwner"]


def _keys(commit, prs, slug):
    selected = None
    for pr in prs:
        merge = pr.get("mergeCommit")
        merge_oid = merge.get("oid") if isinstance(merge, dict) else merge
        if merge_oid == commit["commit"]:
            selected = pr
            break
    if selected is None:
        match = re.search(r"\(#(\d+)\)\s*$", commit["subject"])
        if match:
            selected = next((pr for pr in prs if str(pr.get("number")) == match.group(1)), None)
    if selected is None:
        return None, []
    number = selected.get("number")
    keys = [f"github.com/{slug}/pull/{number}"]
    text = f"{commit['body']}\n{selected.get('body') or ''}"
    keys.extend(sorted(set(WORKFLOW_RE.findall(text))))
    return selected, keys


def _inside(path, repo):
    out = os.path.realpath(path)
    root = os.path.realpath(repo)
    try:
        return os.path.commonpath((out, root)) == root
    except ValueError:
        return False


def link(args):
    if _inside(args.out, args.repo):
        print(f"--out real path {os.path.realpath(args.out)} is inside --repo real path {os.path.realpath(args.repo)}", file=sys.stderr)
        return 2
    roots = [os.path.realpath(os.path.expanduser(root)) for root in (args.roots or DEFAULT_ROOTS)]
    prs = _pr_data(args.repo, args.prs_json)
    slug = _slug(args.repo, args.repo_slug)
    commits = _commits(args.repo, args.paths, args.rev)
    keyed = []
    all_keys = set()
    for commit in commits:
        pr, keys = _keys(commit, prs, slug)
        row = {key: commit[key] for key in ("commit", "date", "subject")}
        row.update({"pr": pr, "keys": keys, "status": "unlinked", "reason": "", "links": [], "unchecked_chats": []})
        keyed.append(row)
        all_keys.update(keys)
    candidates = _discover(sorted(all_keys), roots) if all_keys else []
    excluded = [path for path in candidates if any(marker in path.replace("\\", "/") for marker in EXCLUDED_MARKERS)]
    usable = [path for path in candidates if path not in excluded]
    for path in usable:
        harness = _harness(path)
        try:
            chat_text = Path(path).read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            for row in keyed:
                if any(key in str(exc) for key in row["keys"]):
                    row["unchecked_chats"].append({"chat": path, "reason": str(exc)})
            continue
        for row in keyed:
            if not row["keys"] or not any(key in chat_text for key in row["keys"]):
                continue
            if harness not in ("claude", "codex"):
                row["unchecked_chats"].append({"chat": path, "reason": "tool-call shape not parsed"})
                continue
            try:
                rows = _load_rows(path)
                utterances = transcript_provenance.direct_human_utterances(path, harness)
                for index, _, call_text, output in _creation_calls(rows, harness):
                    for key in row["keys"]:
                        if key in output:
                            prior = [u.text[:2000] for u in utterances if u.index < index][-6:]
                            row["links"].append({"chat": path, "harness": harness, "creation_call": call_text[:300], "key": key, "prior_human_messages": prior})
            except Exception as exc:
                row["unchecked_chats"].append({"chat": path, "reason": str(exc)})
    for row in keyed:
        if row["links"]:
            row["status"] = "linked"
        elif row["unchecked_chats"]:
            row["status"] = "unchecked"
    with open(args.out, "w", encoding="utf-8") as handle:
        for row in keyed:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    counts = {status: sum(row["status"] == status for row in keyed) for status in ("linked", "unlinked", "unchecked")}
    print(f"commits={len(keyed)} linked={counts['linked']} unlinked={counts['unlinked']} unchecked={counts['unchecked']} excluded_chats={len(excluded)}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    link_parser = sub.add_parser("link")
    link_parser.add_argument("--repo", required=True)
    link_parser.add_argument("--paths", nargs="+", required=True)
    link_parser.add_argument("--out", required=True)
    link_parser.add_argument("--rev", default="origin/main")
    link_parser.add_argument("--prs-json")
    link_parser.add_argument("--repo-slug")
    link_parser.add_argument("--roots", nargs="+")
    args = parser.parse_args(argv)
    try:
        return link(args)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
