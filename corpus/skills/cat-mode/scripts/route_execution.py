#!/usr/bin/env python3
"""Executable decision table for cat-mode execution routing.

Mirrors skills/cat-mode/references/execution-routing.md so tests can prove
delegate-vs-local without relying on an agent reading prose.
"""

from __future__ import annotations

from typing import Literal

WorkKind = Literal["readonly", "small_local", "approved_plan", "durable_parallel"]
Route = Literal["local", "delegate_invoker"]
Delegation = Literal["local", "delegate_invoker", "subagent_fanout"]

DURABLE_ALIASES = frozenset({"post_land_babysit", "named_execution_backlog"})

PUBLISHING_OUTPUTS = frozenset({"commit", "pull_request", "tag", "merge", "deploy", "durable_artifact"})
NON_PUBLISHING_OUTPUTS = frozenset({"none", "report", "research", "review", "verification"})
KNOWN_OUTPUTS = PUBLISHING_OUTPUTS | NON_PUBLISHING_OUTPUTS
ALWAYS_PUBLISHING_WORK_KINDS = frozenset(DURABLE_ALIASES | {"approved_plan"})

INVOKER_REQUIRED_TOOLS = (
    "invoker_prepare_plan_review",
    "invoker_submit_plan",
)

DELEGATE_HANDOFF_STEPS = (
    "invoker_prepare_plan_review",
    "await_one_user_approval",
    "invoker_submit_plan",
    "invoker_wait_for_workflow_or_status",
)

SUBAGENT_FANOUT_STEPS = (
    "spawn_worktree_isolated_subagents",
    "collect_reports_async",
    "grep_transcripts_for_writes",
)


def invoker_mcp_available(tool_names: set[str] | frozenset[str] | list[str]) -> bool:
    names = set(tool_names)
    return all(tool in names for tool in INVOKER_REQUIRED_TOOLS)


def normalize_work_kind(work_kind: str) -> WorkKind:
    if work_kind in DURABLE_ALIASES:
        return "durable_parallel"
    if work_kind in ("readonly", "small_local", "approved_plan", "durable_parallel"):
        return work_kind  # type: ignore[return-value]
    raise ValueError(f"unknown work_kind: {work_kind!r}")


def route_execution(*, tools: set[str] | frozenset[str] | list[str], work_kind: str) -> Route:
    """Return where execution should run for this request.

    1. Invoker MCP missing → local
    2. Small / read-only work → local even if Invoker exists
    3. Approved plan or durable/parallel → delegate_invoker
    """
    kind = normalize_work_kind(work_kind)
    if not invoker_mcp_available(tools):
        return "local"
    if kind in ("readonly", "small_local"):
        return "local"
    if kind in ("approved_plan", "durable_parallel"):
        return "delegate_invoker"
    raise ValueError(f"unknown work_kind: {work_kind!r}")


def publishes(*, work_kind: str, produces: set[str] | frozenset[str] | list[str] | tuple[str, ...]) -> bool:
    """Whether this work ends in a commit, PR, or other durable artifact.

    Fails closed: an undeclared or unrecognized output raises instead of
    reading as non-publishing, because an output nobody declared is
    unchecked, not clean.
    """
    outputs = frozenset(produces)
    if not outputs:
        raise ValueError("produces must name at least one output; use 'none' for work that publishes nothing")
    unknown = outputs - KNOWN_OUTPUTS
    if unknown:
        raise ValueError(f"unknown produces value(s): {sorted(unknown)}")
    if work_kind in ALWAYS_PUBLISHING_WORK_KINDS:
        return True
    return bool(outputs & PUBLISHING_OUTPUTS)


def route_delegation(
    *,
    tools: set[str] | frozenset[str] | list[str],
    work_kind: str,
    produces: set[str] | frozenset[str] | list[str] | tuple[str, ...],
) -> Delegation:
    """Resolve the Subagents default against the execution-routing table.

    The Subagents default governs read-only and non-publishing delegation.
    Execution routing wins whenever the work produces a commit, a PR, or a
    durable artifact — separability and parallelism decide nothing on
    their own.
    """
    normalize_work_kind(work_kind)
    if publishes(work_kind=work_kind, produces=produces):
        return route_execution(tools=tools, work_kind=work_kind)
    return "subagent_fanout"


def handoff_steps_for(route: Route | Delegation) -> tuple[str, ...]:
    if route == "local":
        return ("stay_local",)
    if route == "subagent_fanout":
        return SUBAGENT_FANOUT_STEPS
    return DELEGATE_HANDOFF_STEPS


if __name__ == "__main__":
    import json
    import sys

    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    tools = payload.get("tools", [])
    work_kind = payload.get("work_kind", "small_local")
    produces = payload.get("produces")
    if produces is None:
        route: Route | Delegation = route_execution(tools=tools, work_kind=work_kind)
    else:
        route = route_delegation(tools=tools, work_kind=work_kind, produces=produces)
    print(json.dumps({"route": route, "steps": list(handoff_steps_for(route))}))
