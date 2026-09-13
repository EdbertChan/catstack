from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "check_no_silent_hook_except.py"


def write_hook(root: Path, name: str, source: str) -> Path:
    path = root / "engine" / "hooks" / name / "hook.py"
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    return path


def run_check(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class TestNoSilentHookExcept(unittest.TestCase):
    def test_silent_broad_handler_fails_with_file_and_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_hook(
                root,
                "demo",
                "def main():\n    try:\n        run()\n    except Exception:\n        return\n",
            )
            result = run_check(root)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"{path}:4: silent broad exception handler", result.stdout)
        self.assertIn("checked 1 file(s)", result.stdout)

    def test_inserted_stderr_print_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hook(
                root,
                "demo",
                "import sys\n\ndef main():\n    try:\n        run()\n    except Exception as exc:\n        print(f\"catstack-hook-error demo: {type(exc).__name__}: {exc}\", file=sys.stderr)\n        return\n",
            )
            result = run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("checked 1 file(s)", result.stdout)

    def test_narrow_handler_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_hook(
                root,
                "demo",
                "def main():\n    try:\n        run()\n    except OSError:\n        return\n",
            )
            result = run_check(root)
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_syntax_error_is_unchecked_and_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = write_hook(root, "demo", "def main(:\n    pass\n")
            result = run_check(root)
        self.assertEqual(result.returncode, 2, result.stdout)
        self.assertIn(f"unchecked: {path}:", result.stdout)
        self.assertIn("checked 1 file(s)", result.stdout)

    def test_fix_rewrites_silent_handler_and_preserves_other_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_hook(
                root,
                "demo",
                "from __future__ import annotations\n\nVALUE = 3\n\ndef main():\n    before()\n    try:\n        run()\n    except Exception:\n        return\n    after()\n",
            )
            before = path.read_text(encoding="utf-8").splitlines()
            fixed = run_check(root, "--fix")
            after_fix = run_check(root)
            after = path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(fixed.returncode, 0, fixed.stdout)
        self.assertEqual(after_fix.returncode, 0, after_fix.stdout)
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[2], after[3])
        self.assertEqual(before[4], after[5])
        self.assertEqual(before[10], after[12])
        self.assertIn("import sys", after)
        self.assertIn("    except Exception as exc:", after)
        self.assertIn(
            '        print(f"catstack-hook-error demo: {type(exc).__name__}: {exc}", file=sys.stderr)',
            after,
        )


if __name__ == "__main__":
    unittest.main()
