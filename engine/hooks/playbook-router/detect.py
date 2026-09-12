from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re


@dataclass(frozen=True)
class Playbook:
    path: Path
    name: str
    trigger: str
    body: str


@dataclass(frozen=True)
class Procedure:
    playbook: Playbook
    source: Path
    steps: str


def extract_prompt_text(payload: dict) -> str:
    for key in ("prompt", "user_prompt", "userPrompt", "message", "text"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value
    content = payload.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts)
    return ""


def repo_root(cwd: Path) -> Path | None:
    for directory in (cwd, *cwd.parents):
        if (directory / ".git").exists():
            return directory
    return None


def candidate_paths(cwd: Path, home: Path) -> list[tuple[Path, int]]:
    ranked = {}
    root = repo_root(cwd)
    if root is not None:
        repository = list((root / "playbooks").glob("*.md"))
        for layer in ("engine", "corpus", "product", ".claude"):
            repository.extend((root / layer / "skills").glob("*/SKILL.md"))
        ranked.update((path.resolve(), 0) for path in repository)
    for path in (home / ".claude/skills").glob("*/SKILL.md"):
        ranked.setdefault(path.resolve(), 1)
    return sorted(ranked.items())


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def fence_states(text: str) -> tuple[list[tuple[str, bool]], bool]:
    states = []
    fence = None
    for line in text.splitlines():
        marker = re.match(r"\s*(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            states.append((line, True))
        else:
            states.append((line, fence is not None))
    return states, fence is None


def consecutive(numbers: list[int]) -> bool:
    return bool(numbers) and numbers == list(range(1, len(numbers) + 1))


def listed_steps(lines: list[tuple[str, bool]]) -> str | None:
    collected = []
    numbers = []
    active = False
    for line, fenced in lines:
        if not fenced:
            if not active:
                active = re.fullmatch(r" {0,3}## Steps[ \t]*", line) is not None
                continue
            if re.match(r"^ {0,3}#{1,2}\s", line):
                break
            item = re.match(r"^(\d+)\.\s+\S", line)
            if item:
                numbers.append(int(item.group(1)))
        if active:
            collected.append(line)
    return "\n".join(collected).strip() if consecutive(numbers) else None


def heading_steps(lines: list[tuple[str, bool]]) -> str | None:
    headings = []
    for line, fenced in lines:
        heading = None if fenced else re.fullmatch(r" {0,3}##[ \t]+(\d+)\.[ \t]+(\S.*?)[ \t]*", line)
        if heading:
            headings.append((int(heading.group(1)), heading.group(2)))
    if not consecutive([number for number, _ in headings]):
        return None
    return "\n".join(f"{number}. {title}" for number, title in headings)


def procedure_steps(text: str, headings: bool) -> str | None:
    lines, closed = fence_states(text)
    if not closed:
        return None
    steps = listed_steps(lines)
    if steps is None and headings:
        steps = heading_steps(lines)
    return steps


def nested_procedure(directory: Path) -> tuple[Path, str] | None:
    found = []
    for path in sorted(directory.glob("*.md")):
        text = read_text(path)
        if text is None:
            return None
        steps = procedure_steps(text, headings=True)
        if steps is not None:
            found.append((path.resolve(), steps))
    return found[0] if len(found) == 1 else None


def read_playbook(path: Path) -> Playbook | None:
    text = read_text(path)
    if text is None:
        return None
    name = path.parent.name if path.name == "SKILL.md" else path.stem
    if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) is None:
        return None
    trigger = name.replace("-", " ")
    if text.startswith("---\n"):
        sections = text.split("\n---", 1)
        if len(sections) != 2:
            return None
        header, text = sections
        overrides = re.findall(r"^playbook-trigger:[ \t]*(.*)$", header, re.MULTILINE)
        if overrides:
            if len(overrides) != 1:
                return None
            trigger = overrides[0].strip()
            if trigger.startswith('"'):
                try:
                    trigger = json.loads(trigger)
                except ValueError:
                    return None
            if not isinstance(trigger, str) or re.fullmatch(r"[A-Za-z0-9]+(?:[ -]+[A-Za-z0-9]+)+", trigger) is None:
                return None
    return Playbook(path, name, trigger, text)


def procedure(playbook: Playbook) -> Procedure | None:
    if playbook.path.name != "SKILL.md":
        steps = procedure_steps(playbook.body, headings=True)
        return None if steps is None else Procedure(playbook, playbook.path, steps)
    steps = procedure_steps(playbook.body, headings=False)
    if steps is not None:
        return Procedure(playbook, playbook.path, steps)
    nested = nested_procedure(playbook.path.parent / "playbooks")
    return None if nested is None else Procedure(playbook, *nested)


def matches(prompt: str, playbook: Playbook) -> bool:
    phrase = r"[ -]+".join(re.escape(word) for word in re.split(r"[ -]+", playbook.trigger))
    invocation = rf"(?:/{re.escape(playbook.name)}|{phrase})"
    return re.match(
        rf"^\s*(?:please\s+)?(?:(?:run|use|follow)\s+(?:the\s+)?)?{invocation}(?=$|\s|[,:;!?]|\.$)",
        prompt,
        re.IGNORECASE,
    ) is not None


def decide(payload: dict, home: Path | None = None) -> str | None:
    prompt = extract_prompt_text(payload)
    if not prompt.strip():
        return None
    cwd = payload.get("cwd")
    directory = Path(cwd).resolve() if isinstance(cwd, str) and cwd else Path.cwd()
    by_name = {}
    for path, rank in candidate_paths(directory, home or Path.home()):
        playbook = read_playbook(path)
        if playbook is None or not matches(prompt, playbook):
            continue
        found = procedure(playbook)
        if found is not None:
            by_name.setdefault(playbook.name, []).append((rank, found))
    hits = []
    for ranked in by_name.values():
        nearest = min(rank for rank, _ in ranked)
        hits.extend(found for rank, found in ranked if rank == nearest)
    if len(hits) != 1:
        return None
    found = hits[0]
    sources = " and ".join(dict.fromkeys(str(path) for path in (found.playbook.path, found.source)))
    return (
        f"Playbook: {found.playbook.name}\n"
        f"Read and apply the full source at {sources}, including its constraints.\n"
        f"Follow these steps in order:\n\n{found.steps}"
    )
