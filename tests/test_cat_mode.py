#!/usr/bin/env python3
"""Structural regression tests for skills/cat-mode/SKILL.md.

cat-mode is prose, not code -- there is no way to mechanically test whether
an agent actually follows it. What IS mechanically testable, and worth
guarding, is the skill *file* staying well-formed: valid frontmatter, the
deliberate disable-model-invocation:true choice not silently flipping,
every skill it references by name still existing, and the file not
re-bloating the way CLAUDE.md's class-search bullet did before it was
split apart (see cat-mode's own "fix doc bloat proactively" bullet).

Run: python3 -m unittest discover -s tests -v
(stdlib unittest + re only, matches tests/test_install.py and
hooks/diu-stop/tests/test_hooks.py -- no PyYAML dependency in this repo.)
"""
import os
import re
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_PATH = os.path.join(REPO_ROOT, "skills", "cat-mode", "SKILL.md")
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

# Calibrated against the file as of this test's authoring (134 lines, 15
# bullets, longest bullet line 76 chars) with headroom for organic growth --
# tight enough to catch the file re-bloating into a CLAUDE.md-style wall of
# text, loose enough not to fail on a normal new bullet.
MAX_TOTAL_LINES = 220
MAX_BULLET_WORDS = 140
ROUTING_REF = os.path.join(REPO_ROOT, "skills", "cat-mode", "references", "execution-routing.md")


def read_skill_text():
    with open(SKILL_PATH, encoding="utf-8") as f:
        return f.read()


def parse_frontmatter(text):
    """Extracts the --- ... --- frontmatter block as a dict of top-level
    `key: value` pairs. Deliberately not a real YAML parser (no PyYAML
    dependency in this repo) -- good enough for this file's flat frontmatter
    shape, matching every other test file's stdlib-only convention."""
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None
    fields = {}
    for line in match.group(1).splitlines():
        field_match = re.match(r"^([a-zA-Z_-]+):\s*(.*)$", line)
        if field_match:
            fields[field_match.group(1)] = field_match.group(2).strip()
    return fields


class TestCatModeFrontmatter(unittest.TestCase):
    def test_file_exists(self):
        self.assertTrue(os.path.isfile(SKILL_PATH), f"missing {SKILL_PATH}")

    def test_frontmatter_parses_and_has_required_fields(self):
        fields = parse_frontmatter(read_skill_text())
        self.assertIsNotNone(fields, "SKILL.md must open with a --- ... --- frontmatter block")
        self.assertIn("name", fields)
        self.assertIn("description", fields)
        self.assertIn("disable-model-invocation", fields)

    def test_name_is_cat_mode(self):
        fields = parse_frontmatter(read_skill_text())
        self.assertEqual(fields["name"], "cat-mode")

    def test_disable_model_invocation_stays_true(self):
        # Deliberate design choice (see the automate-me skill's own step 4):
        # mode skills are heavy and opinionated and must apply only when
        # explicitly invoked. A future edit accidentally dropping or
        # flipping this would make cat-mode auto-trigger on every session.
        fields = parse_frontmatter(read_skill_text())
        self.assertEqual(fields["disable-model-invocation"], "true")

    def test_description_is_a_real_trigger_not_a_placeholder(self):
        # Frontmatter description is what an agent actually reads to decide
        # relevance; a folded multi-line YAML block (`description: >`) needs
        # the frontmatter's raw block, not just the first-line regex match.
        raw_frontmatter = re.match(r"^---\n(.*?)\n---\n", read_skill_text(), re.DOTALL).group(1)
        description_block = re.search(r"description:\s*>?\s*\n((?:  .+\n?)+)", raw_frontmatter)
        self.assertIsNotNone(description_block, "description field must be present")
        description_text = description_block.group(1)
        self.assertGreater(len(description_text.split()), 10, "description reads like a placeholder, not a real trigger")


class TestCatModeReferences(unittest.TestCase):
    def test_every_referenced_skill_still_exists(self):
        text = read_skill_text()
        referenced = set(re.findall(r"`([a-z][a-z0-9-]*)`", text))
        # Backtick tokens that read as skill-name-shaped (lowercase,
        # hyphenated) but aren't actually skill references (e.g. a
        # hypothetical shell flag) would need excluding here; none exist
        # in the file as of this writing -- if one is added, add it to this
        # allowlist rather than weakening the check.
        not_a_skill_reference = set()
        missing = []
        for name in sorted(referenced - not_a_skill_reference):
            if not os.path.isdir(os.path.join(SKILLS_DIR, name)):
                missing.append(name)
        self.assertEqual(missing, [], f"cat-mode references skill(s) that no longer exist: {missing}")


class TestCatModeDoesNotRebloat(unittest.TestCase):
    def test_total_length_stays_bounded(self):
        line_count = len(read_skill_text().splitlines())
        self.assertLessEqual(
            line_count, MAX_TOTAL_LINES,
            f"cat-mode is {line_count} lines (cap {MAX_TOTAL_LINES}) -- cut per "
            "'Fix the tool, not just the instance': restructure or trim before adding more.",
        )

    def test_no_single_bullet_becomes_a_wall_of_text(self):
        text = read_skill_text()
        offenders = []
        for line in text.splitlines():
            if not line.startswith("- "):
                continue
            word_count = len(line.split())
            if word_count > MAX_BULLET_WORDS:
                offenders.append((word_count, line[:80] + "..."))
        self.assertEqual(
            offenders, [],
            f"bullet(s) exceeding {MAX_BULLET_WORDS} words -- this is exactly the "
            "CLAUDE.md class-search-bullet failure mode cat-mode itself warns against: "
            f"{offenders}",
        )


class TestCatModeExecutionRouting(unittest.TestCase):
    def test_routing_reference_exists_and_is_linked(self):
        self.assertTrue(os.path.isfile(ROUTING_REF), f"missing {ROUTING_REF}")
        skill = read_skill_text()
        self.assertIn("references/execution-routing.md", skill)
        self.assertIn("## Execution routing", skill)

    def test_routing_covers_unavailable_small_and_durable_cases(self):
        with open(ROUTING_REF, encoding="utf-8") as handle:
            text = handle.read()
        self.assertIn("Invoker unavailable", text)
        self.assertIn("Small local work", text)
        self.assertIn("Approved plan or durable/parallel work", text)
        self.assertIn("invoker_prepare_plan_review", text)
        self.assertIn("reviewToken", text)
        self.assertIn("One explicit user approval", text)
        self.assertNotIn("sqlite", text.lower())
        self.assertIn("database reads", text.lower())


if __name__ == "__main__":
    unittest.main()
