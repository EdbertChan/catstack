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


def candidate_paths(cwd: Path, home: Path) -> list[Path]:
    skill_roots = [home / ".claude/skills"]
    root = repo_root(cwd)
    paths = []
    if root is not None:
        skill_roots.extend(root / layer / "skills" for layer in ("engine", "corpus", "product"))
        skill_roots.append(root / ".claude/skills")
        paths.extend((root / "playbooks").glob("*.md"))
    for skill_root in skill_roots:
        paths.extend(skill_root.glob("*/SKILL.md"))
    return sorted({path.resolve() for path in paths})


def ordered_steps(text: str) -> str | None:
    collected = []
    numbers = []
    active = False
    fence = None
    for line in text.splitlines():
        marker = re.match(r"\s*(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            if active:
                collected.append(line)
            continue
        if fence is None:
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
    if fence is not None or not numbers or numbers != list(range(1, len(numbers) + 1)):
        return None
    return "\n".join(collected).strip()


def read_playbook(path: Path) -> Playbook | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
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
    steps = ordered_steps(text)
    if steps is None:
        return None
    return Playbook(path, name, trigger, steps)


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
    hits = []
    for path in candidate_paths(directory, home or Path.home()):
        playbook = read_playbook(path)
        if playbook is not None and matches(prompt, playbook):
            hits.append(playbook)
    if len(hits) != 1:
        return None
    playbook = hits[0]
    return (
        f"Playbook: {playbook.name}\n"
        f"Read and apply the full source at {playbook.path}, including its constraints.\n"
        f"Follow these steps in order:\n\n{playbook.steps}"
    )
