#!/usr/bin/env python3
"""Exclusive and universal claims whose only evidence is file:line citations.

A `file:line` read backs only the line it names. A paragraph that says
only/every/each/both/all/none/never or "N of M" and cites nothing but
file:line is flagged, unless the paragraph also carries a fenced block or a
search command. The positives are real replies pasted verbatim.
"""
import os
import sys
import unittest
from unittest import mock

HOOKS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_markers"))
sys.path.insert(0, os.path.join(os.path.dirname(HOOKS_DIR), "_sdk"))
sys.path.insert(0, HOOKS_DIR)

import claude_stop_check  # noqa: E402

RULE = "diu-stop.universal-claim"

REPLY_WORKERS_2243 = ('1. **A tick is just code.** Each tick is a plain function that reads the database and decides what to do, '
 'with no AI involved. Some ticks, like autofix, end by queueing a job, and that job may later start an AI '
 'agent such as Codex (`repro-autofix-recreate-reset.e2e.test.ts:94`).\n'
 '\n'
 '2. **Workers do remember between ticks.** Past decisions are saved in a database table, `worker_actions` '
 "(`sqlite-schema.ts:505`), which survives restarts. The autofix retry count is kept only in the program's "
 'memory (`auto-fix-attempt-ledger.ts:35-36`), so a restart wipes it. That means a "worker" is a repeating '
 'function plus this saved memory. There is no long-running thread.\n'
 '\n'
 '3. **Only one of each kind should run, and a lock file is the only thing enforcing it.** If a second copy '
 'is registered, the registry silently replaces the first (`worker-registry.ts:41`). The real guard is a '
 'lock file for each kind (`headless.ts:706-715`), and nothing tests it.\n'
 '\n'
 'Should I add this to Part A of the page?')

PARA_SHARED_BY_EVERY_PROGRAM_2421 = ('1. **Why a file and not memory:** the desktop app and the command-line tools run as separate programs, so '
 'they can\'t see each other\'s memory. The lock\'s own notes say "an in-process boolean cannot keep them '
 'mutually exclusive" (`worker-lock.ts:4-7`).\n'
 '2. **Why a lock and not just a queue:** the queues already exist. One is shared by every program, and it '
 'lives in the database (`sqlite-schema.ts:406-419`). The lock covers the step before the queue. A tick '
 'checks "already handled?" and only then adds a request. If two programs checked at the same moment, both '
 'would add one.')

PARA_EVERY_WORKER_COPY_3137 = ('**Can SQLite lock a read and a write together?** Yes, and Invoker already has a helper for it '
 "(`sqlite-adapter.ts:1259`). It doesn't help here, though. Every worker copy runs inside the same "
 'background program, the one that writes to the database, so SQLite sees them all as one user.')

SEARCH_FENCE = (
    "```\n"
    "$ git grep -n \"startWorker(\" -- packages | grep -v __tests__\n"
    "packages/execution-engine/src/headless.ts:706\n"
    "packages/execution-engine/src/auto-fix-worker.ts:88\n"
    "```"
)

FILLER = " ".join(["plain"] * (claude_stop_check.WORD_LIMIT + 20))


def findings(message, retry=False):
    event = {"last_assistant_message": message, "stop_hook_active": retry}
    with mock.patch.object(claude_stop_check, "try_check_reply", return_value=""):
        return claude_stop_check.detect(event)


def universal_hits(message, retry=False):
    return [f for f in findings(message, retry) if f.rule_id == RULE]


class RealPositives(unittest.TestCase):
    def test_full_reply_that_said_only_one_of_each_kind_fires(self):
        hits = universal_hits(REPLY_WORKERS_2243)
        self.assertEqual(len(hits), 1)
        self.assertIn("Only one of each kind should run", hits[0].message)

    def test_every_program_paragraph_fires(self):
        hits = universal_hits(PARA_SHARED_BY_EVERY_PROGRAM_2421)
        self.assertEqual(len(hits), 1)
        self.assertIn("One is shared by every program", hits[0].message)

    def test_every_worker_copy_paragraph_fires(self):
        hits = universal_hits(PARA_EVERY_WORKER_COPY_3137)
        self.assertEqual(len(hits), 1)
        self.assertIn("Every worker copy runs inside", hits[0].message)


class BlockMessage(unittest.TestCase):
    def test_message_says_the_line_backs_only_itself_and_names_both_ways_out(self):
        message = findings(PARA_EVERY_WORKER_COPY_3137)[0].message
        self.assertIn("backs only that line", message)
        self.assertIn("paste a search over all of them", message)
        self.assertIn("narrow the claim", message)


class NearNeighboursStaySilent(unittest.TestCase):
    def assertSilent(self, message):
        self.assertEqual(universal_hits(message), [])

    def test_pasted_search_in_a_fence_backs_the_universal(self):
        self.assertSilent(
            "Every worker copy runs inside the same program (`headless.ts:706`).\n"
            + SEARCH_FENCE + "\nThe fence lists every call site."
        )

    def test_search_command_in_prose_backs_the_universal(self):
        self.assertSilent(
            "I ran `git grep -n \"startWorker(\" -- packages` and the only caller is "
            "in `headless.ts:706`."
        )

    def test_rg_run_in_prose_backs_the_universal(self):
        self.assertSilent(
            "Each caller was listed with rg -n startWorker packages and all of them "
            "are in `headless.ts:706` and `auto-fix-worker.ts:88`."
        )

    def test_plain_file_line_claim_without_a_universal_word_stays_silent(self):
        self.assertSilent("The lock is taken at `headless.ts:708` before the worker starts.")

    def test_reported_speech_is_not_a_claim_about_the_code(self):
        self.assertSilent(
            "Last turn I said a lock file is the only guard (`headless.ts:706-715`), "
            "and that was wrong."
        )

    def test_quoted_universal_word_is_not_a_claim(self):
        self.assertSilent(
            'The design doc says "the only guard" is the lock (`headless.ts:706-715`).'
        )

    def test_question_is_not_a_claim(self):
        self.assertSilent("Is every worker registered by `headless.ts:706`?")

    def test_each_other_and_not_only_are_benign(self):
        self.assertSilent(
            "The two workers wait on each other (`headless.ts:706`), and the lock is "
            "not only a file but also a row (`sqlite-schema.ts:406`)."
        )

    def test_only_then_is_benign(self):
        self.assertSilent(
            "The retry runs only then the queue is empty (`auto-fix-worker.ts:88`)."
        )

    def test_universal_claim_with_no_citation_is_not_this_rule(self):
        self.assertSilent("Every worker copy runs inside the same background program.")

    def test_universal_word_inside_inline_code_is_not_a_claim(self):
        self.assertSilent("The flag `--only` is read at `headless.ts:706`.")


class KnownFalsePositiveIteratingLine(unittest.TestCase):
    """A line that itself iterates does back "every", but a citation alone cannot show that."""

    CITED_ONLY = (
        "`surface_keys` treats the first word of every command segment as a "
        "program (`detect.py:300`)."
    )

    def test_citing_the_iterating_line_alone_fires(self):
        self.assertEqual(len(universal_hits(self.CITED_ONLY)), 1)

    def test_pasting_the_iterating_code_in_a_fence_silences_it(self):
        self.assertSilent_for(
            self.CITED_ONLY + "\n```python\nfor seg in segments:\n"
            "    program = seg.split()[0]\n```"
        )

    def assertSilent_for(self, message):
        self.assertEqual(universal_hits(message), [])


class SearchInAnotherParagraphDoesNotBack(unittest.TestCase):
    """Scope is one paragraph, the same unit the citation check reads."""

    def test_search_fence_in_the_previous_paragraph_still_fires(self):
        message = (
            "Search output:\n\n" + SEARCH_FENCE + "\n\n"
            "Every worker copy runs inside the same program (`headless.ts:706`)."
        )
        self.assertEqual(len(universal_hits(message)), 1)


class FixMatrix(unittest.TestCase):
    CASES = [
        {
            "name": "only_one_lock_narrowed",
            "broken": "Only one copy of each worker runs, because of the lock (`headless.ts:706-715`).",
            "fixed": "A lock file guards the worker kind (`headless.ts:706-715`), and a second copy is not guarded.",
        },
        {
            "name": "every_copy_with_search",
            "broken": PARA_EVERY_WORKER_COPY_3137,
            "fixed": PARA_EVERY_WORKER_COPY_3137 + "\n" + SEARCH_FENCE,
        },
        {
            "name": "shared_by_every_program_narrowed",
            "broken": PARA_SHARED_BY_EVERY_PROGRAM_2421,
            "fixed": PARA_SHARED_BY_EVERY_PROGRAM_2421.replace(
                "One is shared by every program, and it lives in the database",
                "One is shared by the desktop app and the CLI, and it lives in the database",
            ).replace("both would add one", "the second would add one too"),
        },
    ]

    def test_broken_fires_and_fixed_is_silent_on_this_rule(self):
        for case in self.CASES:
            with self.subTest(case=case["name"]):
                self.assertEqual(len(universal_hits(case["broken"])), 1)
                self.assertEqual(universal_hits(case["fixed"]), [])


class StopHookActive(unittest.TestCase):
    def test_compliant_rewrite_on_the_retry_passes(self):
        self.assertEqual(
            universal_hits(PARA_EVERY_WORKER_COPY_3137 + "\n" + SEARCH_FENCE, retry=True),
            [],
        )

    def test_retry_with_the_same_broken_paragraph_still_fires_so_the_fix_stays_available(self):
        self.assertEqual(len(universal_hits(PARA_EVERY_WORKER_COPY_3137, retry=True)), 1)


class EveryCheckRuns(unittest.TestCase):
    def test_word_limit_and_universal_claim_both_report(self):
        message = FILLER + "\n\n" + PARA_EVERY_WORKER_COPY_3137
        rules = {f.rule_id for f in findings(message)}
        self.assertIn(RULE, rules)
        self.assertIn("diu-stop.word-limit", rules)


if __name__ == "__main__":
    unittest.main()
