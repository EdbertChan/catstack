# Source bindings and limits

Protocol APIs were read before implementation. The runner uses Python's
[Unix sockets](https://docs.python.org/3/library/socket.html),
[blocking select with a remaining timeout](https://docs.python.org/3/library/select.html#select.select),
and [exclusive filesystem operations](https://docs.python.org/3/library/os.html).
It accepts an already connected JSONL pipe or connects once to a framed JSON Unix
socket. It does not discover providers, authenticate webhooks, run a CLI, reconnect,
or issue queries on a timer. Review adapters separately from this consumer.

## Invoker local broadcast example

The source was read through GitHub's read-only content API, without opening or
changing a primary checkout. The transport's Envelope type defines:

```json
{"kind":"pub","channel":"workflow.lifecycle","body":{"eventKey":"unique-event","workflowId":"chosen-workflow","taskId":"chosen-task","generation":1,"attemptId":"chosen-attempt","status":"completed"}}
```

[IpcBus source](https://github.com/EdbertChan/Invoker/blob/master/packages/transport/src/ipc-bus.ts)
encodes a four-byte big-endian length and JSON body. subscribe() registers a local
filter; there is no wire subscribe message. The server broadcasts pub envelopes to
peers. [Lifecycle event types](https://github.com/EdbertChan/Invoker/blob/master/packages/execution-engine/src/lifecycle-events.ts)
provide eventKey, workflowId, optional taskId/status/attemptId, and generation.
The [publisher bridge](https://github.com/EdbertChan/Invoker/blob/master/packages/app/src/lifecycle-event-bridge.ts)
publishes task-derived events. This is protocol-source evidence, not a live listener
or CI test. Re-read the installed producer version before use.

Copy [example.json](example.json), supply the exact socket path and nonsecret source
identity, omit subscribe, and use this event mapping with caller-selected values:

```json
{
  "channel": {"path": ["channel"], "equals": "workflow.lifecycle"},
  "filters": [{"path": ["kind"], "equals": "pub"}],
  "subject": [
    {"path": ["body", "workflowId"], "equals": "replace-workflow"},
    {"path": ["body", "taskId"], "equals": "replace-task"},
    {"path": ["body", "generation"], "equals": 1},
    {"path": ["body", "attemptId"], "equals": "replace-attempt"}
  ],
  "identity_paths": [["body", "eventKey"]],
  "status_path": ["body", "status"],
  "terminal": {"completed": "success", "failed": "failure"}
}
```

Select only statuses that are terminal for the caller's exact review objective.
Review-ready or needs-input does not mean completed. Missing attemptId will not
match this example; adjust selectors only from the real target's source contract.
It intentionally supplies no snapshot request: the transport envelope alone does
not establish a safe read handler. Already completed targets require a separately
validated one-time read binding; without it this example cannot recover completion
before attachment. Never invoke an external project CLI as a hidden fallback.

For a provider whose documented read request is known, configure snapshot.request
as a literal object, response predicates matching its correlation ID and channel,
error predicates matching its error envelope, record_path to the returned target,
and a mapping of that object's subject/version/status. Tests demonstrate this
contract with a synthetic read handler; they do not establish an Invoker read API.

## CI

[GitHub's webhook documentation](https://docs.github.com/en/webhooks/webhook-events-and-payloads)
defines workflow_run, check_run and check_suite deliveries and the delivery ID
header. They require an existing configured delivery path. This package does not
turn a local socket into a GitHub subscription. An already authorized bridge must
validate provider identity/signatures, retain the delivery ID, select repository,
run ID, attempt and head SHA, and expose a bounded stream contract. The raw webhook
may exceed this consumer's record limit, so a bridge must deliberately project
fields; silently truncating a payload is invalid.

If no supported delivery stream exists, report `source_delivery_unsupported` and
do not arm a wait. No new public receiver, webhook mutation, relay signup or status
watch command is part of this package. A bridge that polls upstream still violates
the no-poll contract even if its downstream socket pushes events. Live CI delivery
remains blocked until an existing authorized event source is supplied and exercised.
