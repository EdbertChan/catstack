#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

EXEMPLAR_DEBT = frozenset(
    {
        "check_codify_has_code",
        "check_dora_baseline",
        "check_ecosystem_boundaries",
        "check_history_claims",
        "check_hook_test_coverage",
        "check_install_effective",
        "check_mine_repro_coverage",
        "check_no_dated_provenance",
        "check_no_new_comments",
        "check_no_tracked_local_artifacts",
        "check_skill_file_refs",
        "check_skill_test_coverage",
        "check_skill_test_debt_no_growth",
        "check_skill_trigger_mechanism",
        "check_skill_trigger_policy",
        "check_skills_three_harnesses",
        "check_subagent_scope_contract",
    }
)


def _gate_modules() -> list[tuple[str, object]]:
    modules = []
    for path in sorted(SCRIPTS.glob("check_*.py")):
        name = path.stem
        mod = importlib.import_module(name)
        modules.append((name, mod))
    return modules


def _declares_exemplars(mod: object) -> bool:
    return hasattr(mod, "GATE_EXEMPLARS") and hasattr(mod, "gate_check")


class TestEveryGateDeclaresExemplars(unittest.TestCase):
    def test_gates_outside_the_debt_list_have_gate_exemplars_and_gate_check(self):
        missing = []
        for name, mod in _gate_modules():
            if name in EXEMPLAR_DEBT:
                continue
            if not hasattr(mod, "GATE_EXEMPLARS"):
                missing.append(f"{name}: missing GATE_EXEMPLARS")
            if not hasattr(mod, "gate_check"):
                missing.append(f"{name}: missing gate_check")
        self.assertEqual(missing, [], "\n".join(missing))

    def test_debt_list_only_names_gates_that_still_lack_exemplars(self):
        modules = dict(_gate_modules())
        stale = []
        for name in sorted(EXEMPLAR_DEBT):
            if name not in modules:
                stale.append(f"{name}: no such scripts/{name}.py, drop it from EXEMPLAR_DEBT")
            elif _declares_exemplars(modules[name]):
                stale.append(f"{name}: now declares exemplars, drop it from EXEMPLAR_DEBT")
        self.assertEqual(stale, [], "\n".join(stale))

    def test_every_declaring_gate_has_catch_and_allow_exemplars(self):
        empty = []
        for name, mod in _gate_modules():
            if not _declares_exemplars(mod):
                continue
            for kind in ("catch", "allow"):
                if not mod.GATE_EXEMPLARS.get(kind):
                    empty.append(f"{name}: no {kind} exemplars")
        self.assertEqual(empty, [], "\n".join(empty))


class TestExemplarsMatch(unittest.TestCase):
    pass


def _build_exemplar_tests():
    for name, mod in _gate_modules():
        if not _declares_exemplars(mod):
            continue
        exemplars = mod.GATE_EXEMPLARS
        check = mod.gate_check

        for i, ex in enumerate(exemplars.get("catch", [])):

            def make_catch(ex=ex, check=check, name=name, i=i):
                def test(self):
                    self.assertTrue(
                        check(ex),
                        f"{name} catch[{i}] was not caught: {ex!r}",
                    )

                return test

            setattr(
                TestExemplarsMatch,
                f"test_{name}_catch_{i}",
                make_catch(),
            )

        for i, ex in enumerate(exemplars.get("allow", [])):

            def make_allow(ex=ex, check=check, name=name, i=i):
                def test(self):
                    self.assertFalse(
                        check(ex),
                        f"{name} allow[{i}] was incorrectly caught: {ex!r}",
                    )

                return test

            setattr(
                TestExemplarsMatch,
                f"test_{name}_allow_{i}",
                make_allow(),
            )


_build_exemplar_tests()

if __name__ == "__main__":
    unittest.main()
