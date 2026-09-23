# What each harness can actually do about waking a session

A wait that finishes is not a session that resumed. Before declaring a
`wake.mode` other than `none`, confirm the mechanism exists in the harness
version you are running, and prove it with `ready_argv`.

## The ownership rule that costs the most time

Create the wait process **in the same agent that will consume its result**.
A process handle created by a parent agent cannot be awaited by a child agent
— the child is told the process id is unknown. Passing the identifier down
does not pass ownership down. If a child must wait, the child starts the wait.

## Claude Code

The hooks documentation defines an async hook field:

> `asyncRewake` | no | If `true`, runs in the background and wakes Claude on
> exit code 2. The hook's stderr, or stdout if stderr is empty, is shown to
> Claude as a system reminder so it can react to a long-running background
> failure

Two consequences for this skill:

- **The wake is triggered by exit code 2, which is not this runner's success
  code.** A match exits `0`. So an async hook wraps the runner and translates:
  run the wait, and if it matched, exit 2 with the message on stderr. The
  wrapper's exit code is a wake signal, not the watched job's outcome — never
  read "exit 2" as "the build failed".
- The documented `timeout` field is not enforced on a command hook run with
  `async: true`, so the wait's own `deadline_seconds` is the bound that
  actually applies. Set it deliberately.

The same page does not say whether this resumes a session that is already
idle. Treat idle-session wake as unproven until you have seen it work in your
own session, and report `session_wake_unsupported` rather than claiming it.

## Codex CLI

`codex queue --thread <THREAD> --message <TEXT>` queues a message for an
existing session, addressed by session UUID or exact session name. That makes
a usable `wake.argv`, scoped to a session you know the identifier of.

The top-level `notify` program in the Codex configuration is a turn-ended
notification: it runs an external program when a turn ends. It notifies
outward. It does not push anything back into the session, so it is not a wake
path for this skill.

Subagent-completion notifications are scoped to a process that the same child
started and awaited. Do not assume a shell process handle transfers between
agents, and do not assume every published build exposes the same
notify-on-output configuration.

## Cursor

The local agent CLI offers starting a chat, resuming a chat and listing
chats. It exposes no command that pushes a message into a session that is
already running, so for an external wait the honest report is
`session_wake_unsupported`.

Following up on a background subagent is scoped to runs the local SDK itself
owns: inside such a run you can await your own subagent, which is not the same
as waking a separate interactive session from outside.

## When nothing is supported

Leave `wake.mode` as `none`. The wait still blocks correctly and still writes
a receipt; the caller simply has to be the one holding the foreground. That is
a real limitation to report, not a reason to start polling.
