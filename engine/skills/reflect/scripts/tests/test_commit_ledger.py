from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CATSTACK_ROOT = os.path.abspath(os.path.join(SCRIPTS_DIR, "..", "..", "..", ".."))
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, os.path.join(CATSTACK_ROOT, "scripts"))

import commit_ledger
from git_test_repo import init_repo


def run(cmd: list[str], cwd: str) -> str:
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def write(path: str, data: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(data)


def write_jsonl(path: str, rows: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def commit(repo: str, path: str, body: str, message: str) -> str:
    write(os.path.join(repo, path), body)
    run(["git", "add", path], repo)
    run(["git", "commit", "-m", message], repo)
    return run(["git", "rev-parse", "HEAD"], repo)


class TestCommitLedger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        init_repo(self.repo)
        run(["git", "config", "user.email", "test@example.com"], self.repo)
        run(["git", "config", "user.name", "Test User"], self.repo)
        self.path = "engine/hooks/x/detect.py"
        self.outside_sha = commit(self.repo, "docs/outside.md", "outside", "Outside (#15)")
        self.mention_sha = commit(self.repo, self.path, "mention", "Mention only (#13)")
        self.omp_sha = commit(self.repo, self.path, "omp", "OMP only (#12)")
        self.codex_sha = commit(
            self.repo,
            self.path,
            "codex",
            "Codex workflow\n\nwf-1789399890150-5",
        )
        self.claude_sha = commit(self.repo, self.path, "claude", "Claude PR (#11)")
        self.prs_path = os.path.join(self.root, "prs.json")
        with open(self.prs_path, "w", encoding="utf-8") as handle:
            json.dump([
                {
                    "number": 11,
                    "title": "Claude PR",
                    "headRefName": "claude-pr",
                    "body": "",
                    "mergeCommit": {"oid": self.claude_sha},
                },
                {
                    "number": 12,
                    "title": "OMP only",
                    "headRefName": "omp-only",
                    "body": "",
                    "mergeCommit": {"oid": self.omp_sha},
                },
                {
                    "number": 13,
                    "title": "Mention only",
                    "headRefName": "mention-only",
                    "body": "",
                    "mergeCommit": {"oid": self.mention_sha},
                },
            ], handle)
        self.claude_root = os.path.join(self.root, ".claude", "projects")
        self.codex_root = os.path.join(self.root, ".codex", "sessions")
        self.omp_root = os.path.join(self.root, ".omp", "agent", "sessions")
        self.make_chats()

    def tearDown(self):
        self.tmp.cleanup()

    def make_chats(self):
        write_jsonl(os.path.join(self.claude_root, "claude.jsonl"), [
            {
                "type": "user",
                "timestamp": "t1",
                "message": {"role": "user", "content": "Please make the Claude PR"},
            },
            {
                "type": "user",
                "isMeta": True,
                "message": {
                    "role": "user",
                    "content": "Stop hook feedback: injected status line",
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "toolu_1",
                            "name": "Bash",
                            "input": {"command": "gh pr create --fill"},
                        }
                    ],
                },
            },
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "https://github.com/owner/repo/pull/11",
                        }
                    ],
                },
            },
        ])
        write_jsonl(os.path.join(self.codex_root, "rollout-1.jsonl"), [
            {
                "type": "event_msg",
                "payload": {
                    "type": "user_message",
                    "message": "Run the workflow plan for this change",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "shell",
                    "arguments": "invoker-cli run plan.yaml --live",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "submitted wf-1789399890150-5",
                },
            },
        ])
        write_jsonl(os.path.join(self.claude_root, "mention.jsonl"), [
            {
                "type": "user",
                "timestamp": "t2",
                "message": {
                    "role": "user",
                    "content": "I saw https://github.com/owner/repo/pull/13 later",
                },
            }
        ])
        write_jsonl(os.path.join(self.omp_root, "omp.jsonl"), [
            {"message": "https://github.com/owner/repo/pull/12"}
        ])
        judge_dir = "llm" + "-judge"
        write_jsonl(os.path.join(self.claude_root, judge_dir, "judge.jsonl"), [
            {"message": "https://github.com/owner/repo/pull/11"}
        ])

    def invoke(self, out: str) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = [
            "link",
            "--repo",
            self.repo,
            "--paths",
            self.path,
            "--out",
            out,
            "--rev",
            "HEAD",
            "--prs-json",
            self.prs_path,
            "--repo-slug",
            "owner/repo",
            "--roots",
            self.claude_root,
            self.codex_root,
            self.omp_root,
        ]
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                code = commit_ledger.main(argv)
            except SystemExit as exc:
                code = int(exc.code)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_links_creation_outputs_and_records_explicit_states(self):
        out = os.path.join(self.root, "ledger.jsonl")
        code, stdout, stderr = self.invoke(out)
        self.assertEqual(code, 0, stderr)
        self.assertIn("commits=4 linked=2 unlinked=1 unchecked=1 excluded_chats=1", stdout)
        with open(out, encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        by_subject = {row["subject"]: row for row in rows}
        self.assertNotIn("Outside (#15)", by_subject)
        claude = by_subject["Claude PR (#11)"]
        self.assertEqual(claude["status"], "linked")
        self.assertEqual(claude["links"][0]["key"], "github.com/owner/repo/pull/11")
        self.assertEqual(claude["links"][0]["prior_human_messages"], ["Please make the Claude PR"])
        self.assertNotIn("Stop hook feedback", json.dumps(claude))
        codex = by_subject["Codex workflow"]
        self.assertEqual(codex["status"], "linked")
        self.assertEqual(codex["links"][0]["key"], "wf-1789399890150-5")
        mention = by_subject["Mention only (#13)"]
        self.assertEqual(mention["status"], "unlinked")
        omp = by_subject["OMP only (#12)"]
        self.assertEqual(omp["status"], "unchecked")
        self.assertEqual(omp["unchecked_chats"][0]["reason"], "tool-call shape not parsed")
        self.assertNotIn("llm" + "-judge", json.dumps(rows))
        self.assertIn("chat discovery:", stderr)

    def test_refuses_out_inside_repo_before_scanning(self):
        out = os.path.join(self.repo, "ledger.jsonl")
        code, stdout, stderr = self.invoke(out)
        self.assertEqual(code, 2)
        self.assertEqual(stdout, "")
        self.assertIn(os.path.realpath(out), stderr)
        self.assertIn(os.path.realpath(self.repo), stderr)

    def test_chat_read_error_is_unchecked(self):
        real_discover = commit_ledger.discover_chats
        real_contains = commit_ledger.chat_contains_any
        path = os.path.join(self.claude_root, "unreadable.jsonl")

        def discover(_roots, _keys):
            return [commit_ledger.CandidateChat(path, "claude")], 0

        def boom(_path, _keys):
            raise OSError("synthetic unreadable")

        commit_obj = commit_ledger.Commit("abc", "", "Unreadable (#99)", "")
        prs = [{
            "number": 99,
            "title": "Unreadable",
            "headRefName": "unreadable",
            "body": "",
            "mergeCommit": {"oid": "abc"},
        }]
        try:
            commit_ledger.discover_chats = discover
            commit_ledger.chat_contains_any = boom
            rows, excluded = commit_ledger.ledger_rows([commit_obj], prs, "owner/repo", [])
        finally:
            commit_ledger.discover_chats = real_discover
            commit_ledger.chat_contains_any = real_contains
        self.assertEqual(excluded, 0)
        self.assertEqual(rows[0]["status"], "unchecked")
        self.assertEqual(rows[0]["unchecked_chats"], [{
            "chat": path,
            "reason": "synthetic unreadable",
        }])


if __name__ == "__main__":
    unittest.main()
