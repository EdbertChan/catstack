#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import spend_ledger
import token_audit

SCRIPT = os.path.join(SCRIPTS_DIR, "spend_ledger.py")


def write_jsonl(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(entry if isinstance(entry, str) else json.dumps(entry))
            handle.write("\n")


def usage(read=0, write=0, output=0, fresh=0):
    return {"input_tokens": fresh, "cache_read_input_tokens": read, "cache_creation_input_tokens": write,
            "output_tokens": output, "cache_creation": {"ephemeral_5m_input_tokens": write, "ephemeral_1h_input_tokens": 0}}


def assistant(message_id, blocks, use, stamp, model="claude-sonnet-5", sidechain=False):
    return {"type": "assistant", "requestId": f"req-{message_id}", "timestamp": stamp, "isSidechain": sidechain,
            "message": {"id": message_id, "model": model, "usage": use, "content": blocks}}


def user(text, stamp, cwd="/Users/me/Documents/GitHub/app"):
    return {"type": "user", "timestamp": stamp, "cwd": cwd, "message": {"role": "user", "content": text}}


def bash(command, tool_id):
    return {"type": "tool_use", "id": tool_id, "name": "Bash", "input": {"command": command}}


class SpendLedgerFixture(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="spend-ledger-home-")
        projects = os.path.join(self.home, ".claude", "projects", "-Users-me-app")
        one_million = usage(read=1_000_000)
        entries = [
            user("fix the flaky test please", "2026-09-01T10:00:00Z"),
            user("<task-notification>done</task-notification>", "2026-09-01T10:00:30Z"),
            assistant("m1", [{"type": "text", "text": "looking"}], one_million, "2026-09-01T10:01:00Z"),
            assistant("m1", [bash("gh pr checks 42", "t1")], one_million, "2026-09-01T10:01:00Z"),
            user("and land it", "2026-09-01T11:00:00Z"),
        ]
        for index in range(5):
            entries.append(assistant(f"r{index}", [bash("git status", f"s{index}")], one_million,
                                     f"2026-09-01T11:0{index}:00Z"))
        entries.append(assistant("w1", [{"type": "tool_use", "id": "w", "name": "ScheduleWakeup", "input": {}}],
                                 one_million, "2026-09-01T12:00:00Z"))
        entries.append("not json at all")
        write_jsonl(os.path.join(projects, "sess-typed.jsonl"), entries)
        write_jsonl(os.path.join(projects, "sess-typed", "subagents", "agent-1.jsonl"), [
            assistant("a1", [{"type": "text", "text": "helper"}], usage(output=1_000_000), "2026-09-01T10:30:00Z",
                      sidechain=True),
        ])
        write_jsonl(os.path.join(projects, "sess-script.jsonl"), [
            user("one shot", "2026-09-02T10:00:00Z"),
            assistant("x1", [{"type": "text", "text": "ok"}], usage(output=1000), "2026-09-02T10:00:05Z"),
        ])
        worktree = os.path.join(self.home, ".claude", "projects", "-Users-me--invoker-worktrees-abc")
        write_jsonl(os.path.join(worktree, "sess-fleet.jsonl"), [
            user("task prompt", "2026-09-03T10:00:00Z", cwd="/Users/me/.invoker/worktrees/abc"),
            user("follow up", "2026-09-03T10:01:00Z", cwd="/Users/me/.invoker/worktrees/abc"),
            assistant("f1", [], usage(output=1000), "2026-09-03T10:02:00Z"),
        ])
        rollout = "rollout-2026-09-04T10-00-00-11111111-2222-3333-4444-555555555555.jsonl"
        write_jsonl(os.path.join(self.home, ".codex", "sessions", "2026", "09", "04", rollout), [
            {"type": "session_meta", "timestamp": "2026-09-04T10:00:00Z",
             "payload": {"cwd": "/Users/me/app", "originator": "codex_exec"}},
            {"type": "turn_context", "payload": {"model": "gpt-5.6-sol"}},
            {"type": "event_msg", "timestamp": "2026-09-04T10:05:00Z", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": 1_000_000, "cached_input_tokens": 900_000, "output_tokens": 100_000}}}},
        ])
        agent_logs = os.path.join(self.home, ".invoker", "agent-sessions")
        write_jsonl(os.path.join(agent_logs, "11111111-2222-3333-4444-555555555555.jsonl"), [
            {"type": "turn.completed", "usage": {"input_tokens": 999, "output_tokens": 9}},
        ])
        write_jsonl(os.path.join(agent_logs, "99999999-2222-3333-4444-555555555555.jsonl"), [
            "[SshExecutor] Installing managed worktree dependencies...",
            {"type": "thread.started"},
            {"type": "turn.completed", "usage": {"input_tokens": 500, "cached_input_tokens": 200, "output_tokens": 50}},
        ])
        self.report = spend_ledger.run_scan(3650, "test-host", False, home=self.home)
        self.rows = {row["session"]: row for row in self.report["sessions"]}

    def test_split_lines_are_priced_once_and_tool_calls_are_merged(self):
        typed = self.rows["sess-typed"]
        self.assertEqual(typed["calls"] - typed["sub_calls"], 7)
        own_read_cost = 7 * 1_000_000 * 2.0 * 0.1 / 1e6
        helper_output_cost = 1_000_000 * 10.0 / 1e6
        self.assertAlmostEqual(typed["cost_total"], own_read_cost + helper_output_cost, places=4)

    def test_subagents_are_attributed_to_the_parent(self):
        typed = self.rows["sess-typed"]
        self.assertEqual(typed["sub_calls"], 1)
        self.assertAlmostEqual(typed["sub_cost"], 10.0, places=4)
        self.assertNotIn("agent-1", self.rows)

    def test_waiting_and_repeated_commands_are_costed(self):
        polling = self.rows["sess-typed"]["polling"]
        self.assertAlmostEqual(polling["waiting"], 2 * 0.2, places=4)
        self.assertAlmostEqual(polling["repeat"], 5 * 0.2, places=4)

    def test_who_started_the_session(self):
        self.assertEqual(self.rows["sess-typed"]["kind"], "typed")
        self.assertEqual(self.rows["sess-typed"]["prompts"], 2)
        self.assertEqual(self.rows["sess-script"]["kind"], "scripted")
        self.assertEqual(self.rows["sess-fleet"]["kind"], "invoker")

    def test_codex_is_an_estimate_and_agent_logs_are_not_double_counted(self):
        codex = [row for row in self.report["sessions"] if row["tool"] == "codex"]
        self.assertEqual(len(codex), 1)
        expected = (100_000 * 4.0 + 900_000 * 0.40 + 100_000 * 20.0) / 1e6
        self.assertAlmostEqual(codex[0]["cost_total"], expected, places=4)
        self.assertEqual(codex[0]["priced"], "estimate")
        self.assertEqual(codex[0]["kind"], "invoker")
        logs = [row for row in self.report["sessions"] if row["tool"] == "invoker-agent-log"]
        self.assertEqual([row["session"] for row in logs], ["99999999-2222-3333-4444-555555555555"])
        self.assertEqual(logs[0]["priced"], "unpriced")
        self.assertEqual(self.report["status"]["agent_log_already_in_codex_rollouts"], 1)

    def test_unreadable_lines_are_counted_not_silently_dropped(self):
        self.assertGreaterEqual(self.report["status"]["non_object_lines"], 2)


class SpendLedgerFleet(unittest.TestCase):
    def test_unreachable_host_is_unchecked_not_zero(self):
        home = tempfile.mkdtemp(prefix="spend-ledger-fleet-")
        config = os.path.join(home, "config.json")
        with open(config, "w", encoding="utf-8") as handle:
            json.dump({"remoteTargets": {"box": {"host": "203.0.113.9", "user": "invoker"}}}, handle)
        out = os.path.join(home, "ledger.json")
        env = dict(os.environ, HOME=home)
        proc = subprocess.run([sys.executable, SCRIPT, "fleet", "--days", "1", "--config", config, "--out", out,
                               "--ssh", "false"], capture_output=True, text=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(out, encoding="utf-8") as handle:
            ledger = json.load(handle)
        box = [host for host in ledger["hosts"] if host["name"] == "box"][0]
        self.assertEqual(box["state"], "unchecked")
        self.assertIn("exit", box["reason"])
        self.assertIn("unchecked: box", proc.stdout)

    def test_unreadable_config_is_unchecked(self):
        home = tempfile.mkdtemp(prefix="spend-ledger-noconfig-")
        ledger = spend_ledger.run_fleet(1, os.path.join(home, "missing.json"), ["false"], 5, "local")
        self.assertEqual(ledger["hosts"][-1]["state"], "unchecked")


class PricingAgreement(unittest.TestCase):
    def test_token_audit_and_spend_ledger_agree(self):
        for model, prices in token_audit.PRICING.items():
            rate_in, rate_out, read_multiplier = spend_ledger.CLAUDE_PRICES[model]
            self.assertAlmostEqual(prices["input"], rate_in, msg=model)
            self.assertAlmostEqual(prices["output"], rate_out, msg=model)
            self.assertAlmostEqual(prices["cache_read"], rate_in * read_multiplier, msg=model)

    def test_help_prints_usage(self):
        proc = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Usage", proc.stdout)


if __name__ == "__main__":
    unittest.main()
