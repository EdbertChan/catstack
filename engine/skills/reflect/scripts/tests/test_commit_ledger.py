from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(SCRIPTS_DIR, "commit_ledger.py")


def run_git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, check=True)


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


class TestCommitLedger(unittest.TestCase):
    def test_links_supported_creation_calls_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.mkdir(repo)
            run_git(repo, "init", "-b", "main")
            run_git(repo, "config", "user.email", "test@example.com")
            run_git(repo, "config", "user.name", "Test")
            commits = []
            for number, text in enumerate(("claude", "codex", "mention", "omp"), 7):
                path = "engine/hooks/x/detect.py"
                target = os.path.join(repo, path)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with open(target, "w", encoding="utf-8") as handle:
                    handle.write(text)
                run_git(repo, "add", path)
                run_git(repo, "commit", "-m", f"change {text}")
                commits.append(run_git(repo, "rev-parse", "HEAD").stdout.strip())
            outside = os.path.join(repo, "outside.txt")
            with open(outside, "w", encoding="utf-8") as handle:
                handle.write("outside")
            run_git(repo, "add", "outside.txt")
            run_git(repo, "commit", "-m", "outside")
            run_git(repo, "checkout", "-b", "work")
            ask = os.path.join(tmp, "roots", ".claude", "projects", "ask.jsonl")
            codex = os.path.join(tmp, "roots", ".codex", "sessions", "rollout.jsonl")
            mention = os.path.join(tmp, "roots", ".claude", "projects", "mention.jsonl")
            omp = os.path.join(tmp, "roots", ".omp", "agent", "sessions", "omp.jsonl")
            judge = os.path.join(tmp, "roots", ".claude", "projects", "llm-judge", "judge.jsonl")
            for path in (ask, codex, mention, omp, judge):
                os.makedirs(os.path.dirname(path), exist_ok=True)
            write_jsonl(ask, [
                {"type": "user", "message": {"role": "user", "content": "Please make a PR for this hook."}},
                {"type": "user", "isMeta": True, "message": {"role": "user", "content": "Stop hook feedback: ignore this."}},
                {"type": "assistant", "message": {"content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "gh pr create"}}]}},
                {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "https://github.com/acme/catstack/pull/7"}]}},
            ])
            write_jsonl(codex, [
                {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Submit this workflow."}]}},
                {"type": "response_item", "payload": {"type": "function_call", "call_id": "c1", "name": "exec", "arguments": "invoker-cli run plan.yaml --live"}},
                {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "c1", "output": "workflow wf-1789399890150-5 submitted"}},
            ])
            write_jsonl(mention, [{"type": "user", "message": {"role": "user", "content": "I saw https://github.com/acme/catstack/pull/7 later."}}])
            write_jsonl(omp, [{"type": "user", "message": {"role": "user", "content": "https://github.com/acme/catstack/pull/7"}}])
            write_jsonl(judge, [{"type": "user", "message": {"role": "user", "content": "https://github.com/acme/catstack/pull/7"}}])
            write_jsonl(os.path.join(tmp, "roots", ".claude", "projects", "mention.jsonl"), [{"type": "user", "message": {"role": "user", "content": "I saw https://github.com/acme/catstack/pull/9 later."}}])
            write_jsonl(os.path.join(tmp, "roots", ".omp", "agent", "sessions", "omp.jsonl"), [{"type": "user", "message": {"role": "user", "content": "https://github.com/acme/catstack/pull/10"}}])
            write_jsonl(os.path.join(tmp, "roots", ".claude", "projects", "llm-judge", "judge.jsonl"), [{"type": "user", "message": {"role": "user", "content": "https://github.com/acme/catstack/pull/7"}}])
            prs = os.path.join(tmp, "prs.json")
            with open(prs, "w", encoding="utf-8") as handle:
                json.dump([
                    {"number": 7, "title": "claude", "headRefName": "claude", "body": "", "mergeCommit": {"oid": commits[0]}},
                    {"number": 8, "title": "codex", "headRefName": "codex", "body": "wf-1789399890150-5", "mergeCommit": {"oid": commits[1]}},
                    {"number": 9, "title": "mention", "headRefName": "mention", "body": "", "mergeCommit": {"oid": commits[2]}},
                    {"number": 10, "title": "omp", "headRefName": "omp", "body": "", "mergeCommit": {"oid": commits[3]}},
                ], handle)
            out = os.path.join(tmp, "ledger.jsonl")
            result = subprocess.run([sys.executable, SCRIPT, "link", "--repo", repo, "--paths", "engine/hooks/x", "--rev", "HEAD", "--prs-json", prs, "--repo-slug", "acme/catstack", "--roots", os.path.join(tmp, "roots"), "--out", out], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("commits=4 linked=2 unlinked=1 unchecked=1 excluded_chats=1", result.stdout)
            with open(out, encoding="utf-8") as handle:
                rows = [json.loads(line) for line in handle]
            by_pr = {row["pr"]["number"]: row for row in rows}
            self.assertEqual(by_pr[7]["status"], "linked")
            self.assertEqual(by_pr[7]["links"][0]["prior_human_messages"], ["Please make a PR for this hook."])
            self.assertNotIn("Stop hook feedback", str(by_pr[7]))
            self.assertEqual(by_pr[8]["status"], "linked")
            self.assertEqual(by_pr[9]["status"], "unlinked")
            self.assertEqual(by_pr[10]["status"], "unchecked")
            self.assertEqual(by_pr[10]["unchecked_chats"][0]["reason"], "tool-call shape not parsed")
            self.assertNotIn("llm-judge", "\n".join(json.dumps(row) for row in rows))
            self.assertEqual(len(rows), 4)
            self.assertNotIn("outside", "\n".join(row["subject"] for row in rows))

    def test_out_inside_repo_exits_two_and_names_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = os.path.join(tmp, "repo")
            os.mkdir(repo)
            out = os.path.join(repo, "ledger.jsonl")
            result = subprocess.run([sys.executable, SCRIPT, "link", "--repo", repo, "--paths", ".", "--out", out], capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertIn(os.path.realpath(repo), result.stderr)
            self.assertIn(os.path.realpath(out), result.stderr)


if __name__ == "__main__":
    unittest.main()
