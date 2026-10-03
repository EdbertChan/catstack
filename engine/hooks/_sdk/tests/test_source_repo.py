from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import source_repo


class SourceShaTest(unittest.TestCase):
    def test_install_record_names_the_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".catstack-source").write_text("/repo\n" + ("ab" * 20) + "\nmain\n", encoding="utf-8")
            hook = root / "diu-stop" / "detect.py"
            hook.parent.mkdir()
            hook.write_text("#\n", encoding="utf-8")
            self.assertEqual("ab" * 20, source_repo.source_sha(str(hook)))

    def test_checkout_without_a_record_uses_git_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            hook = repo / "engine" / "hooks" / "diu-stop" / "detect.py"
            hook.parent.mkdir(parents=True)
            hook.write_text("#\n", encoding="utf-8")
            (repo / ".git").mkdir()
            with mock.patch("source_repo.subprocess.check_output", return_value="cd" * 20 + "\n") as git:
                self.assertEqual("cd" * 20, source_repo.source_sha(str(hook)))
            git.assert_called_once()

    def test_missing_checkout_stays_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            hook = Path(tmp) / "diu-stop" / "detect.py"
            hook.parent.mkdir()
            hook.write_text("#\n", encoding="utf-8")
            self.assertEqual("", source_repo.source_sha(str(hook)))
