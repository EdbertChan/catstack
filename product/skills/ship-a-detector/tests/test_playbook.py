import re
import unittest
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
PLAYBOOK = SKILL_DIR / "playbooks" / "detector-lifecycle.md"
SKILL_MD = SKILL_DIR / "SKILL.md"

ITEM_RE = re.compile(r"^(\d+)\. (.+) — done: (.+) \((#\d+(?:, #\d+)*)\)$")
HEADING_RE = re.compile(r"^## (\d+)\. (.+)$", re.M)
CITED_RE = re.compile(r"^Cited: (#\d+(?:, #\d+)*)\.$", re.M)
TAIL = {
    14: "install.sh",
    15: "tests/test_install.py",
    16: "README.md",
    17: "docs/ecosystem.md",
    18: "owning skill",
}


def _refs(text):
    return set(re.findall(r"#\d+", text))


def _list_block(text):
    section = text.split("## The list", 1)[1]
    match = re.search(r"```text\n(.*?)\n```", section, re.S)
    return match.group(1).splitlines()


def _sections(text):
    body = text.split("## The list", 1)[1]
    heads = list(HEADING_RE.finditer(body))
    out = []
    for i, head in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        out.append((int(head.group(1)), head.group(2), body[head.end():end]))
    return out


class PlaybookListTest(unittest.TestCase):
    def setUp(self):
        self.text = PLAYBOOK.read_text(encoding="utf-8")
        self.items = [ITEM_RE.match(line) for line in _list_block(self.text)]
        self.sections = _sections(self.text)

    def test_every_list_line_is_a_numbered_item_with_a_done_test_and_citations(self):
        for line, match in zip(_list_block(self.text), self.items):
            self.assertIsNotNone(match, line)

    def test_list_and_sections_are_numbered_one_to_n_in_order(self):
        n = len(self.items)
        self.assertEqual([int(m.group(1)) for m in self.items], list(range(1, n + 1)))
        self.assertEqual([s[0] for s in self.sections], list(range(1, n + 1)))

    def test_each_list_item_carries_its_section_heading_verbatim(self):
        for match, (_, heading, _) in zip(self.items, self.sections):
            self.assertEqual(match.group(2), heading)

    def test_each_list_item_cites_exactly_its_sections_prs(self):
        for match, (number, _, body) in zip(self.items, self.sections):
            cited = CITED_RE.search(body)
            self.assertIsNotNone(cited, f"step {number} has no Cited line")
            self.assertEqual(_refs(match.group(4)), _refs(cited.group(1)), f"step {number}")

    def test_tail_steps_hold_the_wiring_and_the_last_step_calls_make_pr(self):
        titles = {int(m.group(1)): m.group(2) for m in self.items}
        for number, token in TAIL.items():
            self.assertIn(token, titles[number])
        self.assertEqual(titles[len(titles)], "Call `make-pr`")

    def test_skip_with_a_reason_is_the_stated_rule_for_a_step_that_does_not_apply(self):
        how_to = self.text.split("## The list", 1)[0]
        self.assertIn("`skip: <reason>`", how_to)
        self.assertIn("Do not delete it.", how_to)

    def test_skill_md_step_count_matches_the_list(self):
        self.assertIn(f"{len(self.items)}-line block", SKILL_MD.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
