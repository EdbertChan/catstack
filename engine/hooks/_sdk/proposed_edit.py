"""Apply a proposed Edit, Write or MultiEdit to a file in memory and name the lines it changes."""
from __future__ import annotations

import difflib
from pathlib import Path

from finding import Finding

MAX_FILE_BYTES = 2_000_000
EDIT_TOOLS = ("Edit", "Write", "MultiEdit")


class ProposedEdit:
    """One file edit a tool is about to make, applied before the tool runs.

    Carries the tool name and input, the target path, whether that path exists yet,
    the text before and after the edit, the 1-based line numbers the edit touches in the result,
    and the reason the edit could not be applied when there is one.
    """

    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self.tool_name = tool_name
        self.tool_input = tool_input
        self.path = str(tool_input.get("file_path") or tool_input.get("path") or "")
        self.exists = Path(self.path).exists() if self.path else False
        self.before: str | None = None
        self.after: str | None = None
        self.edited_lines: set[int] = set()
        self.unchecked_reason: str | None = None

    @classmethod
    def from_event(cls, event: dict[str, object]) -> ProposedEdit | None:
        tool_input = event.get("tool_input") or {}
        tool_name = str(event.get("tool_name") or "")
        if not isinstance(tool_input, dict) or tool_name not in EDIT_TOOLS:
            return None
        return cls(tool_name, tool_input)

    def creates_file(self) -> bool:
        return self.tool_name == "Write" and not self.exists

    def apply(self) -> bool:
        self.before = self.read_current()
        if self.unchecked_reason:
            return False
        self.after = self.apply_tool(self.before)
        if self.unchecked_reason or self.after is None:
            return False
        self.edited_lines = self.changed_lines(self.before or "", self.after)
        return True

    def read_current(self) -> str | None:
        if not self.exists:
            return None
        file_path = Path(self.path)
        try:
            if file_path.stat().st_size > MAX_FILE_BYTES:
                self.unchecked_reason = f"{self.path} is over {MAX_FILE_BYTES} bytes, so the edit was not checked"
                return None
            return file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            self.unchecked_reason = f"{self.path} could not be read ({type(error).__name__}: {error}), so the edit was not checked"
            return None

    def apply_tool(self, current: str | None) -> str | None:
        if self.tool_name == "Write":
            return str(self.tool_input.get("content") or "")
        if self.tool_name == "Edit":
            edits = [self.tool_input]
        else:
            edits = [edit for edit in (self.tool_input.get("edits") or []) if isinstance(edit, dict)]
        text = current
        for edit in edits:
            text = self.apply_one(text, edit)
            if self.unchecked_reason:
                return None
        return text

    def apply_one(self, text: str | None, edit: dict) -> str | None:
        old_string = str(edit.get("old_string") or "")
        new_string = str(edit.get("new_string") or "")
        if text is None:
            if old_string:
                self.unchecked_reason = f"{self.path} does not exist, so the edit could not be applied and was not checked"
                return None
            return new_string
        if old_string not in text:
            self.unchecked_reason = f"old_string was not found in {self.path}, so the edit could not be applied and was not checked"
            return None
        if edit.get("replace_all"):
            return text.replace(old_string, new_string)
        return text.replace(old_string, new_string, 1)

    def changed_lines(self, before: str, after: str) -> set[int]:
        before_lines = before.splitlines()
        after_lines = after.splitlines()
        matcher = difflib.SequenceMatcher(None, before_lines, after_lines, autojunk=False)
        changed: set[int] = set()
        for tag, _before_start, _before_end, after_start, after_end in matcher.get_opcodes():
            if tag == "equal":
                continue
            if after_start == after_end:
                changed.update(line for line in (after_start, after_start + 1) if 1 <= line <= len(after_lines))
                continue
            changed.update(range(after_start + 1, after_end + 1))
        return changed

    def attach_unchecked(self, event: dict[str, object], finding: Finding) -> None:
        for key, item in (("_catstack_unchecked_findings", finding), ("_catstack_stderr_lines", finding.message)):
            raw = event.get(key)
            if not isinstance(raw, list):
                raw = []
                event[key] = raw
            raw.append(item)
