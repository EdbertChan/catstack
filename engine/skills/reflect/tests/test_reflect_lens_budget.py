"""Run the lens-budget fixtures from the repository's script-test suite."""

import importlib.util
import os

SOURCE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "scripts",
    "tests",
    "test_reflect_lens_budget.py",
)
spec = importlib.util.spec_from_file_location("reflect_script_lens_budget", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
TestReflectLensBudget = module.TestReflectLensBudget
