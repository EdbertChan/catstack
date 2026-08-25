#!/usr/bin/env python3
"""Repro: generic equities resolver matches pre-generic holdings-sheet skill.

Proves:
1. Fixture cwd shaped like hidden_stock → same export/grade argv as the
   frozen legacy contract (current behavior captured as golden).
2. Real hidden_stock checkout (if present) → same argv + real files exist.
3. Catstack / empty cwd → fail closed (no invent).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_equities_bindings as reb  # noqa: E402

CONTRACT_PATH = SKILL_ROOT / "references" / "hidden_stock_legacy_contract.json"
HIDDEN_STOCK = Path(os.environ.get("HIDDEN_STOCK_ROOT", "/Users/edbertchan/hidden_stock"))


def _load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _write_consumer_tree(root: Path, *, with_export: bool = True, with_grade: bool = True) -> None:
    if with_export:
        path = root / "scripts" / "export_equity_holdings_sheets.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture export\n", encoding="utf-8")
    if with_grade:
        path = root / "scripts" / "grade_holdings_sheet.py"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# fixture grade\n", encoding="utf-8")
    schema = (
        root
        / ".cursor"
        / "skills"
        / "holdings-sheet-swarm-grade"
        / "grade_schema.json"
    )
    schema.parent.mkdir(parents=True, exist_ok=True)
    schema.write_text("{}\n", encoding="utf-8")


class TestEquitiesBindingsRepro(unittest.TestCase):
    def test_legacy_contract_file_exists(self):
        self.assertTrue(CONTRACT_PATH.is_file(), CONTRACT_PATH)
        contract = _load_contract()
        self.assertEqual(
            contract["consumer_relative_paths"]["export"],
            "scripts/export_equity_holdings_sheets.py",
        )
        self.assertEqual(
            contract["consumer_relative_paths"]["grade"],
            "scripts/grade_holdings_sheet.py",
        )

    def test_fixture_matches_legacy_contract_current_behavior(self):
        """New generic resolver vs frozen current-version argv (golden)."""
        contract = _load_contract()
        example = contract["example"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_consumer_tree(root)
            result = reb.resolve(
                root,
                ticker=example["ticker"],
                sheet_url=example["sheet_url"],
                produce=example["produce"],
            )
            self.assertTrue(result["ok"], result["errors"])
            by_name = {c["name"]: c["argv"] for c in result["commands"]}
            self.assertEqual(by_name["export"], example["export_argv"])
            self.assertEqual(by_name["grade"], example["grade_argv"])
            self.assertTrue(result["export_exists"])
            self.assertTrue(result["grade_exists"])
            self.assertTrue(result["schema_exists"])

    def test_real_hidden_stock_matches_legacy_and_files_exist(self):
        """Running from the real hidden_stock repo resumes the same commands."""
        if not HIDDEN_STOCK.is_dir():
            self.skipTest(f"hidden_stock not at {HIDDEN_STOCK}")
        contract = _load_contract()
        example = contract["example"]
        export = HIDDEN_STOCK / contract["consumer_relative_paths"]["export"]
        grade = HIDDEN_STOCK / contract["consumer_relative_paths"]["grade"]
        schema = HIDDEN_STOCK / contract["consumer_relative_paths"]["schema"]
        self.assertTrue(export.is_file(), f"missing current-version script {export}")
        self.assertTrue(grade.is_file(), f"missing current-version script {grade}")
        self.assertTrue(schema.is_file(), f"missing current-version schema {schema}")

        result = reb.resolve(
            HIDDEN_STOCK,
            ticker=example["ticker"],
            sheet_url=example["sheet_url"],
            produce=True,
        )
        self.assertTrue(result["ok"], result["errors"])
        by_name = {c["name"]: c for c in result["commands"]}
        self.assertEqual(by_name["export"]["argv"], example["export_argv"])
        self.assertEqual(by_name["grade"]["argv"], example["grade_argv"])
        self.assertEqual(Path(by_name["export"]["path"]), export.resolve())
        self.assertEqual(Path(by_name["grade"]["path"]), grade.resolve())

    def test_catstack_cwd_fails_closed_no_invent(self):
        """Generic skill cwd (no consumer scripts) must not invent CLIs."""
        catstack = SKILL_ROOT.parents[2]  # product/skills/<name> → repo root
        result = reb.resolve(
            catstack,
            ticker="UBER",
            sheet_url="https://example.invalid/sheet",
            produce=True,
        )
        self.assertFalse(result["ok"])
        self.assertFalse(result["export_exists"])
        self.assertFalse(result["grade_exists"])
        joined = " ".join(result["errors"])
        self.assertIn("export_equity_holdings_sheets.py", joined)
        self.assertIn("grade_holdings_sheet.py", joined)
        self.assertEqual(result["commands"], [])

    def test_produce_without_export_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_consumer_tree(root, with_export=False, with_grade=True)
            result = reb.resolve(root, ticker="UBER", produce=True)
            self.assertFalse(result["ok"])
            self.assertTrue(any("export_equity" in e for e in result["errors"]))

    def test_grade_only_without_produce(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_consumer_tree(root, with_export=False, with_grade=True)
            result = reb.resolve(
                root,
                ticker="baba",
                sheet_url="https://example.invalid/s",
                produce=False,
            )
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(len(result["commands"]), 1)
            self.assertEqual(result["commands"][0]["name"], "grade")
            self.assertEqual(result["commands"][0]["argv"][3], "BABA")


if __name__ == "__main__":
    unittest.main()
