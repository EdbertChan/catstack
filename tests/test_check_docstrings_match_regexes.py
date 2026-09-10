#!/usr/bin/env python3
"""Every scripts/check_*.py gate keeps the promises its own docstring makes.

A gate's docstring names the class it rejects; its patterns implement a
narrower proxy. Nothing ties the two together unless the gate says, next to
its patterns, which strings the docstring promises to catch and which it
promises to allow. Each gate declares:

  PROMISED_CATCH   exemplars the docstring says the gate rejects
  PROMISED_ALLOW   exemplars the docstring says the gate leaves alone
  flags_exemplar   exemplar string -> True when the gate would reject it

Every promised catch must be flagged and every promised allow must not be.
A gate without the declaration fails here, so a new gate cannot land
without stating what its docstring commits it to.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
GATES = sorted(SCRIPTS.glob("check_*.py"))


def _load(path: Path) -> ModuleType:
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(f"gate_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GatesDeclareTheirPromises(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gates = {path.stem: _load(path) for path in GATES}

    def test_gate_glob_is_not_empty(self) -> None:
        self.assertTrue(GATES, f"no scripts/check_*.py under {SCRIPTS}; nothing was checked")

    def test_every_gate_declares_promises(self) -> None:
        for name, module in self.gates.items():
            with self.subTest(gate=name):
                catch = getattr(module, "PROMISED_CATCH", None)
                allow = getattr(module, "PROMISED_ALLOW", None)
                flags = getattr(module, "flags_exemplar", None)
                self.assertIsInstance(catch, tuple, f"{name}: PROMISED_CATCH tuple missing")
                self.assertIsInstance(allow, tuple, f"{name}: PROMISED_ALLOW tuple missing")
                self.assertTrue(catch, f"{name}: PROMISED_CATCH is empty")
                self.assertTrue(allow, f"{name}: PROMISED_ALLOW is empty")
                self.assertTrue(all(isinstance(e, str) for e in catch + allow), f"{name}: exemplars must be strings")
                self.assertTrue(callable(flags), f"{name}: flags_exemplar(exemplar) -> bool missing")

    def _verdicts(self, which: str):
        for name, module in self.gates.items():
            flags = getattr(module, "flags_exemplar", None)
            if not callable(flags):
                continue
            for exemplar in getattr(module, which, ()):
                yield name, exemplar, flags(exemplar)

    def test_promised_catches_are_flagged(self) -> None:
        for name, exemplar, verdict in self._verdicts("PROMISED_CATCH"):
            with self.subTest(gate=name, exemplar=exemplar):
                self.assertIs(verdict, True, f"{name} promises to catch this but lets it through")

    def test_promised_allows_are_not_flagged(self) -> None:
        for name, exemplar, verdict in self._verdicts("PROMISED_ALLOW"):
            with self.subTest(gate=name, exemplar=exemplar):
                self.assertIs(verdict, False, f"{name} promises to allow this but flags it")


if __name__ == "__main__":
    unittest.main()
