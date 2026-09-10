#!/usr/bin/env python3
"""Tests for the invoker-db-guard PreToolUse (Bash) hook.

Run: python3 -m unittest discover -s engine/hooks/invoker-db-guard/tests -v

Every fixture under fixtures/ is a whole hook payload plus the outcome it
must produce. Each one carries a `source` field: `transcript` means the
command string is verbatim from a real session's Bash tool call, `constructed`
means it was written here to cover a shape the corpus had no example of.
The three outcomes are hit, clean and unchecked, and every fixture asserts
one of them by name.
"""
from __future__ import annotations

import io
import json
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

HOOK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
sys.path.insert(0, HOOK_DIR)

import claude_pretooluse  # noqa: E402
import detect  # noqa: E402
import install_claude_hook  # noqa: E402


def load_fixture(name: str) -> dict:
    with open(os.path.join(FIXTURE_DIR, name + ".json"), encoding="utf-8") as handle:
        return json.load(handle)


def fixture_names() -> list[str]:
    return sorted(n[:-5] for n in os.listdir(FIXTURE_DIR) if n.endswith(".json"))


def outcome_of(name: str) -> tuple[str, list[str]]:
    fixture = load_fixture(name)
    return detect.pretooluse_outcome(json.dumps(fixture["payload"]))


def run_entrypoint(payload: object) -> tuple[int, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    err = io.StringIO()
    code = 0
    with patch.object(sys, "stdin", io.StringIO(raw)), redirect_stderr(err), redirect_stdout(io.StringIO()):
        try:
            claude_pretooluse.main()
        except SystemExit as exit_exc:
            code = int(exit_exc.code or 0)
    return code, err.getvalue()


class FixtureContract(unittest.TestCase):
    def test_every_fixture_reaches_the_outcome_it_declares(self):
        names = fixture_names()
        self.assertGreater(len(names), 20, names)
        for name in names:
            with self.subTest(fixture=name):
                expected = load_fixture(name)["expect"]
                self.assertIn(expected, ("hit", "clean", "unchecked"))
                self.assertEqual(outcome_of(name)[0], expected)

    def test_every_fixture_declares_transcript_or_constructed_provenance(self):
        for name in fixture_names():
            with self.subTest(fixture=name):
                self.assertIn(load_fixture(name)["source"], ("transcript", "constructed"))

    def test_at_least_one_transcript_payload_backs_each_outcome_the_corpus_has(self):
        sourced = {}
        for name in fixture_names():
            fixture = load_fixture(name)
            sourced.setdefault(fixture["expect"], set()).add(fixture["source"])
        self.assertIn("transcript", sourced["hit"])
        self.assertIn("transcript", sourced["clean"])


class WriteShapesBlock(unittest.TestCase):
    def test_writable_python_connect_plus_routing_update_is_a_hit(self):
        outcome, messages = outcome_of("positive_python_update_routing_columns")
        self.assertEqual(outcome, "hit")
        self.assertIn("invoker-cli route-task", messages[0])
        self.assertIn("execution_agent", messages[0])
        self.assertIn("pool_id", messages[0])

    def test_all_five_routing_columns_in_one_update_are_named_in_the_block(self):
        _outcome, messages = outcome_of("positive_python_update_repoint_five_routing_columns")
        for column in ("execution_agent", "pool_id", "pool_member_id", "remote_target_id", "runner_kind"):
            self.assertIn(column, messages[0])

    def test_route_task_is_marked_as_landing_rather_than_shipped(self):
        _outcome, messages = outcome_of("positive_python_update_routing_columns")
        self.assertIn("landing, not shipped", messages[0])

    def test_status_update_block_names_retry_task_retry_and_resume(self):
        outcome, messages = outcome_of("positive_cli_update_task_status")
        self.assertEqual(outcome, "hit")
        self.assertIn("invoker-cli retry-task <taskId>", messages[0])
        self.assertIn("invoker-cli retry <workflowId>", messages[0])
        self.assertIn("invoker-cli resume <workflowId>", messages[0])

    def test_workflow_delete_block_names_invoker_cli_delete(self):
        outcome, messages = outcome_of("positive_cli_delete_workflow_rows")
        self.assertEqual(outcome, "hit")
        self.assertIn("invoker-cli delete <workflowId>", messages[0])

    def test_heredoc_sql_through_a_shell_variable_is_a_hit(self):
        outcome, messages = outcome_of("positive_cli_heredoc_through_shell_variable")
        self.assertEqual(outcome, "hit")
        self.assertIn("invoker-cli delete <workflowId>", messages[0])

    def test_uncovered_column_block_says_no_headless_command_covers_it(self):
        outcome, messages = outcome_of("positive_python_update_config_blob_uncovered")
        self.assertEqual(outcome, "hit")
        self.assertIn("no headless command covers tasks.config", messages[0])
        self.assertIn("add one", messages[0])
        self.assertNotIn("route-task", messages[0])

    def test_pragma_writable_schema_is_a_hit_with_no_command_to_offer(self):
        outcome, messages = outcome_of("positive_cli_pragma_writable_schema")
        self.assertEqual(outcome, "hit")
        self.assertIn("no headless command covers this statement", messages[0])

    def test_insert_and_alter_both_hit(self):
        self.assertEqual(outcome_of("positive_cli_insert_row")[0], "hit")
        self.assertEqual(outcome_of("positive_cli_alter_table")[0], "hit")

    def test_writable_open_whose_statements_are_all_selects_still_hits(self):
        outcome, messages = outcome_of("positive_python_writable_open_with_only_selects")
        self.assertEqual(outcome, "hit")
        self.assertIn("read-write", messages[0])
        self.assertIn("mode=ro", messages[0])

    def test_mutating_execute_on_a_readonly_connection_hits(self):
        outcome, messages = outcome_of("positive_python_readonly_uri_with_mutating_execute")
        self.assertEqual(outcome, "hit")
        self.assertIn("mutating statement is executed", messages[0])

    def test_an_aliased_sqlite3_import_is_a_hit(self):
        outcome, messages = outcome_of("positive_python_aliased_sqlite3_import")
        self.assertEqual(outcome, "hit")
        self.assertIn("invoker-cli delete <workflowId>", messages[0])

    def test_sql_carried_by_a_flag_ahead_of_the_path_is_a_hit(self):
        outcome, messages = outcome_of("positive_cli_sql_carried_by_a_flag_before_the_path")
        self.assertEqual(outcome, "hit")
        self.assertIn("tasks.runner_kind", messages[0])

    def test_sqlite3_after_a_cd_in_the_same_command_is_a_hit(self):
        self.assertEqual(outcome_of("positive_cli_chained_after_a_cd")[0], "hit")

    def test_no_early_exit_every_applicable_command_is_named(self):
        outcome, messages = outcome_of("positive_cli_four_intents_in_one_command")
        self.assertEqual(outcome, "hit")
        for expected in (
            "invoker-cli route-task",
            "invoker-cli retry-task <taskId>",
            "invoker-cli delete <workflowId>",
            "no headless command covers tasks.notes",
        ):
            self.assertIn(expected, messages[0])

    def test_every_block_message_names_the_owner_write_path(self):
        for name in fixture_names():
            if not name.startswith("positive_"):
                continue
            with self.subTest(fixture=name):
                self.assertIn("writer lock", outcome_of(name)[1][0])


class SilentShapes(unittest.TestCase):
    def test_readonly_uri_with_pragma_table_info_is_clean(self):
        self.assertEqual(outcome_of("negative_python_readonly_uri_pragma_table_info")[0], "clean")

    def test_readonly_uri_built_from_an_fstring_variable_is_clean(self):
        self.assertEqual(outcome_of("negative_python_readonly_fstring_variable_path")[0], "clean")

    def test_readonly_uri_built_from_a_shell_variable_is_clean(self):
        self.assertEqual(outcome_of("negative_shell_variable_readonly_python_c")[0], "clean")

    def test_sqlite_master_read_is_clean(self):
        self.assertEqual(outcome_of("negative_python_readonly_sqlite_master_select")[0], "clean")

    def test_select_only_cli_invocation_is_clean(self):
        self.assertEqual(outcome_of("negative_cli_select_only")[0], "clean")

    def test_cli_readonly_flag_is_clean(self):
        self.assertEqual(outcome_of("negative_cli_readonly_flag_count")[0], "clean")

    def test_a_write_to_some_other_database_is_clean(self):
        self.assertEqual(outcome_of("negative_update_against_an_unrelated_database")[0], "clean")

    def test_listing_the_database_and_reading_the_owner_marker_is_clean(self):
        self.assertEqual(outcome_of("negative_reads_owner_marker_and_file_sizes")[0], "clean")

    def test_a_temp_dir_database_opened_by_the_adapter_is_clean(self):
        self.assertEqual(outcome_of("negative_sqlite_adapter_tmpdir_invoker_db")[0], "clean")

    def test_the_headless_commands_this_hook_recommends_are_clean(self):
        self.assertEqual(outcome_of("negative_headless_command_does_the_write")[0], "clean")

    def test_a_headless_toggle_with_a_readonly_readback_is_clean(self):
        self.assertEqual(outcome_of("negative_cli_toggle_readback_then_readonly_query")[0], "clean")

    def test_the_incident_sql_as_write_tool_content_is_clean(self):
        self.assertEqual(outcome_of("negative_write_tool_content_is_not_a_command")[0], "clean")

    def test_every_silent_fixture_produces_no_message_at_all(self):
        for name in fixture_names():
            if not name.startswith("negative_"):
                continue
            with self.subTest(fixture=name):
                self.assertEqual(outcome_of(name)[1], [])


class UncheckedIsNotClean(unittest.TestCase):
    def test_unbound_database_variable_is_unchecked_not_clean(self):
        outcome, messages = outcome_of("unchecked_unbound_database_variable")
        self.assertEqual(outcome, "unchecked")
        self.assertIn("UNCHECKED", messages[0])
        self.assertIn("could not be resolved", messages[0])

    def test_sql_redirected_from_a_file_is_unchecked_not_clean(self):
        outcome, messages = outcome_of("unchecked_sql_redirected_from_a_file")
        self.assertEqual(outcome, "unchecked")
        self.assertIn("its SQL is not in this command", messages[0])

    def test_connect_path_from_the_environment_is_unchecked_not_clean(self):
        outcome, messages = outcome_of("unchecked_connect_path_from_the_environment")
        self.assertEqual(outcome, "unchecked")
        self.assertIn("UNCHECKED", messages[0])

    def test_unchecked_blocks_and_says_a_check_that_could_not_run_is_not_a_pass(self):
        code, err = run_entrypoint(load_fixture("unchecked_unbound_database_variable")["payload"])
        self.assertEqual(code, 2)
        self.assertIn("A check that could not run is not a pass", err)

    def test_an_unparseable_invocation_is_unchecked_not_clean(self):
        outcome, messages = outcome_of("unchecked_unparseable_shell_fragment")
        self.assertEqual(outcome, "unchecked")
        self.assertIn("UNCHECKED", messages[0])

    def test_an_unresolvable_target_with_no_invoker_mention_stays_silent(self):
        outcome, _messages = detect.problems('sqlite3 "$DB" "UPDATE runs SET status=1"')
        self.assertEqual(outcome, "clean")


class TargetResolver(unittest.TestCase):
    def test_every_spelling_of_the_database_path_resolves_to_the_target(self):
        for spelling in (
            "/home/edbert-chan/.invoker/invoker.db",
            "~/.invoker/invoker.db",
            "$HOME/.invoker/invoker.db",
            "${HOME}/.invoker/invoker.db",
            "invoker.db",
            "/home/invoker/.invoker/invoker.db-wal",
            "~/.invoker/invoker.db-shm",
            "file:/home/edbert-chan/.invoker/invoker.db?mode=ro",
        ):
            with self.subTest(spelling=spelling):
                self.assertTrue(detect.targets_invoker_db(spelling))

    def test_the_sidecar_marker_files_are_not_the_database(self):
        for other in (
            "/home/edbert-chan/.invoker/invoker.db.owner",
            "/home/edbert-chan/.invoker/invoker.db.lock",
            "/tmp/scratch/invoker.db.bak-140233",
            "/home/edbert-chan/.invoker/invoker.log",
            "/tmp/scratch.db",
        ):
            with self.subTest(other=other):
                self.assertFalse(detect.targets_invoker_db(other))

    def test_a_shell_assignment_binds_the_path_for_later_expansion(self):
        command = 'DB=/home/edbert-chan/.invoker/invoker.db\nsqlite3 "$DB" "select 1"'
        bindings = detect.shell_and_python_bindings(command)
        self.assertEqual(bindings["DB"], "/home/edbert-chan/.invoker/invoker.db")
        self.assertTrue(detect.targets_invoker_db(detect.expand("$DB", bindings)))

    def test_a_python_assignment_binds_the_path_for_later_expansion(self):
        command = "db='/home/invoker/.invoker/invoker.db'\nc=sqlite3.connect(db)"
        bindings = detect.shell_and_python_bindings(command)
        self.assertTrue(detect.targets_invoker_db(detect.expand("{db}", bindings)))

    def test_home_expands_without_reading_the_running_users_environment(self):
        bindings = detect.shell_and_python_bindings("echo hi")
        self.assertEqual(detect.expand("$HOME/.invoker/invoker.db", bindings), "~/.invoker/invoker.db")


class IntentMapping(unittest.TestCase):
    def test_assigned_columns_are_read_from_the_set_clause_only(self):
        sql = (
            "update tasks set execution_agent='claude'\n"
            "  where is_merge_node=1 and status not in ('completed','skipped')"
        )
        self.assertEqual(detect.assigned_columns(sql), {"execution_agent"})

    def test_insert_column_list_is_read(self):
        sql = "INSERT INTO tasks (id, workflow_id, status) VALUES ('a','b','c')"
        self.assertEqual(detect.assigned_columns(sql), {"id", "workflow_id", "status"})

    def test_delete_and_drop_name_their_tables(self):
        self.assertEqual(detect.deleted_tables("DELETE FROM workflows WHERE id='x'"), {"workflows"})
        self.assertEqual(detect.deleted_tables("DROP TABLE IF EXISTS tasks"), {"tasks"})

    def test_a_select_is_not_mutating(self):
        self.assertFalse(detect.is_mutating("select id, status from tasks where status='running'"))

    def test_pragma_reads_are_not_mutating_and_writable_schema_is(self):
        self.assertFalse(detect.is_mutating('c.execute("PRAGMA busy_timeout=20000")'))
        self.assertFalse(detect.is_mutating('cols=[r[1] for r in c.execute("PRAGMA table_info(tasks)")]'))
        self.assertTrue(detect.is_mutating("PRAGMA writable_schema=ON"))


class FailsOpenOnInputItCannotParse(unittest.TestCase):
    def test_malformed_payload_fails_open_and_prints_nothing(self):
        code, err = run_entrypoint("{not json at all")
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_missing_tool_input_fails_open(self):
        code, err = run_entrypoint({"tool_name": "Bash"})
        self.assertEqual(code, 0)
        self.assertEqual(err, "")

    def test_a_non_shell_tool_fails_open(self):
        code, _err = run_entrypoint({"tool_name": "Read", "tool_input": {"command": "sqlite3 ~/.invoker/invoker.db 'DROP TABLE tasks'"}})
        self.assertEqual(code, 0)

    def test_an_unterminated_quote_in_the_command_does_not_crash_the_hook(self):
        outcome, _messages = detect.problems("sqlite3 ~/.invoker/invoker.db \"UPDATE tasks SET status='x")
        self.assertIn(outcome, ("hit", "unchecked"))

    def test_a_detector_exception_allows_the_command_and_says_so(self):
        with patch.object(claude_pretooluse, "pretooluse_outcome", side_effect=RuntimeError("boom")):
            code, err = run_entrypoint({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        self.assertEqual(code, 0)
        self.assertIn("detector error, allowing this command", err)


class Entrypoint(unittest.TestCase):
    def test_a_hit_exits_two_with_the_message_on_stderr(self):
        code, err = run_entrypoint(load_fixture("positive_python_update_routing_columns")["payload"])
        self.assertEqual(code, 2)
        self.assertIn("invoker-db-guard", err)
        self.assertIn("route-task", err)

    def test_a_clean_command_exits_zero_and_prints_nothing(self):
        code, err = run_entrypoint(load_fixture("negative_cli_select_only")["payload"])
        self.assertEqual(code, 0)
        self.assertEqual(err, "")


class Installer(unittest.TestCase):
    def test_the_fragment_wires_bash_pretooluse_to_this_hook(self):
        with open(os.path.join(HOOK_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            fragment = json.load(handle)
        entry = fragment["hooks"]["PreToolUse"][0]
        self.assertEqual(entry["matcher"], "Bash")
        self.assertIn("invoker-db-guard/claude_pretooluse.py", entry["hooks"][0]["command"])

    def test_merging_twice_does_not_duplicate_the_entry(self):
        with open(os.path.join(HOOK_DIR, "claude.hook.json"), encoding="utf-8") as handle:
            fragment = json.load(handle)
        settings, first = install_claude_hook.merge_hook({}, fragment)
        settings, second = install_claude_hook.merge_hook(settings, fragment)
        self.assertTrue(first)
        self.assertFalse(second)
        commands = [h["command"] for e in settings["hooks"]["PreToolUse"] for h in e["hooks"]]
        self.assertEqual(len([c for c in commands if install_claude_hook.MARKER in c]), 1)


if __name__ == "__main__":
    unittest.main()
