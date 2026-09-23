# Worked example: a framed-JSON bus over a Unix socket

A common shape for a local agent bus: every frame is a 4-byte big-endian
length header followed by that many bytes of UTF-8 JSON. One process owns the
listening socket and rebroadcasts each published envelope to every connected
peer.

## Envelope shapes

```text
pub   {"kind": "pub", "channel": "<name>", "body": {...}}
req   {"kind": "req", "channel": "<name>", "reqId": "<id>", "body": {...}}
res   {"kind": "res", "channel": "<name>", "reqId": "<id>", "body": {...}}
err   {"kind": "err", "channel": "<name>", "reqId": "<id>", "code": "<code>"}
```

This is the envelope used by the local IPC bus this skill was generalised
from. Two properties were confirmed by reading that bus's own transport
source, and both matter for the spec you write:

- **Subscription is local.** A subscriber registers a handler inside its own
  process. No subscribe frame goes over the wire, because the owner
  broadcasts every published envelope to all peers. So a wait connects and
  filters client-side, and a source with no snapshot never sends a byte.
- **A request is answered by `reqId`.** A snapshot therefore needs
  `request_id_field` so a reply meant for someone else is ignored.

## Spec for that bus

```json
{
  "wait_id": "wf-4821",
  "deadline_seconds": 3600,
  "receipt_path": "/absolute/private/dir/wf-4821.receipt.json",
  "source": {
    "kind": "unix_socket",
    "path": "<bus-home>/ipc-transport.sock",
    "framing": {"kind": "length_prefix", "prefix_bytes": 4, "byte_order": "big"},
    "event_envelope": {
      "match_fields": {"kind": "pub", "channel": "workflow.lifecycle"},
      "body_path": ["body"]
    }
  },
  "match": {
    "subject_path": ["workflowId"],
    "subject": "wf-4821",
    "status_path": ["status"],
    "terminal_statuses": ["completed", "failed", "cancelled"],
    "event_id_path": ["eventId"]
  },
  "wake": {"mode": "none"}
}
```

Replace `<bus-home>` with the real socket path, and confirm the channel name,
the body field names and the terminal status words against the bus you are
actually attaching to. They are configuration, not constants of this skill.

## Adding the one snapshot

Only add a snapshot when the producer answers requests and the completion may
already have happened before you attached:

```json
"snapshot": {
  "request": {"kind": "req", "channel": "workflow.get", "body": {"workflowId": "wf-4821"}},
  "request_id_field": "reqId",
  "response_match_fields": {"kind": "res"},
  "error_match_fields": {"kind": "err"},
  "body_path": ["body"]
}
```

It is sent once, after attaching. There is no second request, ever. A source
that rejects it ends the wait with `snapshot_rejected` rather than falling
back to asking again.

## Line-delimited sources

A process that prints one JSON object per line needs no framing header:

```json
"source": {
  "kind": "json_stream",
  "command": ["<your-log-follower>", "--follow"],
  "framing": {"kind": "lines"},
  "event_envelope": {"match_fields": {}, "body_path": []}
}
```

Empty `match_fields` accepts every record and an empty `body_path` treats the
whole record as the body. A `path` may name a file or a fifo instead, but a
fifo with no writer attached reads as an immediate end-of-stream, so keep a
writer open or use `command`.

The last record may end at end-of-stream instead of with a newline, so a file
or an exiting command whose final line is the match still matches. Bytes left
over that are not whole JSON are reported as `truncated_frame`.
