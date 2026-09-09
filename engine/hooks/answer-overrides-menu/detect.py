"""answer-overrides-menu: catch a free-text answer to a multiple-choice question.

`AskUserQuestion` offers a menu and the harness appends an "Other" escape
hatch. When the user types instead of picking, every option offered was
wrong -- that answer is the single most binding thing said in the turn, and
it is also the least durable: a typed message persists as a `user` turn,
while an `AskUserQuestion` answer lands in a `tool_result` blob shaped like
any `Bash` output. The plan is then built from the menu the agent wrote
rather than the answer the user gave.

The check is a string comparison against the tool's own payload: an answer
is a menu pick only when it is verbatim one of the labels offered for that
same question. Anything else is an override. `AskUserQuestionOutput`'s
`answers` map is keyed by question text, so each answer is compared only
against its own question's labels. Multi-select answers are comma-joined
(sdk-tools.d.ts, `answers`: "multi-select answers are comma-separated"), so
a multi-select answer also counts as a pick when every comma-separated part
is a label of that question. `response` is the harness's own field for
"freeform text the user typed instead of selecting a structured option";
non-empty is an override by definition.

No regex over prose, no keyword list, no sentiment. Inject-only, never
blocks, fail-open on any malformed payload.

Fixtures: tests/fixtures/real_free_text_override.json is the verbatim
payload of the session where the user answered "0DTE and futures. futures
need to be checked" and a five-year SPY equities pipeline was built anyway;
tests/fixtures/real_menu_pick.json is a verbatim payload where the user
picked an offered label.
"""
from __future__ import annotations

TOOL_NAME = "AskUserQuestion"


def _as_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _question_menus(payload: dict) -> dict[str, tuple[frozenset[str], bool]]:
    menus: dict[str, tuple[frozenset[str], bool]] = {}
    for source in (payload.get("tool_input"), payload.get("tool_response")):
        for question in _as_dict(source).get("questions") or []:
            if not isinstance(question, dict):
                continue
            text = question.get("question")
            if not isinstance(text, str) or not text:
                continue
            labels = {
                option["label"]
                for option in question.get("options") or []
                if isinstance(option, dict) and isinstance(option.get("label"), str)
            }
            if not labels:
                continue
            menus[text] = (frozenset(labels), bool(question.get("multiSelect")))
    return menus


def _is_menu_pick(answer: str, labels: frozenset[str], multi_select: bool) -> bool:
    if answer.strip() in labels:
        return True
    if not multi_select:
        return False
    parts = [part.strip() for part in answer.split(",")]
    return bool(parts) and all(part in labels for part in parts)


def overrides(payload: dict) -> list[tuple[str, str]]:
    """Return (question, answer) pairs whose answer matched no offered label."""
    if str(payload.get("tool_name") or "") != TOOL_NAME:
        return []
    response = _as_dict(payload.get("tool_response"))
    menus = _question_menus(payload)
    found: list[tuple[str, str]] = []
    for question, answer in (_as_dict(response.get("answers"))).items():
        if not isinstance(question, str) or not isinstance(answer, str):
            continue
        menu = menus.get(question)
        if menu is None:
            continue
        if not _is_menu_pick(answer, menu[0], menu[1]):
            found.append((question, answer))
    freeform = response.get("response")
    if isinstance(freeform, str) and freeform.strip():
        found.append(("", freeform))
    return found


def reminder_text(found: list[tuple[str, str]]) -> str:
    quoted = "\n".join(f'  {question}\n  -> "{answer}"' for question, answer in found)
    return (
        "answer-overrides-menu: the user answered outside the options offered, so every "
        "option offered was wrong. A free-text answer supersedes the menu and binds exactly "
        "as hard as a typed message. Restate it verbatim as a binding parameter of the plan "
        "before any work starts, and re-read it before each phase; do not substitute the "
        "nearest option you did offer.\n" + quoted
    )


def decide(payload: dict) -> str | None:
    found = overrides(payload)
    if not found:
        return None
    return reminder_text(found)
