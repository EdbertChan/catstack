"""Every playbook step names a real rule id, and a hard step names what checks it."""
from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "runbook" / "check_playbook.py"
RULES_TSV_HEADER = "rule_id\tkind\tbucket\tsource\tmode\twhy_mode\tauto_fire\tsummary\n"
VALID_FRONT_MATTER = """---
runbook: widget-repair
version: 1
applies_to:
  - engine/hooks/alpha-stop/
compiled_from:
  - alpha-stop
  - beta-warn
playbook-trigger: repair the broken widget
enforcement_profile: strict
---

# Repairing a widget
"""
VALID_STEPS = """
## 1. Paste the real payload [alpha-stop · hard · evidence: pasted_payload · @PreToolUse]

Copy the text the detector must catch, not a paraphrase of it.

## 2. Name the neighbours [beta-warn · soft]

List the near misses that must stay silent.
"""


def run(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True)


def write_playbook(root: Path, skill: str, name: str, text: str) -> Path:
    directory = root / "product" / "skills" / skill / "playbooks"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.md"
    path.write_text(text, encoding="utf-8")
    return path


def numbered_steps(count: int) -> str:
    lines = []
    for number in range(1, count + 1):
        lines.append(f"\n## {number}. Step {number} [alpha-stop · soft]\n\nDo the {number}th thing.\n")
    return "".join(lines)


class PlaybookFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        inventory = self.root / "engine" / "runbook" / "rules.tsv"
        inventory.parent.mkdir(parents=True)
        inventory.write_text(
            RULES_TSV_HEADER
            + "alpha-stop\thook\tengine\tengine/hooks/alpha-stop/\tstop\tattention\tevent\tStops alpha.\n"
            + "beta-warn\thook\tengine\tengine/hooks/beta-warn/\twarn\thabit\tevent\tWarns beta.\n",
            encoding="utf-8",
        )
        self.playbook = write_playbook(self.root, "widget-repair", "repair", VALID_FRONT_MATTER + VALID_STEPS)

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def check(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return run("--root", str(self.root), *arguments)

    def test_valid_playbook_passes(self) -> None:
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("clean: 1 playbook(s)", result.stdout)

    def test_valid_playbook_passes_under_all(self) -> None:
        result = self.check("--all")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unknown_rule_id_fails_naming_the_step(self) -> None:
        self.playbook.write_text(
            VALID_FRONT_MATTER + VALID_STEPS.replace("beta-warn · soft", "gamma-off · soft"),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("step 2 names unknown rule id 'gamma-off'", result.stderr)
        self.assertIn("engine/runbook/rules.tsv", result.stderr)

    def test_hard_step_without_evidence_fails(self) -> None:
        self.playbook.write_text(
            VALID_FRONT_MATTER
            + VALID_STEPS.replace(
                "alpha-stop · hard · evidence: pasted_payload · @PreToolUse",
                "alpha-stop · hard · @PreToolUse",
            ),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("step 1 declares hard with no 'evidence: <key>'", result.stderr)

    def test_hard_step_without_event_fails(self) -> None:
        self.playbook.write_text(
            VALID_FRONT_MATTER
            + VALID_STEPS.replace(
                "alpha-stop · hard · evidence: pasted_payload · @PreToolUse",
                "alpha-stop · hard · evidence: pasted_payload",
            ),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("step 1 declares hard with no '@event'", result.stderr)

    def test_soft_step_needs_no_evidence(self) -> None:
        self.assertEqual(self.check(str(self.playbook)).returncode, 0)

    def test_step_with_no_binding_fails(self) -> None:
        self.playbook.write_text(
            VALID_FRONT_MATTER + VALID_STEPS.replace(" [beta-warn · soft]", ""),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("step 2 ('Name the neighbours') carries no", result.stderr)

    def test_duplicate_trigger_fails(self) -> None:
        twin = write_playbook(self.root, "widget-rework", "rework", VALID_FRONT_MATTER + VALID_STEPS)
        result = self.check(str(twin))
        self.assertEqual(result.returncode, 1)
        self.assertIn("'repair the broken widget' is already claimed by", result.stderr)
        self.assertIn("product/skills/widget-repair/playbooks/repair.md", result.stderr)

    def test_ten_steps_fail(self) -> None:
        self.playbook.write_text(VALID_FRONT_MATTER + numbered_steps(10), encoding="utf-8")
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("10 steps; the cap is 9", result.stderr)

    def test_nine_steps_pass(self) -> None:
        self.playbook.write_text(VALID_FRONT_MATTER + numbered_steps(9), encoding="utf-8")
        self.assertEqual(self.check(str(self.playbook)).returncode, 0)

    def test_long_step_body_fails(self) -> None:
        body = "\n".join(f"Line {number} of the body." for number in range(1, 5))
        self.playbook.write_text(
            VALID_FRONT_MATTER
            + f"\n## 1. Only step [alpha-stop · soft]\n\n{body}\n",
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("step 1 has a 4-line body; the cap is 3 lines", result.stderr)

    def test_missing_enforcement_profile_fails(self) -> None:
        self.playbook.write_text(
            (VALID_FRONT_MATTER + VALID_STEPS).replace("enforcement_profile: strict\n", ""),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("front matter is missing enforcement_profile", result.stderr)

    def test_invalid_enforcement_profile_fails(self) -> None:
        self.playbook.write_text(
            (VALID_FRONT_MATTER + VALID_STEPS).replace("enforcement_profile: strict", "enforcement_profile: loud"),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("enforcement_profile 'loud' is not advisory, guided or strict", result.stderr)

    def test_one_word_trigger_fails(self) -> None:
        self.playbook.write_text(
            (VALID_FRONT_MATTER + VALID_STEPS).replace("playbook-trigger: repair the broken widget", "playbook-trigger: repair"),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("playbook-trigger 'repair' is not 2 or more plain words", result.stderr)

    def test_compiled_from_unknown_rule_id_fails(self) -> None:
        self.playbook.write_text(
            (VALID_FRONT_MATTER + VALID_STEPS).replace("  - beta-warn", "  - gamma-off"),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("compiled_from names unknown rule id 'gamma-off'", result.stderr)

    def test_out_of_order_steps_fail(self) -> None:
        self.playbook.write_text(
            VALID_FRONT_MATTER + VALID_STEPS.replace("## 2. Name", "## 3. Name"),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("step 3 is out of order; expected step 2", result.stderr)

    def test_every_breach_is_reported_in_one_run(self) -> None:
        self.playbook.write_text(
            (VALID_FRONT_MATTER + VALID_STEPS)
            .replace("enforcement_profile: strict", "enforcement_profile: loud")
            .replace("beta-warn · soft", "gamma-off · soft"),
            encoding="utf-8",
        )
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 1)
        self.assertIn("enforcement_profile 'loud'", result.stderr)
        self.assertIn("unknown rule id 'gamma-off'", result.stderr)

    def test_unreadable_rule_inventory_is_unchecked_not_clean(self) -> None:
        (self.root / "engine" / "runbook" / "rules.tsv").unlink()
        result = self.check(str(self.playbook))
        self.assertEqual(result.returncode, 2)
        self.assertIn("unchecked:", result.stderr)
        self.assertIn("rule inventory unreadable", result.stderr)

    def test_missing_playbook_is_unchecked_not_clean(self) -> None:
        result = self.check(str(self.root / "product" / "skills" / "widget-repair" / "playbooks" / "absent.md"))
        self.assertEqual(result.returncode, 2)
        self.assertIn("playbook unreadable", result.stderr)

    def test_a_path_and_all_together_are_refused(self) -> None:
        result = self.check(str(self.playbook), "--all")
        self.assertEqual(result.returncode, 2)
        self.assertIn("exactly one playbook path or --all", result.stderr)


if __name__ == "__main__":
    unittest.main()
