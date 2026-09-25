# Subagents: what the default covers, and what outranks it

SKILL.md carries the one-line rules. This is the boundary between the
Subagents default and the Execution routing section, and which of them wins
where.

## The default is scoped, not general

Fan-out to parallel background/worktree-isolated subagents is the default for
work whose output is information: research, verification, file-scoped reading,
a search too wide to hold in the main thread's context. Separability is the
trigger and context relief is the payoff. Read-only and non-publishing work
stays here even when it is long-running or parallel, because nothing durable
comes out of it.

## Execution routing wins on anything that publishes

Work that produces a commit, a PR, a tag, a merge, a deploy, or any other
durable artifact is routed by [execution-routing.md](execution-routing.md) and
`scripts/route_execution.py` — never by the Subagents default, even when it is
separable, even when it is parallel, and especially when it is both. Both
sections fire on separable parallel PR-worthy work; the routing table is the
one that decides.

Read in the other order, the Subagents default reads as blanket authorization
to fan out, and has been: eight subagents spawned on the strength of
"separable ... default to parallel", each producing a PR-worthy commit, with
`invoker-cli` installed and the routing section never consulted. Nothing in
the Subagents default said no, because nothing in it was ever about
publishing.

The executable form is `route_delegation`. Any publishing output in `produces`
hands the decision straight back to `route_execution`; the durable work kinds
(`post_land_babysit`, `named_execution_backlog`, `approved_plan`) publish by
definition whatever `produces` claims; and an empty or unrecognized `produces`
raises rather than falling through to fan-out, because an output nobody
declared is unchecked, not clean.

## Many stacks: parallel per unit, never serial

Routing picks *who* runs publishing work; it never licenses running several
independent units one after another in the parent thread. When the work is N
independent PR stacks (landing, conflict repair, review fixes), each stack is
its own unit with its own worktree, and the units run in parallel: an Invoker
workflow per stack first, and one worktree-isolated subagent per stack as the
fallback when Invoker is unavailable or the user directs it
(`subagent_worktree_per_unit`). The per-unit subagent still inherits only the
scope the parent names, and its transcript is still grepped for writes.

The failure shape: asked to land dozens of admin-bypass PRs across two repos,
the parent recommended working the ~20 rebases and review fixes "one at a
time" and started serially in one worktree, until the user asked for a
worktree subagent per stack. The routing table allowed it: `route_execution`
returned `local` for publishing work without Invoker at any unit count.

Prior art: Amdahl's law — Gene M. Amdahl, "Validity of the single processor
approach to achieving large scale computing capabilities", AFIPS 1967,
https://doi.org/10.1145/1465482.1465560 — the serial fraction bounds the
whole job, so independent units forced through one thread set the finish
time.

## The user's named shape wins

When the user names the execution shape — one worktree subagent per stack,
one Invoker workflow for everything, do it here in this thread — that choice
wins over the Invoker-first default. Routing picks the shape only when the
user has not. Say so in one line before launching ("Using one worktree
subagent per stack, as you asked, instead of Invoker"), so the override is
visible and can be corrected before any agent starts. Scope and publishing
rules still apply to whatever shape the user named. No known prior art.

## Cap the fan-out and say what it costs

Before a fan-out of more than about 8 agents, state the planned concurrency
(how many run at once, how many total) and the token or usage cost spent so
far in the session, then launch. A wide fan-out spends shared usage quota
fast, and the user cannot weigh that trade without the number.

After a usage-limit stop, resume the agents that serve the original task
first. Hold any extras the fan-out added — side investigations, speculative
repairs, follow-ups the user did not ask for — until the original task's
agents have finished or the user says to run them. No known prior art.

## Defer to the harness's routing skill

The precedence above is catstack's fallback, not the owner. When a harness
ships its own routing skill — today Invoker's `invoker-route-delegation` —
that skill decides publishing-vs-fan-out and this file steps aside.
The fallback stays because the swarm may change: a future harness plugs in
by adding its skill name to `HARNESS_ROUTING_SKILLS` in
`scripts/route_execution.py`, not by editing this rule.

## Prior art

[[principle-subagent-inherits-scope]]: commits, pushes, PRs, merges, deploys
and external calls "need the parent to say so explicitly, and a parent cannot
grant what it does not hold." A default about context relief is not that
explicit grant. The wider rule is least privilege — Saltzer and Schroeder,
"Basic Principles of Information Protection" (1975),
https://web.mit.edu/Saltzer/www/publications/protection/Basic.html — base
access on permission rather than exclusion, so publishing authority is named,
never inherited.
