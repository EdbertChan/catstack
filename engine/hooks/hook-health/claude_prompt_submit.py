from __future__ import annotations

from functools import partial
import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from detect import detect  # noqa: E402
from runtime import run_hook  # noqa: E402


def main() -> int:
    try:
        run_hook(
            "hook-health",
            "claude",
            partial(detect, harness="claude"),
            "UserPromptSubmit",
        )
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
