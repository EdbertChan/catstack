# Blocking consumer contract

Python 3.9+ on POSIX; stdlib only. No subprocess or shell invocation in the runner.
One process owns one connection, wait ID, receipt directory and callback contract.
All simultaneous waits in a harness ownership domain MUST use the same registry.
IDs are exclusive within that registry, not globally across arbitrary registries.
The registry must already exist, belong to the current user, and have mode 0700.
The runner atomically creates its ID directory with mkdir; it never replaces it.
A reused ID is rejected even after completion. Receipt files use exclusive create
and mode 0600. No producer socket or receipt directory is removed on cancellation.

## Spec

Use the shapes in [example.json](example.json), replacing all placeholder values.
The deadline is an absolute Unix timestamp in seconds, at most seven days ahead.
It becomes one monotonic budget when execution starts, covering connection,
subscription, callback registration, snapshot, continuous traffic and delivery.
Terminal receipt writing is bounded in size but filesystem availability is outside
that budget. The receipt MUST be registry / wait ID / terminal.json.

The spec, frame and JSONL record limits are 64 KiB. Duplicate JSON keys, non-finite
numbers, non-object records and unknown configuration fields are rejected. Each
mapping uses literal equality predicates and fixed key/index paths, never eval,
regular expressions, templates or arbitrary selectors. Path arrays have up to
12 components; selectors up to 16 predicates. Strings are exact, case sensitive.
Unknown nonterminal status strings keep waiting. A matched event with missing
identity or status is a source error. Target identifiers and payload text are not
copied to receipts. The caller must use nonsecret control labels.

`source.identity` names the exact source contract. For Unix transport it binds to
the exact configured socket endpoint, not a payload's self-reported identity. Use
a trusted, access-controlled endpoint; this is not authentication against a socket
owner who can replace that endpoint. JSONL stdin is a caller-owned pipe bound to
the named source. It has no subscription or snapshot request API. A bridge must
establish its subscription before handing over that pipe. No arbitrary command
or bridge is spawned by the runner.

Unix transport uses a four-byte unsigned big-endian length followed by UTF-8 JSON.
It optionally sends one `subscribe.request`, awaits literal `subscribe.response`
predicates, and buffers the first matching terminal while waiting. Without a
subscription request the source must broadcast on connection. The source-ready
receipt explicitly distinguishes `transport_only` from `subscription_ack`.

After subscription/connect and callback registration, at most one
`snapshot.request` is sent on that same socket. `response` must identify that
specific request; optional `error` predicates identify its error response.
`record_path` selects one object in the response, and `mapping` selects its exact
subject, identity and status. Include all source-required correlation fields.
Unrelated records are consumed throughout; matching terminal events are retained
while the response is pending. A streamed terminal takes precedence over a stale
snapshot. A failed snapshot remains a source failure even if an event was buffered.
The contract requires terminal transitions to be irreversible within the chosen
attempt. It cannot resolve mutable outcomes or provider ordering without versions.

Event identity is the tuple at `identity_paths`, hashed before persistence.
Matching duplicates are suppressed in memory, including while awaiting a snapshot.
The set holds at most 4096 identities; overflow is explicit `identity_limit`, never
silent eviction. No deduplication or exactly-once promise survives a crash.
The socket/kernel provides bounded in-flight buffering during callback registration;
source disconnect or dropped provider events cannot be repaired by this consumer.

## Callback protocol

An owning harness adapter supplies a **pre-existing** private Unix callback socket.
It is separate from the source and uses the same bounded framing. This package
provides the protocol, not a universal harness broker. No callback subprocess runs.
The adapter must serve concurrent connections without sharing wait state.

The listener sends `{"type":"register","wait_id":"...","owner":"...","nonce":"..."}`.
The adapter replies with exactly the same fields and `type: callback_ready` only
after it has registered delivery to that owning agent. The nonce is a fresh
per-invocation correlation value, not a provider secret. Acknowledgments with
extra fields, another ID, nonce or owner fail closed. Receipt and stdout readiness
messages are separate from the adapter's runtime acknowledgment.

On terminal observation the listener persists event.json, then sends those same
correlation fields with `type: event_received`, `event_digest`, `target_outcome`,
and `origin` (stream or snapshot). The adapter treats these as data only.

- `wake.mode: native`: after notification the process exits with result
  `wake_pending`. Its owning harness awaits that process and delivers completion
  using its own native tool. The **resumed parent** records acknowledgment using
  `python3 scripts/wait_event.py ack-wake --receipt "$EVENT_WAIT_RECEIPT" --owner "$EVENT_WAIT_OWNER" --nonce "$EVENT_WAIT_NONCE"`.
  This creates wake-delivered.json once, without editing the terminal receipt.
  The command is an owner attestation; the consumer cannot independently prove a
  chat turn. Keep a sanitized parent result alongside it as live-path evidence.
- `wake.mode: acknowledged`: a bridge able to obtain a real parent acknowledgment
  before the process exits replies with the exact registration fields and
  `type: wake_delivered`. This is the bridge's attestation of parent delivery,
  not evidence that a synthetic acknowledgment came from a real harness.
- `wake.mode: unsupported`: no callback socket. The consumer still observes the
  event, but terminates nonzero with `session_wake_unsupported`; it is not armed.

A native adapter must not wait for process exit before sending callback_ready;
that creates a deadlock. Conversely, a native listener cannot wait for the parent's
post-exit acknowledgment. The separate ack command breaks that dependency.

## Receipts and exits

Source-ready, callback-ready and event receipts are milestones, not terminal
receipts. One terminal.json is written for an accepted invocation under normal
completion, handled signals and handled source/callback errors. Invalid specs or
ownership conflicts return a redacted diagnostic and never write in a competing
wait's directory. SIGKILL, crashes and failed storage can leave incomplete receipts;
retain the directory and inspect it, do not assume successful delivery or reuse its ID.

Exit 0 means event observation with native delivery pending or acknowledged.
It does **not** mean the target succeeded. Read target_outcome (success, failure,
cancelled) separately. Exit 1 is timeout, source/callback failure, cancellation or
unsupported wake; target_outcome is null until an actual terminal event is received.
Exit 2 is validation, ownership, local storage or acknowledgment failure. Diagnostics
use fixed codes, excluding raw exceptions, payloads and paths. Output is bounded
and nonblocking; an unread/full stdout can cause output_failed rather than hanging.
