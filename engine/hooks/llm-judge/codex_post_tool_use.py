#!/usr/bin/env python3
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
SDK_DIR = os.path.join(os.path.dirname(HERE), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from detect import detect_codex_post_tool_use as detect  # noqa: E402
from runtime import run_hook  # noqa: E402

HARNESS = "Codex PostToolUse"


def _json_error(exc: BaseException) -> str:
    return f"llm-judge: {HARNESS} could not read payload: {type(exc).__name__}: {exc}"


def main() -> None:
    try:
        run_hook("llm-judge", "codex", detect, hook_event_name="PostToolUse", json_error_message=_json_error)
    except SystemExit:
        if __name__ == "__main__":
            raise


if __name__ == "__main__":
    main()
