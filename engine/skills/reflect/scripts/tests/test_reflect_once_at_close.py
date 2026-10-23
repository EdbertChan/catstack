"""Pin the once-at-close rule in reflect's "When to invoke" section."""
from __future__ import annotations

import unittest
from pathlib import Path

SKILL_MD = Path(__file__).resolve().parents[2] / "SKILL.md"


def _when_to_invoke(text: str) -> str:
    start = text.index("## When to invoke")
    end = text.index("## Process", start)
    return " ".join(text[start:end].split())


class ReflectOnceAtClose(unittest.TestCase):
    def test_when_to_invoke_opens_with_once_at_close(self):
        section = _when_to_invoke(SKILL_MD.read_text(encoding="utf-8"))
        self.assertIn("Reflect runs once, at the close of the work.", section)
        self.assertIn("do not run a pass after each deliverable or each correction", section)
        self.assertIn("they do not each earn a separate pass before the close", section)

    def test_rule_sits_before_the_trigger_list(self):
        section = _when_to_invoke(SKILL_MD.read_text(encoding="utf-8"))
        self.assertLess(section.index("Reflect runs once, at the close of the work."), section.index("reflect-on-thrash"))


if __name__ == "__main__":
    unittest.main()
