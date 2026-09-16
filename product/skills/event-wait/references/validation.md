# Validation and evidence boundaries

## Disposable spike finding

Before production implementation, two real Python subprocesses attached to a local
framed-JSON Unix producer. B completed before A; A stayed alive and had no receipt
when B completed. Both produced only their matching receipt. The disposable code
was removed. Its output was:

```text
PASS spike: 2 blocking subprocesses; completion B then A; no cross-delivery; status_requests=0
```

This supported one blocking process per wait. It did not measure provider delivery
or crash durability. The maintained suite supersedes the throwaway implementation.

## Rerunnable proof

From the repository root:

```sh
python3 -m unittest discover -s product/skills/event-wait/tests -v
python3 product/skills/event-wait/tests/verify_install.py
python3 scripts/check_skill_file_refs.py
python3 scripts/check_skill_test_coverage.py
```

The suite uses actual subprocesses, pipes, Unix sockets, fragmented frames, callback
connections and filesystem receipts, without importing the runner or mocking its
implementation. It exercises 20 waits, reversed completion, wrong targets/channels/
attempts, duplicates, snapshot races, completion before callback readiness,
cancellation isolation, continuous traffic deadlines, malformed/oversized/truncated
records, disconnect, atomic ID reuse rejection, private receipts and callback
unsupported/failure paths. The producer counts every received request and asserts
exactly one initial snapshot per configured wait and zero later queries.

Native and acknowledged callback tests use a synthetic bridge. They validate the
callback contract, not Claude, Cursor, public CLI idle wake, or live CI delivery.

## Actual tool harness probe

A child agent in the current Codex tool harness created and awaited a real runner
subprocess against a synthetic local producer. The parent entered its blocking
agent-notification wait. The child's final completion returned the terminal receipt
with source_ready, callback_ready and event_received true, wake_delivered false,
and result wake_pending. The resumed parent then invoked ack-wake; it returned
wake_delivered true. The parent inspected the separate owner-attestation receipt.
The child reported zero status requests and one subscription request.

This proves this tool-level child-to-waiting-parent path for that invocation.
It does not prove a wake after an ended chat turn, a public CLI idle session, a
machine restart, or provider CI delivery. Claude and Cursor were not live-tested;
their session/SDK registration was unavailable in this probe.

To rerun with an authorized delegated child, first establish native final-result
notifications, then have the parent enter its blocking wait. The **child** starts
and awaits this utility; caller supplies a fresh private receipt registry and owner:

```sh
python3 product/skills/event-wait/tests/native_probe.py --parent-idle --receipts "$EVENT_WAIT_PROBE_REGISTRY" --owner "$EVENT_WAIT_OWNER"
```

The flag records the parent's handshake; it does not create a harness registration.
After the final child result arrives, only the resumed parent runs ack-wake using
the printed receipt/owner/nonce. Keep only sanitized control receipts and a compact
parent result, never raw conversation transcripts, in review evidence.

## Publication and activation limits

Run make-pr preflight on the actual product-skill diff. The generated trigger
inventory must also recognize a new skill; changing that inventory is outside this
slice's allowed files. A failing repository gate blocks publication even when the
focused suite passes. Do not broaden the review unit or waive the gate silently.

The isolated installer probe uses the canonical scripts/ci entrypoint for harness
parity: the legacy symlink entrypoint computes its root using abspath rather than
resolving its link. A direct legacy invocation failed looking for install.sh one
level above this worktree. The install helper invokes the canonical path instead;
it does not change that engine-owned checker.

No user-home activation is performed: the normal installer cannot target only this
skill. See [installation](install.md) for retained source requirements. Live CI
requires an existing authorized push source; absent that prerequisite it is blocked,
not scored as passing.
