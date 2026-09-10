#!/usr/bin/env python3
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SCRIPTS_DIR)

import token_audit  # noqa: E402


def human(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def bash(command):
    return {"type": "assistant", "message": {"id": command[:20], "content": [
        {"type": "tool_use", "id": "t", "name": "Bash", "input": {"command": command}},
    ]}}


def write(path, content):
    return {"type": "assistant", "message": {"id": path, "content": [
        {"type": "tool_use", "id": "w", "name": "Write", "input": {"file_path": path, "content": content}},
    ]}}


def conformance(rows):
    msgs = [
        (i, None, r["message"]["content"])
        for i, r in enumerate(rows)
        if r["type"] == "user" and isinstance(r["message"]["content"], str)
    ]
    return token_audit.instruction_conformance(rows, msgs)


PARTIAL_UPDATE = (
    "sqlite3 invoker.db \"update tasks set pool_id='local-worktree', execution_agent='claude' "
    "where status in ('pending','queued')\""
)
FULL_UPDATE = (
    "sqlite3 invoker.db \"update tasks set pool_id='local-worktree' "
    "where COALESCE(pool_id,'') <> 'local-worktree'\""
)


class TestScopeExtraction(unittest.TestCase):
    def test_quantifier_target_and_verb(self):
        found = token_audit.extract_scoped_directive("can you make all tasks use claude and local executor")
        self.assertEqual(found["verbs"], ["make"])
        self.assertEqual([(s["quantifier"], s["head"]) for s in found["scopes"]], [("all", "tasks")])

    def test_scope_fronted_before_the_verb(self):
        found = token_audit.extract_scoped_directive("also for all prs and merge gates, use ai claude agent")
        self.assertEqual([s["stem"] for s in found["scopes"]], ["pr", "gate"])
        self.assertEqual(found["scopes"][1]["qualifiers"], ["merge"])

    def test_the_whole_and_each(self):
        found = token_audit.extract_scoped_directive("scan the whole corpus and report each session")
        self.assertEqual([(s["quantifier"], s["stem"]) for s in found["scopes"]],
                         [("the whole", "corpus"), ("each", "session")])

    def test_look_at_all_is_a_scope_but_at_all_alone_is_not(self):
        found = token_audit.extract_scoped_directive("please look at all the sessions on the droplets")
        self.assertEqual([s["stem"] for s in found["scopes"]], ["session"])
        self.assertIsNone(token_audit.extract_scoped_directive("do not change it at all"))

    def test_question_is_not_a_directive(self):
        self.assertIsNone(token_audit.extract_scoped_directive("are all failed tasks using claude? yes or no?"))

    def test_request_phrased_as_question_is_a_directive(self):
        found = token_audit.extract_scoped_directive("can we tag all the prs with admin-bypass in catstack?")
        self.assertEqual([s["stem"] for s in found["scopes"]], ["pr"])

    def test_declarative_sentence_is_not_a_directive(self):
        self.assertIsNone(token_audit.extract_scoped_directive("Review claim: the report covers both conventions."))

    def test_pasted_log_line_is_not_a_directive(self):
        self.assertIsNone(token_audit.extract_scoped_directive(
            "FAIL src/registry.test.ts > registers every built-in worker"))

    def test_pronoun_target_has_no_stem(self):
        found = token_audit.extract_scoped_directive("just do all of them")
        self.assertEqual([s["stem"] for s in found["scopes"]], [None])


class TestInstructionConformance(unittest.TestCase):
    def test_partial_status_filter_on_the_named_table_is_a_narrowing(self):
        c = conformance([human("make all tasks use the local-worktree pool"), bash(PARTIAL_UPDATE)])
        self.assertEqual((c["scoped"], c["narrowed"], c["undetermined"]), (1, 1, 0))
        self.assertIn("status in ('pending','queued')", c["directives"][0]["evidence"][0]["predicate"])

    def test_update_over_every_row_with_an_idempotency_guard_is_not_a_narrowing(self):
        c = conformance([human("make all tasks use claude"), bash(FULL_UPDATE)])
        self.assertEqual((c["scoped"], c["narrowed"], c["covered"]), (1, 0, 1))

    def test_filter_value_the_user_named_is_not_a_narrowing(self):
        c = conformance([
            human("make all failed tasks use claude"),
            bash("sqlite3 db \"update tasks set execution_agent='claude' where status in ('failed')\""),
        ])
        self.assertEqual((c["narrowed"], c["covered"]), (0, 1))

    def test_pronoun_target_is_undetermined(self):
        c = conformance([human("just do all of them"), bash(PARTIAL_UPDATE)])
        self.assertEqual((c["scoped"], c["undetermined"]), (1, 1))
        self.assertEqual(c["directives"][0]["reason"], "the scope names no target noun")

    def test_action_after_the_next_human_turn_is_outside_the_window(self):
        c = conformance([human("make all tasks use claude"), human("go ahead"), bash(PARTIAL_UPDATE)])
        self.assertEqual((c["scoped"], c["narrowed"], c["undetermined"]), (1, 0, 1))

    def test_filtered_read_does_not_count_as_the_action_for_a_change_directive(self):
        c = conformance([
            human("make all tasks use claude"),
            bash("sqlite3 db \"select id from tasks where status in ('pending')\""),
        ])
        self.assertEqual((c["narrowed"], c["undetermined"]), (0, 1))

    def test_filtered_read_counts_for_an_inspect_directive(self):
        c = conformance([
            human("show all tasks and their pools"),
            bash("sqlite3 db \"select id, pool_id from tasks where status in ('pending')\""),
        ])
        self.assertEqual(c["narrowed"], 1)

    def test_named_set_membership_in_a_mutating_script_is_a_narrowing(self):
        script = (
            "invoker-cli query tasks --output json > t.json\n"
            "python3 - <<'EOF' > ops.txt\n"
            "ACTIVE = {'running', 'fixing_with_ai'}\n"
            "for t in json.load(open('t.json')):\n"
            "    if t['status'] in ACTIVE:\n"
            "        continue\n"
            "    print(t['id'])\n"
            "EOF\n"
            "xargs -L1 invoker-ui --headless set task-pool < ops.txt\n"
        )
        c = conformance([human("make all tasks use local-only"), write("/tmp/move.sh", script)])
        self.assertEqual(c["narrowed"], 1)
        self.assertEqual(c["directives"][0]["evidence"][0]["predicate"], "t['status'] in ACTIVE")

    def test_cli_state_filter_in_a_mutating_command_is_a_narrowing(self):
        c = conformance([
            human("tag all the prs with admin-bypass"),
            bash("for n in $(gh pr list --state open --json number); do gh pr edit $n --add-label admin-bypass; done"),
        ])
        self.assertEqual(c["narrowed"], 1)

    def test_boolean_partition_across_two_updates_is_not_a_narrowing(self):
        c = conformance([
            human("make all tasks use claude"),
            bash("sqlite3 db \"update tasks set execution_agent='claude' where is_merge_node=0\"\n"
                 "sqlite3 db \"update tasks set execution_agent='claude' where is_merge_node=1\""),
        ])
        self.assertEqual((c["narrowed"], c["covered"]), (0, 1))

    def test_hook_relay_row_does_not_end_the_window(self):
        c = conformance([
            human("make all tasks use the local-worktree pool"),
            human("Stop hook feedback: keep replies short"),
            bash(PARTIAL_UPDATE),
        ])
        self.assertEqual(c["narrowed"], 1)

    def test_no_human_rows_is_unchecked_not_clean(self):
        c = token_audit.instruction_conformance([bash(PARTIAL_UPDATE)], [])
        self.assertIsNone(c["scoped"])
        flag = token_audit._conformance_flag(c)
        self.assertEqual((flag["value"], flag["count"]), ("unchecked", None))


class TestConformanceFlag(unittest.TestCase):
    def flag(self, rows):
        return token_audit._conformance_flag(conformance(rows))

    def test_yes_when_a_narrowing_is_found(self):
        flag = self.flag([human("make all tasks use the local-worktree pool"), bash(PARTIAL_UPDATE)])
        self.assertEqual((flag["value"], flag["count"]), ("yes", 1))

    def test_unchecked_when_nothing_narrowed_but_a_directive_was_undetermined(self):
        flag = self.flag([human("make all tasks use claude")])
        self.assertEqual((flag["value"], flag["count"]), ("unchecked", 0))
        self.assertIn("undetermined=1", flag["rationale"])

    def test_no_when_every_directive_was_covered(self):
        flag = self.flag([human("make all tasks use claude"), bash(FULL_UPDATE)])
        self.assertEqual((flag["value"], flag["count"]), ("no", 0))

    def test_no_when_there_is_no_scoped_directive(self):
        flag = self.flag([human("fix the flaky test"), bash("pytest -x")])
        self.assertEqual((flag["value"], flag["count"]), ("no", 0))


class TestAuditClaudeReportsConformance(unittest.TestCase):
    def test_out_report_carries_the_three_counts_and_the_flag(self):
        rows = [human("make all tasks use the local-worktree pool"), bash(PARTIAL_UPDATE)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
            path = f.name
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out = f.name
        try:
            with redirect_stdout(io.StringIO()) as buf:
                token_audit.audit_claude(path, out_path=out, include_subagents=False)
            with open(out) as fh:
                report = json.load(fh)
            self.assertEqual(
                {k: report["conformance"][k] for k in ("scoped", "narrowed", "undetermined")},
                {"scoped": 1, "narrowed": 1, "undetermined": 0},
            )
            flag = next(fl for fl in report["flags"] if fl["name"] == "instruction-conformance")
            self.assertEqual(flag["value"], "yes")
            self.assertIn("instruction-conformance: yes (count=1)", buf.getvalue())
        finally:
            os.unlink(path)
            os.unlink(out)


if __name__ == "__main__":
    unittest.main()
