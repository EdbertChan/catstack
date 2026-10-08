"""A private llm-judge verdict channel with a per-transcript verdict cache.

A hook that must hold a tool call until the judge answers uses this instead of
the shared inbox: its jobs ride a channel of their own, so it never drains
another hook's verdicts and the inbox never shows them. Verdicts are cached per
transcript, so each text is judged once. Two hook processes can wait on one job
(parallel tool calls); the one that drains the verdict writes it to the cache,
and the other adopts it from there.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

LLM_JUDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "llm-judge")

HIT, CLEAN, UNCHECKED = "hit", "clean", "unchecked"
OUTCOMES = (HIT, CLEAN, UNCHECKED)
POLL_SECONDS = 0.5
KNOWN_TTL_SECONDS = 2 * 3600
UNCHECKED_TTL_SECONDS = 600


@dataclass(frozen=True)
class ChannelConfig:
    hook: str
    id_prefix: str
    state_env: str
    cache_dirname: str


def llm_judge():
    if LLM_JUDGE_DIR not in sys.path:
        sys.path.insert(0, LLM_JUDGE_DIR)
    import judge
    import phrases

    return judge, phrases


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def wait_seconds(env_name: str, default: float) -> float:
    raw = os.environ.get(env_name)
    if raw is None:
        return default
    try:
        return max(0.0, float(raw))
    except ValueError:
        print(f"catstack-hook-error judge-channel: {env_name}={raw!r} is not a number; waiting {default:g}s", file=sys.stderr)
        return default


def state_path(config: ChannelConfig, transcript: str) -> str:
    root = os.environ.get(config.state_env) or os.path.join(os.path.expanduser("~"), ".cache", config.cache_dirname)
    return os.path.join(root, f"{sha(transcript)}.json")


def load_cache(config: ChannelConfig, transcript: str, now: float) -> dict:
    try:
        with open(state_path(config, transcript), encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        print(f"catstack-hook-error {config.hook}: unreadable verdict cache, treating it as empty: {exc}", file=sys.stderr)
        return {}
    if not isinstance(data, dict):
        print(f"catstack-hook-error {config.hook}: verdict cache is not an object, treating it as empty", file=sys.stderr)
        return {}
    kept = {}
    for job_id, entry in data.items():
        if not isinstance(entry, dict) or entry.get("outcome") not in OUTCOMES:
            continue
        at = entry.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)) or at > now:
            continue
        ttl = UNCHECKED_TTL_SECONDS if entry["outcome"] == UNCHECKED else KNOWN_TTL_SECONDS
        if now - at <= ttl:
            kept[job_id] = entry
    return kept


def save_cache(config: ChannelConfig, transcript: str, cache: dict) -> None:
    path = state_path(config, transcript)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        temp = f"{path}.{os.getpid()}.tmp"
        with open(temp, "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
        os.replace(temp, path)
    except OSError as exc:
        print(f"catstack-hook-error {config.hook}: could not write verdict cache {path}: {exc}", file=sys.stderr)


def channel(config: ChannelConfig, transcript: str) -> str:
    return f"{transcript}#{config.hook}"


def job_id(config: ChannelConfig, checker: str, transcript: str, text: str) -> str:
    return f"{config.id_prefix}-{sha(checker)}-{sha(transcript + chr(0) + text)}"


class Verdicts:
    def __init__(self, config: ChannelConfig, transcript: str, now: float):
        self.config = config
        self.transcript = transcript
        self.cache = load_cache(config, transcript, now)
        self.reasons: dict[str, str] = {}

    def outcome(self, jid: str) -> str | None:
        entry = self.cache.get(jid)
        return entry.get("outcome") if entry else None

    def request(self, checker: str, text: str) -> str:
        jid = job_id(self.config, checker, self.transcript, text)
        if self.outcome(jid) is not None:
            return jid
        judge, phrases = llm_judge()
        if os.path.exists(os.path.join(judge.state_root(), "jobs", f"{jid}.json")):
            return jid
        dictionary = phrases.load(checker)
        job = phrases.job(dictionary, channel(self.config, self.transcript), text)
        job["id"] = jid
        if judge.enqueue(job) is None:
            self.record(jid, UNCHECKED, "the judge refused the job (running inside a judge or a subagent)")
        return jid

    def record(self, jid: str, outcome: str, reason: str = "") -> None:
        self.cache[jid] = {"outcome": outcome, "at": time.time()}
        if reason:
            self.reasons[jid] = reason

    def collect(self) -> None:
        judge, _ = llm_judge()
        drained = False
        for verdict in judge.drain(channel(self.config, self.transcript)):
            jid = verdict.get("id")
            outcome = verdict.get("outcome")
            if isinstance(jid, str) and outcome in OUTCOMES:
                self.record(jid, outcome, str(verdict.get("reason") or ""))
                drained = True
        if drained:
            self.save()
        for jid, entry in load_cache(self.config, self.transcript, time.time()).items():
            self.cache.setdefault(jid, entry)

    def save(self) -> None:
        merged = load_cache(self.config, self.transcript, time.time())
        merged.update(self.cache)
        save_cache(self.config, self.transcript, merged)


def await_verdicts(verdicts: Verdicts, needed: list[str], settle: Callable[[], object], wait: float) -> object:
    """Poll until settle() returns something other than None or the wait runs out.

    A needed verdict still missing at the deadline is recorded as UNCHECKED, and
    settle() is asked once more so it can decide on that.
    """
    deadline = time.monotonic() + wait
    while True:
        verdicts.collect()
        result = settle()
        if result is not None or time.monotonic() >= deadline:
            break
        time.sleep(POLL_SECONDS)
    for jid in needed:
        if verdicts.outcome(jid) is None:
            verdicts.record(jid, UNCHECKED, f"no verdict within {wait:g}s")
    return settle()
