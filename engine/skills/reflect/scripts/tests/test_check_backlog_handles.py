from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(SCRIPTS, "check_backlog_handles.py")


def run_summary(text: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        input=textwrap.dedent(text).lstrip(),
        capture_output=True,
        text=True,
    )


class TestBacklogHandleCheck(unittest.TestCase):
    def test_backlog_item_without_handle_fails_and_names_item(self):
        res = run_summary(
            """
            ## Accepted
            - What happened: one covered thing.

            ## Backlog
            - Build a land-stack no-op fix so queueing an empty stack exits cleanly.

            ## Rejected
            - Not relevant.
            """
        )
        self.assertEqual(res.returncode, 1)
        self.assertIn("land-stack no-op fix", res.stdout)

    def test_backlog_item_with_invoker_workflow_id_passes(self):
        res = run_summary(
            """
            ## Backlog
            - Build a land-stack no-op fix. Invoker workflow wf-1789281139235-17 owns it.
            """
        )
        self.assertEqual(res.returncode, 0)

    def test_summary_with_only_accepted_items_passes(self):
        res = run_summary(
            """
            ## Accepted
            - What happened: the session skipped proof.
              Fix: tighten the verifier.
              Catch: test_check_verifier.py fired.
            """
        )
        self.assertEqual(res.returncode, 0)

    def test_route_and_rejected_items_without_handles_pass(self):
        res = run_summary(
            """
            ## Route-to-automate-me
            - Preserve the user's preferred review order.

            ## Rejected
            - One-off timeout in a closed environment.
            """
        )
        self.assertEqual(res.returncode, 0)

    def test_unparseable_input_exits_unchecked(self):
        res = run_summary("not a reflect summary at all\n")
        self.assertEqual(res.returncode, 2)
        self.assertIn("unchecked", res.stdout)

    def test_declined_by_user_is_an_explicit_handle(self):
        res = run_summary(
            """
            ## Backlog
            - Build a worker for optional cleanup, declined by user.
            """
        )
        self.assertEqual(res.returncode, 0)

    def test_file_argument_is_supported(self):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as handle:
            handle.write("## Backlog\n- Fix the checker in PR #541.\n")
            handle.flush()
            res = subprocess.run(
                [sys.executable, SCRIPT, handle.name],
                capture_output=True,
                text=True,
            )
        self.assertEqual(res.returncode, 0)


if __name__ == "__main__":
    unittest.main()
