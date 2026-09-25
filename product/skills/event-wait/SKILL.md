---
name: event-wait
description: >-
  Wait for a background job, workflow, build, or continuous-integration run to
  finish by subscribing to the events it already pushes, instead of asking for
  status over and over. Use when a task must block until something elsewhere
  completes, when many such waits must run at once, or when a wait needs to
  wake an idle session. Replaces hand-rolled one-off listeners and status
  polling loops.
---

# event-wait

One blocking process per wait. It attaches to a push source, says it is
armed, optionally asks once for current state, then sleeps until its own
event arrives. Nothing asks the producer again.

Run it with `scripts/wait_event.py`:

```bash
python3 scripts/wait_event.py --spec /absolute/path/to/spec.json
```

## Do not poll

There is no status timer, no repeated snapshot, no reconnect-and-rescan loop.
If a source cannot push, this skill is the wrong tool — say so instead of
writing a sleep-and-check loop behind its back.

## When a remote host can only be asked

If the only way to learn the state is to ask a remote host over `ssh`, say so,
then use `scripts/remote_watch.py` instead of a hand-written watcher loop:

```bash
python3 scripts/remote_watch.py --host box --remote-script /abs/read-status.sh \
  --status-field status --terminal completed --terminal failed \
  --idle idle --stall-seconds 600 --pidfile /abs/private/watch-4821.pid
```

- **The remote part is its own file**, sent as `ssh box 'bash -s' < file`. A
  quoted command string on the `ssh` line is expanded by the local shell
  first, so `${wf: -2}` fails locally with `wf: unbound variable`.
- **The file prints one JSON line.** The watcher reads `--status-field` from
  the last line.
- **Every reading has three outcomes**: a status, a terminal status, or
  `unread`. An empty reading, text that is not JSON, a missing field, a
  failed `ssh`, or a timeout is `unread`. It never counts toward a stall and
  never passes as clean. Enough `unread` readings in a row end the wait with
  exit `4`, not a stall verdict.
- **A stall is only real readings.** Only readable readings whose status is in
  `--idle` for `--stall-seconds` give exit `3`.
- **One watcher per job.** A new watcher with the same `--pidfile` stops the
  older one first. It checks the recorded pid and start time, so it never
  signals an unrelated process that reused the pid.
- **A thing that disappears is not a failure.** If a cleanup job can remove
  the watched item, have the remote file print its own status for that case
  (for example `"gone"`) and decide what it means. Do not let an empty
  reading stand for it.

## The order that makes this correct

1. **Attach first.** Connect or start the stream before anything else.
2. **Acknowledge.** The runner prints one `armed` record. The caller MUST read
   that line before it triggers the work it wants to wait for. A producer that
   emits before the wait is attached emits into nothing.
3. **Snapshot at most once.** Only if the spec declares one, and only after
   attaching, to recover a completion that already happened.
4. **Block.** A live event is matched the moment it arrives, including while
   the snapshot reply is still in flight, so a completion inside that window is
   never parked behind a reply that may never come.

## The spec

Every selector is a literal field path plus a literal value. Nothing in the
spec is an expression, and nothing from a producer payload is ever executed.

```json
{
  "wait_id": "build-4821",
  "deadline_seconds": 1800,
  "receipt_path": "/absolute/private/dir/build-4821.receipt.json",
  "claim_dir": "/absolute/private/dir",
  "source": {
    "kind": "unix_socket",
    "path": "/absolute/path/to/bus.sock",
    "framing": {"kind": "length_prefix", "prefix_bytes": 4, "byte_order": "big"},
    "event_envelope": {
      "match_fields": {"kind": "pub", "channel": "workflow.lifecycle"},
      "body_path": ["body"]
    },
    "snapshot": {
      "request": {"kind": "req", "channel": "workflow.get", "body": {"id": "4821"}},
      "request_id_field": "reqId",
      "response_match_fields": {"kind": "res"},
      "error_match_fields": {"kind": "err"},
      "body_path": ["body"]
    }
  },
  "match": {
    "subject_path": ["workflowId"],
    "subject": "4821",
    "status_path": ["status"],
    "terminal_statuses": ["completed", "failed", "cancelled"],
    "event_id_path": ["eventId"]
  },
  "wake": {"mode": "none"},
  "limits": {"max_frame_bytes": 1048576, "max_record_bytes": 65536}
}
```

Unknown keys are refused. So are relative paths, an out-of-range deadline, and
a wait id with anything but letters, digits, dot, dash and underscore.

### Sources

- `unix_socket` — connect to a socket carrying framed JSON. Framing is
  `length_prefix` (2, 4 or 8 byte big- or little-endian header) or `lines`.
  Only this source may declare a `snapshot`.
- `json_stream` — read JSON records from a child process you name in
  `command`, or from a file or fifo you name in `path`. Read-only: it never
  gets written to, and it may not declare a snapshot.

See `references/framed-socket-source.md` for a worked socket example.

### Ownership

`wait_id` and `receipt_path` are both claimed with an exclusive create, so two
waits racing for either one can never both win — there is no check-then-create
gap. Point every wait's `claim_dir` at one shared private directory to make
wait ids exclusive everywhere rather than per receipt directory. The receipt
directory must not be group- or world-writable.

A wait cleans up only its own claim. It never touches the producer, another
wait, or another wait's receipt.

## Two things the receipt keeps apart

`event_received` says the event arrived. `wake_delivered` says the session was
told. They are separate fields because process output is not proof that a chat
resumed.

```json
{"record": "receipt", "outcome": "matched", "event_received": true,
 "wake_delivered": false, "wake_status": "session_wake_unsupported",
 "matched_via": "stream", "status": "completed", "exit_code": 0}
```

Exit codes: `0` matched, `2` spec invalid, `3` deadline passed, `4` source
error, `5` claim conflict, `6` cancelled, `7` matched but the wake failed.

A source error is a fact about the source. It is never evidence that the
watched job failed, and never evidence that it succeeded.

## Waking a session

`wake.mode: "none"` reports `session_wake_unsupported`. That is the honest
answer when a harness offers no push-wake, and it is required instead of
quietly polling or claiming a wake path that was never proven.

`wake.mode: "command"` runs an argument list from the spec — never a shell
string, never anything built from a payload. The command sees only
spec-derived values in its environment: the wait id, subject, receipt path,
declared owner, and the matched status, which must already be one of the
declared `terminal_statuses`. The receipt is written after the wake attempt,
so the wake command must read those variables rather than the receipt file.

Declare `ready_argv` to prove the wake can actually run. Without it the
`armed` record says `callback_status: "unproven"` — armed source, unproven
callback. `source_ready` and `callback_ready` are separate acknowledgments
for exactly this reason.

**Create and await the wait in the same agent that owns the wake.** A process
handle made by a parent agent is not usable by a child; the child is told the
process id is unknown. Handing the handle down does not transfer ownership.

`references/harness-wake.md` records what each harness actually supports.

## Limits this makes explicit

- Frames and matched records are size-capped; an oversize frame is refused
  from its header, before the body is read.
- Errors name a code, a field and a byte count. They never quote payload bytes.
- The deadline is absolute and monotonic. Continuous unrelated traffic cannot
  extend it.
- Malformed JSON, a truncated frame, and a disconnect before a match each end
  the wait with a nonzero exit, not a silent retry.
- A bad frame only fails the records behind it. Records decoded earlier in the
  same read are matched first, so a terminal event that shares a read with an
  oversize or malformed frame still completes the wait.
- Delivery is not exactly-once across a crash. A wait that dies leaves its
  claimed receipt file behind, which is what makes a reused id fail loudly.
- A synthetic local producer proves the protocol only. It is not evidence that
  any real continuous-integration service or harness delivers these events.

## Tests

```bash
python3 -m unittest discover -s tests
```
