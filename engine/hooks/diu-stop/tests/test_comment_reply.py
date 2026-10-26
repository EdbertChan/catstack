#!/usr/bin/env python3
"""The comment-reply gate: block, allow, or unchecked for every comment-posting call.

Run: python3 -m unittest discover -s engine/hooks/diu-stop/tests -v
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
HOOK_DIR = os.path.dirname(TESTS_DIR)
sys.path.insert(0, HOOK_DIR)

import comment_reply  # noqa: E402
import diu_limit  # noqa: E402

ENTRYPOINT = os.path.join(HOOK_DIR, "claude_pretooluse_comment.py")
FRAGMENT = os.path.join(HOOK_DIR, "claude.tool.hook.json")
README = os.path.join(HOOK_DIR, "README.md")
ARTIFACT_URL = "https://claude.ai/artifact/abc123"
LONG_REPLY = " ".join(["word"] * 70)
PLAIN_REPLY = (
    "Done. The second page now keeps the first page's fix, so the two no longer fight over the same file. "
    "Look at the top of the second section to see the new line."
)
JARGON_REPLY = "Mostly regex false positives."
ACK_REPLY = "On it. " + " ".join(["word"] * 43)
LONG_ACK_REPLY = "On it. " + " ".join(["word"] * 90)
DOCS_TOOLS = ("mcp__claude_ai_Claude_Docs__create", "mcp__claude_ai_Claude_Docs__batch", "mcp__claude_ai_Claude_Docs__update")


def run_entrypoint(stdin_text: str, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.pop("CATSTACK_HOOK_MODE_DIU_STOP", None)
    env.update(extra_env or {})
    with tempfile.TemporaryDirectory() as metrics:
        env["CATSTACK_HOOK_METRICS_DIR"] = metrics
        return subprocess.run(
            [sys.executable, ENTRYPOINT], input=stdin_text, capture_output=True, text=True, timeout=15, env=env,
        )


def artifact_reply(text, **extra) -> dict:
    payload = {
        "tool_name": "ArtifactComments",
        "tool_input": {"action": "reply", "url": ARTIFACT_URL, "thread_id": "thread-1", "text": text},
    }
    payload.update(extra)
    return payload


def docs_create(body) -> dict:
    return {
        "tool_name": "mcp__claude_ai_Claude_Docs__create",
        "tool_input": {
            "object": "utterance",
            "container": {"kind": "project", "id": "doc-1"},
            "payload": {"value": {"body": body, "parent": {"object": "utterance", "id": "root-1"}}},
        },
    }


def docs_batch(items) -> dict:
    return {
        "tool_name": "mcp__claude_ai_Claude_Docs__batch",
        "tool_input": {"container": {"kind": "project", "id": "doc-1"}, "batch": items},
    }


def docs_update(payload) -> dict:
    return {
        "tool_name": "mcp__claude_ai_Claude_Docs__update",
        "tool_input": {"ref": {"object": "utterance", "id": "utt-1"}, "container": {"kind": "project", "id": "doc-1"}, "payload": payload},
    }


def rule_ids(event) -> list[str]:
    return [finding.rule_id for finding in comment_reply.detect(event)]


class TestBlocks(unittest.TestCase):
    def test_blocks_a_70_word_artifact_reply(self):
        self.assertEqual(rule_ids(artifact_reply(LONG_REPLY)), [comment_reply.RULE_LENGTH])
        result = run_entrypoint(json.dumps(artifact_reply(LONG_REPLY)))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("70 words", result.stderr)
        self.assertIn("under 40 words", result.stderr)

    def test_blocks_a_45_word_reply(self):
        reply = " ".join(["word"] * 45)
        result = run_entrypoint(json.dumps(artifact_reply(reply)))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("45 words", result.stderr)

    def test_blocks_a_reply_with_a_flagged_jargon_word(self):
        findings = comment_reply.detect(artifact_reply(JARGON_REPLY))
        self.assertEqual([f.rule_id for f in findings], [comment_reply.RULE_JARGON])
        self.assertIn('a technical word "regex"', findings[0].message)
        result = run_entrypoint(json.dumps(artifact_reply(JARGON_REPLY)))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn('"regex"', result.stderr)

    def test_blocks_a_docs_create_utterance_over_the_cap(self):
        self.assertEqual(rule_ids(docs_create(LONG_REPLY)), [comment_reply.RULE_LENGTH])

    def test_blocks_a_docs_batch_utterance_with_a_code_name(self):
        items = [
            {"object": "node", "payload": {"markdown": "## Fixed"}},
            {"object": "utterance", "payload": {"value": {"body": "materialize_revision now calls realpath.", "parent": {"object": "utterance", "id": "root-1"}}}},
        ]
        findings = comment_reply.detect(docs_batch(items))
        self.assertEqual([f.rule_id for f in findings], [comment_reply.RULE_JARGON])
        self.assertIn('a code name "materialize_revision"', findings[0].message)

    def test_blocks_a_docs_update_utterance_with_two_negatives_in_one_sentence(self):
        findings = comment_reply.detect(docs_update("The retry does not run unless the queue is not empty."))
        self.assertEqual([f.rule_id for f in findings], [comment_reply.RULE_JARGON])
        self.assertIn("two negatives in one sentence", findings[0].message)

    def test_blocks_report_both_the_length_and_the_jargon_at_once(self):
        self.assertEqual(
            rule_ids(artifact_reply(LONG_REPLY + " Mostly regex false positives.")),
            [comment_reply.RULE_LENGTH, comment_reply.RULE_JARGON],
        )

    def test_flags_each_mechanical_kind_from_the_phrase_lists(self):
        hits = comment_reply.find_jargon(
            "It points at a real design gap in e2e-autofix. Set disable-model-invocation: true on the skill. "
            "It flips desiredEnabled: true. The script ships as an SEA. It died on a 401 unauthorized."
        )
        self.assertEqual(
            {(hit.kind, hit.text) for hit in hits},
            {
                ("an internal name", "e2e-autofix"),
                ("a code name", "disable-model-invocation:"),
                ("a code name", "desiredEnabled"),
                ("an abbreviation", "SEA"),
                ("a status code", "401 unauthorized"),
            },
        )


class TestAcknowledgements(unittest.TestCase):
    def test_allows_an_on_it_reply_up_to_the_acknowledgement_cap(self):
        self.assertGreater(diu_limit.comment_words(ACK_REPLY), 40)
        self.assertEqual(rule_ids(artifact_reply(ACK_REPLY)), [])
        result = run_entrypoint(json.dumps(artifact_reply(ACK_REPLY)))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocks_an_on_it_reply_over_the_acknowledgement_cap(self):
        self.assertEqual(rule_ids(artifact_reply(LONG_ACK_REPLY)), [comment_reply.RULE_LENGTH])
        result = run_entrypoint(json.dumps(artifact_reply(LONG_ACK_REPLY)))
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("under 50 words", result.stderr)

    def test_a_reply_that_does_not_open_with_an_acknowledgement_keeps_the_plain_cap(self):
        text = "Done. " + " ".join(["word"] * 43)
        self.assertEqual(rule_ids(artifact_reply(text)), [comment_reply.RULE_LENGTH])

    def test_every_opener_counts_whatever_the_case_and_leading_space(self):
        for opener in ("On it.", "  on it,", "Got it.", "Working on it.", "Will do.", "Looking into it."):
            self.assertTrue(diu_limit.is_acknowledgement(opener + " rest"), opener)
        for text in ("Done.", "Not on it yet.", "Gotten it wrong.", ""):
            self.assertFalse(diu_limit.is_acknowledgement(text), text)

    def test_limit_module_states_both_caps(self):
        self.assertEqual(diu_limit.ACKNOWLEDGEMENT_WORD_LIMIT, 50)
        self.assertEqual(diu_limit.comment_rule_text(acknowledgement=True), "under 50 words, not counting fenced code blocks or URLs")


class TestAllows(unittest.TestCase):
    def test_allows_a_30_word_plain_reply(self):
        self.assertLessEqual(diu_limit.comment_words(PLAIN_REPLY), 40)
        self.assertGreaterEqual(diu_limit.comment_words(PLAIN_REPLY), 30)
        self.assertEqual(rule_ids(artifact_reply(PLAIN_REPLY)), [])
        result = run_entrypoint(json.dumps(artifact_reply(PLAIN_REPLY)))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertEqual(result.stderr, "")

    def test_allows_a_plain_docs_create_batch_and_update_reply(self):
        for event in (docs_create(PLAIN_REPLY), docs_batch([docs_create(PLAIN_REPLY)["tool_input"]]), docs_update(PLAIN_REPLY)):
            with self.subTest(tool=event["tool_name"]):
                self.assertEqual(rule_ids(event), [])

    def test_allows_a_term_the_comment_itself_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            transcript = os.path.join(tmp, "session.jsonl")
            with open(transcript, "w", encoding="utf-8") as handle:
                handle.write(json.dumps({"type": "user", "message": {"role": "user", "content": "[Artifact comment sent to Claude] is this mostly a regex problem?"}}) + "\n")
            self.assertEqual(rule_ids(artifact_reply(JARGON_REPLY, transcript_path=transcript)), [])

    def test_allows_fenced_code_urls_and_citations_outside_the_count_and_the_jargon_check(self):
        reply = (
            PLAIN_REPLY
            + "\n\n```\n" + " ".join(["materialize_revision"] * 40) + "\n```\n"
            + "See https://example.com/some_path/with-dashes-1 and backtest_detector.py:102 @ origin/main."
        )
        self.assertEqual(rule_ids(artifact_reply(reply)), [])

    def test_allows_everyday_hyphens_and_abbreviations(self):
        self.assertEqual(comment_reply.find_jargon("The end-to-end check is OK; the PR is up-to-date, step-by-step."), [])

    def test_allows_an_artifact_read_watch_or_resolve(self):
        for action in ("read", "watch", "resolve"):
            with self.subTest(action=action):
                event = {"tool_name": "ArtifactComments", "tool_input": {"action": action, "url": ARTIFACT_URL, "thread_id": "t"}}
                self.assertIsNone(comment_reply.extract(event))

    def test_allows_docs_calls_that_post_no_comment(self):
        events = [
            {"tool_name": "mcp__claude_ai_Claude_Docs__create", "tool_input": {"object": "node", "payload": {"markdown": "## Heading"}}},
            {"tool_name": "mcp__claude_ai_Claude_Docs__update", "tool_input": {"ref": {"object": "node", "id": "n1"}, "payload": {"ops": []}}},
            {"tool_name": "mcp__claude_ai_Claude_Docs__batch", "tool_input": {"container": {"kind": "project", "create": {"name": "x"}}, "batch": []}},
            docs_create(None) | {"tool_input": {"object": "utterance", "payload": {"value": {"kind": "resolve", "parent": {"object": "utterance", "id": "r"}}}}},
        ]
        for event in events:
            with self.subTest(tool=event["tool_name"]):
                self.assertIsNone(comment_reply.extract(event))

    def test_allows_an_unrelated_tool(self):
        self.assertIsNone(comment_reply.extract({"tool_name": "Bash", "tool_input": {"command": "echo " + LONG_REPLY}}))
        result = run_entrypoint("{}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")


class TestUnchecked(unittest.TestCase):
    def test_unreadable_payload_is_unchecked_not_clean(self):
        result = run_entrypoint('{"tool_name": "ArtifactComments", "tool_input": {"action": "reply", "text": ')
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unchecked, not clean", result.stderr)

    def test_unreadable_payload_for_another_tool_is_not_this_gates_call(self):
        result = run_entrypoint('{"tool_name": "Bash", "tool_input": {"command": ')
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_reply_text_is_unchecked(self):
        findings = comment_reply.detect(artifact_reply(12345))
        self.assertEqual([f.rule_id for f in findings], [comment_reply.RULE_UNCHECKED])
        self.assertIn("a int, not a string", findings[0].message)

    def test_docs_utterance_without_a_body_is_unchecked(self):
        event = docs_create(None)
        event["tool_input"]["payload"] = {"value": {"parent": {"object": "utterance", "id": "r"}}}
        self.assertEqual(rule_ids(event), [comment_reply.RULE_UNCHECKED])
        batch = docs_batch([{"object": "utterance", "payload": 7}])
        self.assertEqual(rule_ids(batch), [comment_reply.RULE_UNCHECKED])

    def test_unreadable_tool_input_is_unchecked(self):
        self.assertEqual(rule_ids({"tool_name": "ArtifactComments", "tool_input": "reply"}), [comment_reply.RULE_UNCHECKED])
        self.assertEqual(rule_ids({"tool_name": "mcp__claude_ai_Claude_Docs__batch", "tool_input": {"batch": "x"}}), [comment_reply.RULE_UNCHECKED])

    def test_missing_transcript_still_checks_the_reply(self):
        event = artifact_reply(JARGON_REPLY, transcript_path="/nonexistent/session.jsonl")
        self.assertEqual(rule_ids(event), [comment_reply.RULE_JARGON])


class TestWiringAndAgreement(unittest.TestCase):
    def test_fragment_matches_every_comment_posting_tool_and_nothing_else(self):
        with open(FRAGMENT, encoding="utf-8") as handle:
            entries = json.load(handle)["hooks"]["PreToolUse"]
        self.assertEqual(len(entries), 1)
        matcher = entries[0]["matcher"]
        for tool in ("ArtifactComments",) + DOCS_TOOLS:
            self.assertIsNotNone(re.fullmatch(matcher, tool), (matcher, tool))
        for tool in ("Bash", "mcp__claude_ai_Claude_Docs__read", "mcp__claude_ai_Claude_Docs__delete"):
            self.assertIsNone(re.fullmatch(matcher, tool), (matcher, tool))
        self.assertIn("diu-stop/claude_pretooluse_comment.py", entries[0]["hooks"][0]["command"])

    def test_limit_module_block_message_and_readme_state_the_same_cap(self):
        self.assertEqual(diu_limit.COMMENT_WORD_LIMIT, 40)
        self.assertEqual(diu_limit.comment_rule_text(), "under 40 words, not counting fenced code blocks or URLs")
        with open(README, encoding="utf-8") as handle:
            readme = handle.read()
        self.assertIn("under 40 words", readme)
        self.assertIn("claude_pretooluse_comment.py", readme)

    def test_rule_ids_are_namespaced(self):
        for rule in (comment_reply.RULE_LENGTH, comment_reply.RULE_JARGON, comment_reply.RULE_UNCHECKED):
            self.assertTrue(rule.startswith("diu-stop.comment-reply-"), rule)


if __name__ == "__main__":
    unittest.main()
