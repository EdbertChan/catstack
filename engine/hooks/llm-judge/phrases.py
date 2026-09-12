from __future__ import annotations

import json
import os

READS = {"reply", "user", "exchange"}
TEXT_LIMIT = 4000


def _bad(path: str, key: str, detail: str) -> ValueError:
    return ValueError(f"{path}: {key} {detail}")


def _strings(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def load(checker: str, directory: str | None = None) -> dict:
    folder = directory or os.path.join(os.path.dirname(os.path.abspath(__file__)), "phrases")
    path = os.path.join(folder, f"{checker}.json")
    try:
        with open(path, encoding="utf-8") as handle:
            dictionary = json.load(handle)
    except ValueError as exc:
        raise _bad(path, "json", f"is invalid: {exc}") from exc
    except OSError as exc:
        raise _bad(path, "file", f"could not be read: {exc}") from exc
    if not isinstance(dictionary, dict):
        raise _bad(path, "root", f"must be an object, not {type(dictionary).__name__}")
    for key in ("checker", "meaning", "reads", "match", "not_match", "on_hit"):
        if key not in dictionary:
            raise _bad(path, key, "is required")
    stem = os.path.splitext(os.path.basename(path))[0]
    if not isinstance(dictionary["checker"], str) or dictionary["checker"] != stem:
        raise _bad(path, "checker", f"must equal {stem!r}")
    if not isinstance(dictionary["meaning"], str):
        raise _bad(path, "meaning", "must be a string")
    if not isinstance(dictionary["reads"], str) or dictionary["reads"] not in READS:
        raise _bad(path, "reads", "must be one of reply, user, exchange")
    if not _strings(dictionary["match"]) or not dictionary["match"]:
        raise _bad(path, "match", "must be a non-empty array of strings")
    if not _strings(dictionary["not_match"]):
        raise _bad(path, "not_match", "must be an array of strings")
    if not isinstance(dictionary["on_hit"], str):
        raise _bad(path, "on_hit", "must be a string")
    return dictionary


def prompt(dictionary: dict, text: str) -> str:
    clipped = str(text)[-TEXT_LIMIT:]
    expected = '{"match": true|false, "closest": "<phrase or empty>"}'
    return "\n".join(
        [
            f'Return exactly one line of JSON: {expected}',
            f"Meaning: {dictionary['meaning']}",
            f"Match phrases: {json.dumps(dictionary['match'], ensure_ascii=False)}",
            f"Not-match phrases: {json.dumps(dictionary['not_match'], ensure_ascii=False)}",
            "A phrase that is only quoted, negated, or described does not count.",
            "Match when the TEXT means the same thing as the Meaning, in any wording. The phrases are examples of the meaning, not a checklist of exact words.",
            "TEXT:",
            clipped,
        ]
    )


def job(dictionary: dict, transcript: str, text: str) -> dict:
    return {
        "hook": dictionary["checker"],
        "transcript": transcript,
        "prompt": prompt(dictionary, text),
        "hit_if_all_true": ["match"],
        "on_hit": dictionary["on_hit"],
    }
