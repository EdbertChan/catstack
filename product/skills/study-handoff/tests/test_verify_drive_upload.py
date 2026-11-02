from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import verify_drive_upload as verifier  # noqa: E402


def run_verifier(files, listing):
    with tempfile.TemporaryDirectory() as directory:
        for name, content in files.items():
            with open(os.path.join(directory, name), "w") as handle:
                handle.write(content)
        listing_path = os.path.join(directory, "listing.json.tmp")
        with open(listing_path, "w") as handle:
            json.dump(listing, handle)
        local_directory = os.path.join(directory, "study")
        os.mkdir(local_directory)
        for name in files:
            os.replace(os.path.join(directory, name), os.path.join(local_directory, name))
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            exit_code = verifier.main(["--local-directory", local_directory, "--listing", listing_path])
    return exit_code, output.getvalue()


class SizeComparison(unittest.TestCase):
    def test_matching_files_pass(self):
        exit_code, output = run_verifier({"runs.csv": "a,b\n"}, [{"title": "runs.csv", "fileSize": "4"}])
        self.assertEqual(exit_code, 0)
        self.assertIn("runs.csv\t4\t4\tok", output)

    def test_hand_copy_that_is_132_bytes_short_fails_and_names_the_file(self):
        local_content = "x" * 14948
        exit_code, output = run_verifier({"runs.csv": local_content}, [{"title": "runs.csv", "fileSize": "14816"}])
        self.assertEqual(exit_code, 1)
        self.assertIn("runs.csv\t14948\t14816\tsize differs by 132 bytes", output)

    def test_file_missing_in_drive_fails(self):
        exit_code, output = run_verifier({"a.py": "print(1)\n"}, [])
        self.assertEqual(exit_code, 1)
        self.assertIn("a.py\t9\tNone\tmissing in Drive", output)

    def test_file_missing_locally_fails(self):
        exit_code, output = run_verifier({}, [{"title": "old.py", "fileSize": "10"}])
        self.assertEqual(exit_code, 1)
        self.assertIn("old.py\tNone\t10\tmissing locally", output)

    def test_unreadable_listing_exits_two_with_an_error(self):
        errors = io.StringIO()
        with tempfile.TemporaryDirectory() as directory, contextlib.redirect_stderr(errors):
            exit_code = verifier.main(["--local-directory", directory, "--listing", os.path.join(directory, "absent.json")])
        self.assertEqual(exit_code, 2)
        self.assertIn("ERROR could not compare", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
