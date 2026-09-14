#!/usr/bin/env python3
"""A flag lookup has three answers, and the third one is the point.

set-on and set-off are easy. The answer this suite exists for is
could-not-tell: a candidate .env file that is there and cannot be read. The
old reader returned None for that, which every caller then read as "the flag
is not set" -- a check that could not run reporting clean. These tests pin
that such a file lands in `unreadable`, that the walk carries on past it, and
that `unreadable_note` gives the caller something to say.

Run: python3 -m unittest discover -s engine/hooks/_flags/tests -v
"""
from __future__ import annotations

import io
import os
import sys
import tempfile
import unittest

FLAGS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, FLAGS_DIR)

import flags  # noqa: E402

KEY = "CATSTACK_TEST_FLAG"


class Sandbox:
    """A home directory, and a git repo to act as cwd, both throwaway."""

    def __init__(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home")
        self.repo = os.path.join(self.tmp.name, "repo")
        os.makedirs(os.path.join(self.repo, ".git"))
        self.cwd = os.path.join(self.repo, "nested", "deeper")
        os.makedirs(self.cwd)
        os.makedirs(self.home)

    def write(self, path: str, text: str) -> str:
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    @property
    def home_env(self) -> str:
        return os.path.join(self.home, ".catstack.env")

    @property
    def repo_env(self) -> str:
        return os.path.join(self.repo, ".env")

    def environ(self, extra: dict | None = None) -> dict:
        env = {"HOME": self.home}
        env.update(extra or {})
        return env

    def cleanup(self) -> None:
        self.tmp.cleanup()


class FlagsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)

    def resolve(self, environ: dict | None = None, cwd: str | None = None):
        return flags.resolve_flag(
            KEY, self.box.environ(environ), cwd if cwd is not None else self.box.cwd, self.box.home
        )


    def test_nothing_defines_it(self):
        found = self.resolve()
        self.assertEqual((found.value, found.source, found.unreadable), (None, None, ()))
        self.assertFalse(found.on)

    def test_unset_and_explicit_off_are_different_answers(self):
        unset = self.resolve()
        self.box.write(self.box.repo_env, f"{KEY}=0\n")
        off = self.resolve()
        self.assertIsNone(unset.value)
        self.assertEqual(off.value, "0")
        self.assertFalse(unset.on)
        self.assertFalse(off.on)


    def test_true_values(self):
        for value in ("1", "true", "TRUE", "yes", "on", " on "):
            with self.subTest(value=value):
                self.assertTrue(flags.flag_on(KEY, self.box.environ({KEY: value}), self.box.cwd, self.box.home))

    def test_false_values(self):
        for value in ("0", "false", "off", "no", "", "maybe"):
            with self.subTest(value=value):
                self.assertFalse(flags.flag_on(KEY, self.box.environ({KEY: value}), self.box.cwd, self.box.home))


    def test_environment_beats_every_file(self):
        self.box.write(self.box.repo_env, f"{KEY}=1\n")
        self.box.write(self.box.home_env, f"{KEY}=1\n")
        found = self.resolve({KEY: "0"})
        self.assertEqual((found.value, found.source), ("0", "env"))

    def test_named_env_file_beats_repo_and_home(self):
        named = self.box.write(os.path.join(self.box.tmp.name, "named.env"), f"{KEY}=1\n")
        self.box.write(self.box.repo_env, f"{KEY}=0\n")
        self.box.write(self.box.home_env, f"{KEY}=0\n")
        found = self.resolve({flags.ENV_FILE_VAR: named})
        self.assertEqual((found.value, found.source), ("1", named))

    def test_repo_env_beats_home_and_is_found_by_walking_up(self):
        self.box.write(self.box.repo_env, f"{KEY}=1\n")
        self.box.write(self.box.home_env, f"{KEY}=0\n")
        found = self.resolve()
        self.assertEqual((found.value, found.source), ("1", self.box.repo_env))

    def test_home_env_is_the_last_resort(self):
        self.box.write(self.box.home_env, f"{KEY}=1\n")
        found = self.resolve()
        self.assertEqual((found.value, found.source), ("1", self.box.home_env))

    def test_no_cwd_drops_only_the_repo_candidate(self):
        self.box.write(self.box.home_env, f"{KEY}=1\n")
        found = self.resolve(cwd=None)
        self.assertEqual((found.value, found.source), ("1", self.box.home_env))
        self.assertNotIn(self.box.repo_env, flags.env_file_candidates(self.box.environ(), None, self.box.home))


    def test_later_line_wins_and_comments_are_skipped(self):
        self.box.write(self.box.repo_env, f"# {KEY}=1\n{KEY}=0\n\n{KEY}=1\n")
        self.assertEqual(self.resolve().value, "1")

    def test_quotes_and_export_prefix(self):
        self.box.write(self.box.repo_env, f'export {KEY}="1"\n')
        self.assertEqual(self.resolve().value, "1")

    def test_other_keys_are_not_read_back(self):
        self.box.write(self.box.repo_env, f"SECRET=hunter2\n{KEY}=1\n")
        found = self.resolve()
        self.assertEqual(found.value, "1")
        self.assertNotIn("hunter2", repr(found))


    def test_missing_file_is_a_clean_miss_not_an_unreadable(self):
        found = self.resolve()
        self.assertEqual(found.unreadable, ())
        self.assertEqual(found.unreadable_note(KEY), "")

    def test_a_directory_in_place_of_the_file_is_reported_not_swallowed(self):
        os.makedirs(self.box.repo_env)
        found = self.resolve()
        self.assertEqual([path for path, _ in found.unreadable], [self.box.repo_env])
        self.assertFalse(found.on)
        self.assertIn(self.box.repo_env, found.unreadable_note(KEY))
        self.assertIn(KEY, found.unreadable_note(KEY))

    def test_undecodable_file_is_reported_not_swallowed(self):
        with open(self.box.repo_env, "wb") as handle:
            handle.write(b"\xff\xfe\x00\x00" + KEY.encode() + b"=1\n")
        found = self.resolve()
        self.assertEqual([reason for _, reason in found.unreadable], ["UnicodeDecodeError"])
        self.assertFalse(found.on)

    def test_an_unreadable_candidate_does_not_stop_the_walk(self):
        os.makedirs(self.box.repo_env)
        self.box.write(self.box.home_env, f"{KEY}=1\n")
        found = self.resolve()
        self.assertEqual((found.value, found.source), ("1", self.box.home_env))
        self.assertTrue(found.on)
        self.assertEqual([path for path, _ in found.unreadable], [self.box.repo_env])

    def test_read_flag_from_file_raises_rather_than_returning_none(self):
        os.makedirs(self.box.repo_env)
        with self.assertRaises(flags.UnreadableEnvFile) as caught:
            flags.read_flag_from_file(self.box.repo_env, KEY)
        self.assertEqual(caught.exception.path, self.box.repo_env)


    def test_reflect_enforcement_key_and_default(self):
        self.assertEqual(flags.REFLECT_ENFORCEMENT, "CATSTACK_REFLECT_ENFORCEMENT")
        self.assertFalse(flags.reflect_enforcement_on(self.box.environ(), self.box.cwd, self.box.home))

    def test_reflect_enforcement_reads_the_same_sources(self):
        self.box.write(self.box.repo_env, f"{flags.REFLECT_ENFORCEMENT}=1\n")
        self.assertTrue(flags.reflect_enforcement_on(self.box.environ(), self.box.cwd, self.box.home))


class EnforcementGateTest(unittest.TestCase):
    """The one gate the reflect/automate-me hooks call.

    Its job beyond on/off is the third outcome: when a candidate .env file
    cannot be read, the gate says so by name before returning False, so a
    silent hook is never the only evidence the user gets.
    """

    def setUp(self) -> None:
        self.box = Sandbox()
        self.addCleanup(self.box.cleanup)
        self.err = io.StringIO()

    def gate(self, environ: dict | None = None) -> bool:
        return flags.enforcement_gate(
            "test-hook", self.box.cwd, self.box.environ(environ), self.err
        )

    def test_off_and_quiet_when_nothing_is_set(self):
        self.assertFalse(self.gate())
        self.assertEqual(self.err.getvalue(), "")

    def test_on_when_the_environment_says_so(self):
        self.assertTrue(self.gate({flags.REFLECT_ENFORCEMENT: "1"}))
        self.assertEqual(self.err.getvalue(), "")

    def test_an_unreadable_env_file_is_named_not_swallowed(self):
        os.makedirs(self.box.repo_env)
        self.assertFalse(self.gate())
        note = self.err.getvalue()
        self.assertTrue(note.startswith("test-hook: "), note)
        self.assertIn(self.box.repo_env, note)
        self.assertIn(flags.REFLECT_ENFORCEMENT, note)
        self.assertTrue(note.endswith("\n"), repr(note))

    def test_an_unreadable_file_is_still_reported_when_the_flag_is_on(self):
        os.makedirs(self.box.repo_env)
        self.box.write(self.box.home_env, f"{flags.REFLECT_ENFORCEMENT}=1\n")
        self.assertTrue(self.gate())
        self.assertIn(self.box.repo_env, self.err.getvalue())

    def test_no_cwd_is_not_a_failure(self):
        self.assertFalse(
            flags.enforcement_gate("test-hook", None, self.box.environ(), self.err)
        )
        self.assertEqual(self.err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
