#!/usr/bin/env python3
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _gate_modules() -> list[tuple[str, object]]:
    modules = []
    for path in sorted(SCRIPTS.glob("check_*.py")):
        name = path.stem
        mod = importlib.import_module(name)
        modules.append((name, mod))
    return modules


class TestEveryGateDeclaresExemplars(unittest.TestCase):
    def test_all_check_scripts_have_gate_exemplars_and_gate_check(self):
        missing = []
        for name, mod in _gate_modules():
            if not hasattr(mod, "GATE_EXEMPLARS"):
                missing.append(f"{name}: missing GATE_EXEMPLARS")
            if not hasattr(mod, "gate_check"):
                missing.append(f"{name}: missing gate_check")
        self.assertEqual(missing, [], "\n".join(missing))


class TestExemplarsMatch(unittest.TestCase):
    pass


def _build_exemplar_tests():
    for name, mod in _gate_modules():
        if not (hasattr(mod, "GATE_EXEMPLARS") and hasattr(mod, "gate_check")):
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
