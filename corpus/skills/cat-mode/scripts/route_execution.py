#!/usr/bin/env python3
"""Executable decision table for cat-mode execution routing.

Mirrors skills/cat-mode/references/execution-routing.md so tests can prove
delegate-vs-local without relying on an agent reading prose.
"""

from __future__ import annotations

from typing import Literal

WorkKind = Literal["readonly", "small_local", "approved_plan", "durable_parallel"]
Route = Literal["local", "delegate_invoker"]

INVOKER_REQUIRED_TOOLS = (
    "invoker_prepare_plan_review",
    "invoker_submit_plan",
)

DELEGATE_HANDOFF_STEPS = (
    "invoker_prepare_plan_review",
    "await_one_user_approval",
    "invoker_submit_plan",
    "arm_wait_sentinel_end_turn",
)


def invoker_mcp_available(tool_names: set[str] | frozenset[str] | list[str]) -> bool:
    names = set(tool_names)
    return all(tool in names for tool in INVOKER_REQUIRED_TOOLS)


def route_execution(*, tools: set[str] | frozenset[str] | list[str], work_kind: WorkKind) -> Route:
    """Return where execution should run for this request.

    1. Invoker MCP missing → local
    2. Small / read-only work → local even if Invoker exists
    3. Approved plan or durable/parallel → delegate_invoker
    """
    if not invoker_mcp_available(tools):
        return "local"
    if work_kind in ("readonly", "small_local"):
        return "local"
    if work_kind in ("approved_plan", "durable_parallel"):
        return "delegate_invoker"
    raise ValueError(f"unknown work_kind: {work_kind!r}")


def handoff_steps_for(route: Route) -> tuple[str, ...]:
    if route == "local":
        return ("stay_local",)
    return DELEGATE_HANDOFF_STEPS


if __name__ == "__main__":
    import json
    import sys

    payload = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    tools = payload.get("tools", [])
    work_kind = payload.get("work_kind", "small_local")
    route = route_execution(tools=tools, work_kind=work_kind)
    print(json.dumps({"route": route, "steps": list(handoff_steps_for(route))}))
