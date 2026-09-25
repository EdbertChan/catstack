"""A stand-in llm-judge runner for token_audit tests, plugged in through the
judge's own CATSTACK_LLM_JUDGE_RUNNERS override."""
import contextlib
import json
import os
import sys
import tempfile

RUNNER = r'''
import json, os, sys
prompt = sys.argv[1]
marker = "\nTEXT:\n"
text = prompt.split(marker, 1)[1] if marker in prompt else ""
with open(os.environ["FAKE_JUDGE_LOG"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps(text) + "\n")
if os.environ.get("FAKE_JUDGE_FAIL") == "1":
    sys.exit(1)
needles = json.loads(os.environ.get("FAKE_JUDGE_MATCH") or "[]")
print(json.dumps({"match": any(needle in text for needle in needles)}))
'''


@contextlib.contextmanager
def fake_judge(match=(), fail=False):
    with tempfile.TemporaryDirectory() as root:
        script = os.path.join(root, "runner.py")
        with open(script, "w", encoding="utf-8") as handle:
            handle.write(RUNNER)
        log = os.path.join(root, "judged.jsonl")
        open(log, "w", encoding="utf-8").close()
        env = {
            "CATSTACK_LLM_JUDGE_RUNNERS": json.dumps([["fake", [sys.executable, script, "{prompt}"]]]),
            "CATSTACK_LLM_JUDGE_STATE_DIR": os.path.join(root, "state"),
            "FAKE_JUDGE_LOG": log,
            "FAKE_JUDGE_MATCH": json.dumps(list(match)),
            "FAKE_JUDGE_FAIL": "1" if fail else "0",
        }
        saved = {key: os.environ.get(key) for key in env}
        os.environ.update(env)

        def judged_texts():
            with open(log, encoding="utf-8") as handle:
                return [json.loads(line) for line in handle if line.strip()]

        try:
            yield judged_texts
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
