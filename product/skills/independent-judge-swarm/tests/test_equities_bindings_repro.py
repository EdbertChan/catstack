#!/usr/bin/env python3
"""Repro: bindings-driven resolver matches fixture golden and consumer cwd.

Catstack never hardcodes consumer script basenames. Bindings come from:
  .cursor/judge-swarm-bindings.json  (consumer or fixture)

Proves:
1. Fixture cwd + fixture bindings → golden argv (generic skill path).
2. Optional consumer cwd via CONSUMER_REPO_ROOT → same argv as that repo's
   bindings file, and every named script exists (current consumer behavior).
3. Catstack repo cwd (no bindings) → fail closed.
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

FIXTURE_BINDINGS = SKILL_ROOT / "references" / "fixture_bindings.json"
CONSUMER_ROOT = os.environ.get("CONSUMER_REPO_ROOT", "").strip()
BINDINGS_REL = Path(".cursor/judge-swarm-bindings.json")


def _load_fixture() -> dict:
    return json.loads(FIXTURE_BINDINGS.read_text(encoding="utf-8"))


def _install_fixture_tree(root: Path, fixture: dict) -> None:
    bindings_path = root / BINDINGS_REL
    bindings_path.parent.mkdir(parents=True, exist_ok=True)
    # Write commands only (resolver does not need example block).
    bindings_path.write_text(
        json.dumps(
            {
                "schema_version": fixture.get("schema_version", 1),
                "commands": fixture["commands"],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    for spec in fixture["commands"].values():
        rel = Path(spec["relative"])
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# fixture {rel.name}\n", encoding="utf-8")


class TestEquitiesBindingsRepro(unittest.TestCase):
    def test_fixture_bindings_file_is_in_catstack(self):
        self.assertTrue(FIXTURE_BINDINGS.is_file(), FIXTURE_BINDINGS)
        fixture = _load_fixture()
        for spec in fixture["commands"].values():
            rel = Path(spec["relative"])
            # Fixture paths must not escape the fixture tree conceptually.
            self.assertFalse(rel.is_absolute())
            self.assertNotIn("..", rel.parts)

    def test_fixture_cwd_matches_golden_argv(self):
        """New generic resolver vs fixture golden (catstack-owned files only)."""
        fixture = _load_fixture()
        example = fixture["example"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _install_fixture_tree(root, fixture)
            result = reb.resolve(
                root,
                ticker=example["ticker"],
                sheet_url=example["sheet_url"],
                produce=example["produce"],
            )
            self.assertTrue(result["ok"], result["errors"])
            by_name = {c["name"]: c["argv"] for c in result["commands"]}
            self.assertEqual(by_name["produce"], example["produce_argv"])
            self.assertEqual(by_name["grade"], example["grade_argv"])

    def test_consumer_repo_bindings_resume_current_behavior(self):
        """If CONSUMER_REPO_ROOT is set, resolve using that repo's bindings only."""
        if not CONSUMER_ROOT:
            self.skipTest("set CONSUMER_REPO_ROOT to a consumer checkout to run")
        root = Path(CONSUMER_ROOT)
        bindings_path = root / BINDINGS_REL
        self.assertTrue(
            bindings_path.is_file(),
            f"consumer missing {BINDINGS_REL.as_posix()} under {root}",
        )
        bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
        example = bindings.get("example")
        self.assertIsInstance(example, dict, "consumer bindings need an example block for repro")

        # Every relative path named in commands must exist in the consumer.
        for name, spec in bindings["commands"].items():
            path = root / spec["relative"]
            self.assertTrue(path.is_file(), f"consumer missing {name} script {path}")

        result = reb.resolve(
            root,
            ticker=example["ticker"],
            sheet_url=example.get("sheet_url"),
            produce=bool(example.get("produce")),
        )
        self.assertTrue(result["ok"], result["errors"])
        by_name = {c["name"]: c for c in result["commands"]}
        if example.get("produce"):
            self.assertEqual(by_name["produce"]["argv"], example["produce_argv"])
        self.assertEqual(by_name["grade"]["argv"], example["grade_argv"])
        for name, cmd in by_name.items():
            self.assertTrue(Path(cmd["path"]).is_file())
            self.assertEqual(
                Path(cmd["path"]),
                (root / bindings["commands"][name]["relative"]).resolve(),
            )

    def test_catstack_cwd_fails_closed_no_invent(self):
        catstack = SKILL_ROOT.parents[2]
        result = reb.resolve(
            catstack,
            ticker="ACME",
            sheet_url="https://example.invalid/sheet",
            produce=True,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["commands"], [])
        self.assertTrue(
            any("judge-swarm-bindings.json" in e for e in result["errors"]),
            result["errors"],
        )

    def test_produce_without_produce_command_fails_closed(self):
        fixture = _load_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            slim = {
                "schema_version": 1,
                "commands": {"grade": fixture["commands"]["grade"]},
            }
            _install_fixture_tree(root, slim)
            result = reb.resolve(
                root,
                ticker="ACME",
                sheet_url="https://example.invalid/s",
                produce=True,
            )
            self.assertFalse(result["ok"])
            self.assertTrue(any("produce" in e for e in result["errors"]))

    def test_grade_only_without_produce(self):
        fixture = _load_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _install_fixture_tree(root, fixture)
            result = reb.resolve(
                root,
                ticker="acme",
                sheet_url="https://example.invalid/s",
                produce=False,
            )
            self.assertTrue(result["ok"], result["errors"])
            self.assertEqual(len(result["commands"]), 1)
            self.assertEqual(result["commands"][0]["name"], "grade")
            self.assertEqual(result["commands"][0]["argv"][3], "ACME")


if __name__ == "__main__":
    unittest.main()
