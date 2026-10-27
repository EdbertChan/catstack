"""Every hook and skill gets one row; people's review columns survive a rerun."""
from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "runbook" / "inventory_rules.py"


def run(*args: str, working_directory: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=working_directory, capture_output=True, text=True)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def make_fixture(root: Path) -> None:
    hooks = root / "engine" / "hooks"
    hooks.mkdir(parents=True)
    (hooks / "hooks.toml").write_text(
        '[hooks.alpha-stop]\nmode = "stop"\nwhy_mode = "attention"\nsummary = "Stops alpha."\n\n'
        '[hooks.beta-warn]\nmode = "warn"\nwhy_mode = "habit"\nsummary = "Warns beta."\n',
        encoding="utf-8",
    )
    auto = root / "product" / "skills" / "auto-skill"
    auto.mkdir(parents=True)
    (auto / "SKILL.md").write_text(
        "---\nname: auto-skill\ndescription: >-\n  Fires on its own.\n  Second line kept.\n---\n# body\n",
        encoding="utf-8",
    )
    explicit = root / "corpus" / "skills" / "typed-skill"
    explicit.mkdir(parents=True)
    (explicit / "SKILL.md").write_text(
        '---\nname: typed-skill\ndescription: "Only when typed."\ndisable-model-invocation: true\n---\n',
        encoding="utf-8",
    )
    (root / "engine" / "skills").mkdir()


class InventoryFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        make_fixture(self.root)
        self.inventory = self.root / "engine" / "runbook" / "rules.tsv"

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_one_row_per_hook_and_skill(self) -> None:
        result = run("--root", str(self.root), working_directory=self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        rows = read_rows(self.inventory)
        self.assertEqual([row["rule_id"] for row in rows], ["alpha-stop", "beta-warn", "typed-skill", "auto-skill"])
        rows_by_id = {row["rule_id"]: row for row in rows}
        self.assertEqual(rows_by_id["alpha-stop"]["mode"], "stop")
        self.assertEqual(rows_by_id["auto-skill"]["auto_fire"], "yes")
        self.assertEqual(rows_by_id["auto-skill"]["summary"], "Fires on its own. Second line kept.")
        self.assertEqual(rows_by_id["typed-skill"]["auto_fire"], "no")
        self.assertEqual(rows_by_id["typed-skill"]["summary"], "Only when typed.")
        self.assertEqual(rows_by_id["typed-skill"]["bucket"], "corpus")

    def test_review_columns_survive_a_rerun(self) -> None:
        run("--root", str(self.root), working_directory=self.root)
        text = self.inventory.read_text(encoding="utf-8").replace(
            "beta-warn\thook\tengine\tengine/hooks/beta-warn/\twarn\thabit\tevent\tWarns beta.\t\t\t\t",
            "beta-warn\thook\tengine\tengine/hooks/beta-warn/\twarn\thabit\tevent\tWarns beta.\tsoft\tcheap\tlow\tlow",
        )
        self.inventory.write_text(text, encoding="utf-8")
        run("--root", str(self.root), working_directory=self.root)
        rows_by_id = {row["rule_id"]: row for row in read_rows(self.inventory)}
        self.assertEqual(rows_by_id["beta-warn"]["proposed_level"], "soft")
        self.assertEqual(rows_by_id["beta-warn"]["fp_cost"], "low")
        self.assertEqual(rows_by_id["alpha-stop"]["proposed_level"], "")

    def test_check_fails_when_a_hook_is_missing_a_row(self) -> None:
        run("--root", str(self.root), working_directory=self.root)
        self.assertEqual(run("--root", str(self.root), "--check", working_directory=self.root).returncode, 0)
        config = self.root / "engine" / "hooks" / "hooks.toml"
        config.write_text(config.read_text(encoding="utf-8") + '\n[hooks.gamma-off]\nmode = "off"\nwhy_mode = "habit"\nsummary = "Records gamma."\n', encoding="utf-8")
        result = run("--root", str(self.root), "--check", working_directory=self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("stale", result.stderr)

    def test_skill_without_front_matter_is_refused_by_name(self) -> None:
        bare = self.root / "product" / "skills" / "bare-skill"
        bare.mkdir()
        (bare / "SKILL.md").write_text("# no front matter\n", encoding="utf-8")
        result = run("--root", str(self.root), working_directory=self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("bare-skill/SKILL.md: no front matter", result.stderr)


class InventoryIsFresh(unittest.TestCase):
    def test_committed_inventory_matches_the_repo(self) -> None:
        result = run("--root", str(REPO), "--check", working_directory=REPO)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)


if __name__ == "__main__":
    unittest.main()
