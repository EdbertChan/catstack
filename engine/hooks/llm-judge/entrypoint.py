from __future__ import annotations

import importlib.util
import os
import sys

SDK_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_sdk")
if SDK_DIR not in sys.path:
    sys.path.insert(0, SDK_DIR)

from runtime import run_hook  # noqa: E402


def run(harness: str, hook_event_name: str, json_error_stderr_prefix: str) -> None:
    try:
        run_hook(
            "llm-judge",
            harness,
            _detect(),
            hook_event_name,
            json_error_stderr_prefix=json_error_stderr_prefix,
        )
    except SystemExit as exc:
        if exc.code not in (0, None):
            raise


def _detect():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sdk_detect.py")
    spec = importlib.util.spec_from_file_location("_catstack_llm_judge_detect", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load llm-judge detector from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.detect
