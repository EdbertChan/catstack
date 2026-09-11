#!/usr/bin/env python3
"""_claude_utterances must accept any iterable of rows, not only a re-iterable one.

With include_queue_operations=True the function walks rows twice: once to index
the delivered user sends, once to build the utterances. A one-shot iterable is
exhausted by the first walk, so the second yields nothing and the function
returns an empty list with no error -- a silent wrong answer, not a crash.

Found when a caller passed a generator: the frustration replay returned no
messages at all. The failure mode is the reason this is pinned rather than left
to the caller, since every future caller would have to know about the two walks.
"""
from __future__ import annotations

import os
import sys
import unittest

SCRIPTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
import transcript_provenance  # noqa: E402

ROWS = [
    {"type": "user", "message": {"role": "user", "content": "please fix the audio"}},
    {"type": "assistant", "message": {"role": "assistant", "content": "on it"}},
    {"type": "user", "message": {"role": "user", "content": "still broken"}},
]


def utterances(rows, *, queue_ops):
    return transcript_provenance._claude_utterances(
        "/tmp/session.jsonl", rows, include_queue_operations=queue_ops,
    )


class TestAnyIterableOfRows(unittest.TestCase):
    def test_generator_matches_list_with_queue_operations(self):
        """The two-walk path. A generator here used to return nothing."""
        from_list = utterances(list(ROWS), queue_ops=True)
        from_generator = utterances((row for row in ROWS), queue_ops=True)
        self.assertEqual(len(from_list), 2)
        self.assertEqual(
            [u.text for u in from_generator], [u.text for u in from_list],
        )

    def test_generator_matches_list_without_queue_operations(self):
        from_list = utterances(list(ROWS), queue_ops=False)
        from_generator = utterances((row for row in ROWS), queue_ops=False)
        self.assertEqual(
            [u.text for u in from_generator], [u.text for u in from_list],
        )

    def test_indices_are_positions_in_the_original_row_order(self):
        """Materializing must not renumber rows: index 0 and 2, not 0 and 1."""
        found = utterances((row for row in ROWS), queue_ops=True)
        self.assertEqual([u.index for u in found], [0, 2])

    def test_an_exhausted_iterator_yields_nothing_rather_than_raising(self):
        spent = iter([])
        self.assertEqual(utterances(spent, queue_ops=True), [])


if __name__ == "__main__":
    unittest.main()
