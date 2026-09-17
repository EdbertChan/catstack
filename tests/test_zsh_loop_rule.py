#!/usr/bin/env python3
"""The learned rule about zsh loops, and the shell behavior it depends on.

zsh does not split an unquoted parameter into words, so a loop over `$LIST`
runs once with the whole list as a single item, exits 0, and reads as "all
done". The premise tests run both shells so the rule fails loudly if that
behavior ever stops being true.
"""
import os
import shutil
import subprocess
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEARNED = os.path.join(REPO_ROOT, "corpus", "CLAUDE.learned.md")
COUNT_LOOP = 'L="a b c"; n=0; for x in $L; do n=$((n+1)); done; echo $n'


def loop_count(shell):
    result = subprocess.run([shell, "-c", COUNT_LOOP], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def working_style_section():
    with open(LEARNED, encoding="utf-8") as handle:
        text = handle.read()
    start = text.index("# Working style")
    end = text.find("\n# ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class TestZshLoopPremise(unittest.TestCase):
    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed on this machine")
    def test_zsh_runs_an_unquoted_list_loop_once(self):
        self.assertEqual(loop_count("zsh"), "1")

    def test_bash_runs_the_same_loop_once_per_word(self):
        self.assertEqual(loop_count("bash"), "3")


class TestZshLoopRule(unittest.TestCase):
    def test_rule_names_the_shell_and_the_fix(self):
        section = working_style_section()
        self.assertIn("zsh", section)
        self.assertIn("`for x in $LIST`", section)
        self.assertIn("bash <<'EOF'", section)

    def test_rule_counts_failed_lookups_as_unchecked(self):
        self.assertIn("count lookups that failed as unchecked", working_style_section())

    def test_rule_cites_the_zsh_option(self):
        self.assertIn("SH_WORD_SPLIT", working_style_section())


if __name__ == "__main__":
    unittest.main()
