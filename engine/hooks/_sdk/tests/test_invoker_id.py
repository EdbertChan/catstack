from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SDK_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SDK_DIR))

import invoker_id


class InvokerIdTest(unittest.TestCase):
    def setUp(self) -> None:
        invoker_id._INVOKER_VERSION = None
        invoker_id._INVOKER_SHA = None

    def tearDown(self) -> None:
        invoker_id._INVOKER_VERSION = None
        invoker_id._INVOKER_SHA = None

    def test_version_comes_from_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli = Path(tmp) / "invoker-cli"
            cli.write_text("#!/bin/sh\necho 9.9.9\n", encoding="utf-8")
            cli.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": tmp}, clear=False):
                self.assertEqual("9.9.9", invoker_id.invoker_version())

    def test_missing_cli_leaves_version_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"PATH": tmp}, clear=False):
            self.assertEqual("", invoker_id.invoker_version())
            self.assertEqual("", invoker_id.invoker_sha())

    def test_source_checkout_records_the_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "Invoker"
            bin_dir = root / "packages" / "cli" / "bin"
            bin_dir.mkdir(parents=True)
            (root / "pnpm-workspace.yaml").write_text("packages: []\n", encoding="utf-8")
            (root / ".git").mkdir()
            cli = bin_dir / "invoker-cli"
            cli.write_text("#!/bin/sh\necho 0.2.1\n", encoding="utf-8")
            cli.chmod(0o755)
            real = invoker_id.subprocess.check_output

            def choose(cmd, *args, **kwargs):
                if isinstance(cmd, list) and cmd and cmd[0] == "git":
                    return "abcd" * 10 + "\n"
                return real(cmd, *args, **kwargs)

            with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}, clear=False), mock.patch(
                "invoker_id.subprocess.check_output",
                side_effect=choose,
            ):
                self.assertEqual("0.2.1", invoker_id.invoker_version())
                self.assertEqual("abcd" * 10, invoker_id.invoker_sha())

    def test_packaged_binary_leaves_commit_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cli_dir = Path(tmp) / "cli" / "invoker-cli-0.2.1-darwin-arm64"
            cli_dir.mkdir(parents=True)
            cli = cli_dir / "invoker-cli"
            cli.write_text("#!/bin/sh\necho 0.2.1\n", encoding="utf-8")
            cli.chmod(0o755)
            with mock.patch.dict(os.environ, {"PATH": str(cli_dir)}, clear=False):
                self.assertEqual("0.2.1", invoker_id.invoker_version())
                self.assertEqual("", invoker_id.invoker_sha())
