#!/usr/bin/env python3
"""Tests for wait_event.py against real Unix sockets and real subprocesses.

Every source here is a real socket server or a real child process, never a
stand-in for the runner's own code, so the assertions exercise framing,
concurrency and process lifetime rather than mirroring the implementation.
The producer counts the bytes and records it receives, which is what proves
the no-polling claim independently of anything the runner reports about
itself.

A synthetic producer proves the protocol only. It is not evidence that any
real continuous-integration service or agent harness delivers these events.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")
RUNNER = os.path.join(SCRIPTS, "wait_event.py")
sys.path.insert(0, SCRIPTS)
import wait_event  # noqa: E402

CHANNEL = "workflow.lifecycle"
DEADLINE = 20.0


def frame(payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + payload


def pub(body: dict, channel: str = CHANNEL) -> bytes:
    return frame(json.dumps({"kind": "pub", "channel": channel, "body": body}).encode("utf-8"))


def wait_until(predicate, timeout=10.0, interval=0.01):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class Producer:
    """A real framed-JSON Unix socket bus that records everything it is sent."""

    def __init__(self, directory: str, name: str = "bus.sock") -> None:
        self.path = os.path.join(directory, name)
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(self.path)
        self.server.listen(64)
        self.peers: list[socket.socket] = []
        self.inbound_bytes = 0
        self.requests: list[dict] = []
        self.on_request = None
        self.running = True
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._accept_loop, daemon=True)
        self.thread.start()

    def _accept_loop(self) -> None:
        while self.running:
            try:
                peer, _ = self.server.accept()
            except OSError:
                return
            with self.lock:
                self.peers.append(peer)
            threading.Thread(target=self._read_loop, args=(peer,), daemon=True).start()

    def _read_loop(self, peer: socket.socket) -> None:
        buffer = b""
        while self.running:
            try:
                chunk = peer.recv(65536)
            except OSError:
                return
            if not chunk:
                return
            with self.lock:
                self.inbound_bytes += len(chunk)
            buffer += chunk
            while len(buffer) >= 4:
                length = struct.unpack(">I", buffer[:4])[0]
                if len(buffer) < 4 + length:
                    break
                record = json.loads(buffer[4 : 4 + length].decode("utf-8"))
                buffer = buffer[4 + length :]
                with self.lock:
                    self.requests.append(record)
                if self.on_request is not None:
                    self.on_request(peer, record)

    def wait_for_peers(self, expected: int, timeout: float = 15.0) -> bool:
        return wait_until(lambda: self.peer_count() >= expected, timeout=timeout)

    def send_raw(self, payload: bytes, expect_peers: int = 1) -> None:
        """Send to every connected peer, waiting for the expected ones to exist.

        A client's connect() returns as soon as the kernel queues it on the
        listen backlog, so without this wait a test can emit into an empty peer
        list and then hang on a wait that never saw the event. Pass
        expect_peers=0 to emit deliberately into an empty bus.
        """
        if expect_peers and not self.wait_for_peers(expect_peers):
            raise AssertionError(f"fewer than {expect_peers} waits connected to the producer")
        with self.lock:
            peers = list(self.peers)
        for peer in peers:
            try:
                peer.sendall(payload)
            except OSError:
                pass

    def send_to(self, peer: socket.socket, payload: bytes) -> None:
        try:
            peer.sendall(payload)
        except OSError:
            pass

    def emit(self, body: dict, channel: str = CHANNEL, expect_peers: int = 1) -> None:
        self.send_raw(pub(body, channel), expect_peers=expect_peers)

    def peer_count(self) -> int:
        with self.lock:
            return len(self.peers)

    def request_count(self) -> int:
        with self.lock:
            return len(self.requests)

    def drop_peers(self, expect: int = 0) -> None:
        if expect and not self.wait_for_peers(expect):
            raise AssertionError(f"fewer than {expect} peers connected")
        with self.lock:
            peers, self.peers = list(self.peers), []
        for peer in peers:
            try:
                peer.close()
            except OSError:
                pass

    def stop(self) -> None:
        self.running = False
        self.drop_peers()
        try:
            self.server.close()
        except OSError:
            pass


class WaitProcess:
    """One runner subprocess plus the records it printed."""

    def __init__(self, spec: dict, directory: str) -> None:
        self.spec = spec
        self.spec_path = os.path.join(directory, f"{spec['wait_id']}.spec.json")
        with open(self.spec_path, "w", encoding="utf-8") as handle:
            json.dump(spec, handle)
        self.process = subprocess.Popen(
            [sys.executable, RUNNER, "--spec", self.spec_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.armed = None
        self.receipt = None
        self.stderr = ""

    def read_armed(self, timeout: float = 15.0) -> dict:
        self.armed = self._read_record(timeout)
        return self.armed

    def _read_record(self, timeout: float) -> dict:
        result: list = []

        def reader():
            line = self.process.stdout.readline()
            result.append(line)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        thread.join(timeout)
        if not result or not result[0]:
            raise AssertionError(f"no record within {timeout}s")
        return json.loads(result[0])

    def finish(self, timeout: float = 25.0) -> dict:
        self.receipt = self._read_record(timeout)
        self.process.wait(timeout=timeout)
        self.stderr = self.process.stderr.read()
        return self.receipt

    def kill(self) -> None:
        if self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)


class EventWaitTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = tempfile.mkdtemp(prefix="event-wait-test-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.waits: list[WaitProcess] = []

    def tearDown(self) -> None:
        for wait in self.waits:
            wait.kill()

    def socket_spec(self, wait_id: str, subject: str, sock_path: str, **overrides) -> dict:
        spec = {
            "wait_id": wait_id,
            "deadline_seconds": overrides.pop("deadline_seconds", DEADLINE),
            "receipt_path": os.path.join(self.dir, f"{wait_id}.receipt.json"),
            "source": {
                "kind": "unix_socket",
                "path": sock_path,
                "framing": {"kind": "length_prefix", "prefix_bytes": 4, "byte_order": "big"},
                "event_envelope": {
                    "match_fields": {"kind": "pub", "channel": CHANNEL},
                    "body_path": ["body"],
                },
            },
            "match": {
                "subject_path": ["workflowId"],
                "subject": subject,
                "status_path": ["status"],
                "terminal_statuses": ["completed", "failed", "cancelled"],
                "event_id_path": ["eventId"],
            },
            "wake": {"mode": "none"},
        }
        for key, value in overrides.items():
            if key in ("snapshot",):
                spec["source"]["snapshot"] = value
            else:
                spec[key] = value
        return spec

    def start(self, spec: dict) -> WaitProcess:
        wait = WaitProcess(spec, self.dir)
        self.waits.append(wait)
        return wait

    def producer(self, name: str = "bus.sock") -> Producer:
        producer = Producer(self.dir, name)
        self.addCleanup(producer.stop)
        return producer

    def read_receipt_file(self, spec: dict) -> dict:
        with open(spec["receipt_path"], encoding="utf-8") as handle:
            return json.load(handle)


class ConcurrencyTests(EventWaitTestCase):
    def test_two_concurrent_waits_route_to_their_own_subject(self):
        producer = self.producer()
        specs = [self.socket_spec(f"pair-{name}", f"wf-{name}", producer.path) for name in "AB"]
        waits = [self.start(spec) for spec in specs]
        for wait in waits:
            self.assertTrue(wait.read_armed()["source_ready"])
        self.assertTrue(wait_until(lambda: producer.peer_count() == 2))

        producer.emit({"workflowId": "wf-B", "status": "completed", "eventId": "e1"})
        first = waits[1].finish()
        producer.emit({"workflowId": "wf-A", "status": "failed", "eventId": "e2"})
        second = waits[0].finish()

        self.assertEqual((first["subject"], first["status"]), ("wf-B", "completed"))
        self.assertEqual((second["subject"], second["status"]), ("wf-A", "failed"))
        self.assertEqual(first["exit_code"], 0)
        self.assertEqual(second["exit_code"], 0)
        self.assertEqual(waits[0].process.returncode, 0)
        self.assertEqual(waits[1].process.returncode, 0)

    def test_twenty_concurrent_waits_complete_in_reverse_order_without_cross_delivery(self):
        producer = self.producer()
        count = 20
        specs = [
            self.socket_spec(f"many-{index:02d}", f"wf-{index:02d}", producer.path)
            for index in range(count)
        ]
        waits = [self.start(spec) for spec in specs]
        for wait in waits:
            self.assertTrue(wait.read_armed(timeout=25.0)["source_ready"])
        self.assertTrue(wait_until(lambda: producer.peer_count() == count, timeout=20.0))

        producer.emit({"workflowId": "wf-nobody", "status": "completed", "eventId": "noise"})
        for index in reversed(range(count)):
            producer.emit(
                {"workflowId": f"wf-{index:02d}", "status": "completed", "eventId": f"e{index}"}
            )

        for index, wait in enumerate(waits):
            receipt = wait.finish(timeout=40.0)
            self.assertEqual(receipt["subject"], f"wf-{index:02d}")
            self.assertEqual(receipt["wait_id"], f"many-{index:02d}")
            self.assertEqual(receipt["status"], "completed")
            self.assertEqual(receipt["exit_code"], 0, receipt)
            body = json.loads(receipt["event_excerpt"])
            self.assertEqual(body["workflowId"], f"wf-{index:02d}")

        self.assertEqual(producer.request_count(), 0)
        self.assertEqual(producer.inbound_bytes, 0)

    def test_cancelling_one_wait_leaves_its_neighbour_alive(self):
        producer = self.producer()
        spec_a = self.socket_spec("cancel-A", "wf-A", producer.path)
        spec_b = self.socket_spec("cancel-B", "wf-B", producer.path)
        wait_a, wait_b = self.start(spec_a), self.start(spec_b)
        wait_a.read_armed()
        wait_b.read_armed()

        wait_a.process.send_signal(signal.SIGTERM)
        receipt_a = wait_a.finish()
        self.assertEqual(receipt_a["outcome"], "cancelled")
        self.assertEqual(receipt_a["exit_code"], wait_event.EXIT_CANCELLED)
        self.assertEqual(wait_a.process.returncode, wait_event.EXIT_CANCELLED)
        self.assertFalse(receipt_a["event_received"])

        self.assertIsNone(wait_b.process.poll())
        producer.emit({"workflowId": "wf-B", "status": "completed", "eventId": "b1"})
        receipt_b = wait_b.finish()
        self.assertEqual(receipt_b["outcome"], "matched")
        self.assertEqual(receipt_b["subject"], "wf-B")

    def test_cancelled_wait_removes_only_its_own_claim(self):
        producer = self.producer()
        spec_a = self.socket_spec("claim-A", "wf-A", producer.path)
        spec_b = self.socket_spec("claim-B", "wf-B", producer.path)
        wait_a, wait_b = self.start(spec_a), self.start(spec_b)
        wait_a.read_armed()
        wait_b.read_armed()
        claim_b = os.path.join(self.dir, "claim-B.claim")
        self.assertTrue(os.path.exists(claim_b))

        wait_a.process.send_signal(signal.SIGTERM)
        wait_a.finish()
        self.assertFalse(os.path.exists(os.path.join(self.dir, "claim-A.claim")))
        self.assertTrue(os.path.exists(claim_b))
        self.assertTrue(os.path.exists(spec_a["receipt_path"]))


class RoutingTests(EventWaitTestCase):
    def test_unrelated_events_and_wrong_target_never_match(self):
        producer = self.producer()
        spec = self.socket_spec("routing", "wf-target", producer.path, deadline_seconds=3.0)
        wait = self.start(spec)
        wait.read_armed()

        producer.emit({"workflowId": "wf-other", "status": "completed", "eventId": "x1"})
        producer.emit({"workflowId": "wf-target", "status": "running", "eventId": "x2"})
        producer.emit({"workflowId": "wf-target", "status": "completed"}, channel="other.channel")
        producer.send_raw(frame(json.dumps({"kind": "req", "channel": CHANNEL, "reqId": "9"}).encode()))

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "timeout")
        self.assertFalse(receipt["event_received"])
        self.assertEqual(receipt["exit_code"], wait_event.EXIT_TIMEOUT)

    def test_duplicate_events_are_skipped_by_event_identity(self):
        producer = self.producer()
        spec = self.socket_spec("dupes", "wf-1", producer.path, deadline_seconds=4.0)
        wait = self.start(spec)
        wait.read_armed()

        for _ in range(3):
            producer.emit({"workflowId": "wf-1", "status": "running", "eventId": "same"})
        time.sleep(0.3)
        producer.emit({"workflowId": "wf-1", "status": "completed", "eventId": "final"})

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "matched")
        self.assertEqual(receipt["duplicate_events_skipped"], 2)

    def test_repeated_terminal_event_still_writes_one_receipt(self):
        producer = self.producer()
        spec = self.socket_spec("one-receipt", "wf-1", producer.path)
        wait = self.start(spec)
        wait.read_armed()
        for _ in range(4):
            producer.emit({"workflowId": "wf-1", "status": "completed", "eventId": "t1"})

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "matched")
        with open(spec["receipt_path"], encoding="utf-8") as handle:
            self.assertEqual(len([line for line in handle if line.strip()]), 1)
        self.assertEqual(self.read_receipt_file(spec)["status"], "completed")

    def test_timeout_holds_under_continuous_unrelated_traffic(self):
        producer = self.producer()
        spec = self.socket_spec("busy", "wf-quiet", producer.path, deadline_seconds=2.0)
        wait = self.start(spec)
        wait.read_armed()

        stop = threading.Event()

        def flood():
            index = 0
            while not stop.is_set():
                producer.emit({"workflowId": "wf-noisy", "status": "running", "eventId": f"n{index}"})
                index += 1
                time.sleep(0.01)

        thread = threading.Thread(target=flood, daemon=True)
        thread.start()
        started = time.monotonic()
        receipt = wait.finish()
        stop.set()
        thread.join(timeout=5)
        elapsed = time.monotonic() - started

        self.assertEqual(receipt["outcome"], "timeout")
        self.assertEqual(receipt["error_code"], "deadline_exceeded")
        self.assertLess(elapsed, 8.0, "continuous traffic must not extend the deadline")
        self.assertGreaterEqual(receipt["elapsed_seconds"], 1.9)


class SnapshotTests(EventWaitTestCase):
    def snapshot_config(self) -> dict:
        return {
            "request": {"kind": "req", "channel": "workflow.get", "body": {"workflowId": "wf-1"}},
            "request_id_field": "reqId",
            "response_match_fields": {"kind": "res"},
            "error_match_fields": {"kind": "err"},
            "body_path": ["body"],
        }

    def answer_with(self, producer: Producer, body: dict, kind: str = "res", delay: float = 0.0):
        def handler(peer, record):
            def reply():
                if delay:
                    time.sleep(delay)
                payload = {"kind": kind, "channel": record["channel"], "reqId": record["reqId"]}
                if kind == "err":
                    payload["code"] = "NO_HANDLER"
                else:
                    payload["body"] = body
                producer.send_to(peer, frame(json.dumps(payload).encode("utf-8")))

            threading.Thread(target=reply, daemon=True).start()

        producer.on_request = handler

    def test_completion_before_attach_is_recovered_by_the_single_snapshot(self):
        producer = self.producer()
        self.answer_with(producer, {"workflowId": "wf-1", "status": "completed", "eventId": "old"})
        spec = self.socket_spec(
            "snap-before", "wf-1", producer.path, snapshot=self.snapshot_config()
        )
        wait = self.start(spec)
        wait.read_armed()

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "matched")
        self.assertEqual(receipt["matched_via"], "snapshot")
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["source_requests_sent"], 1)
        self.assertEqual(producer.request_count(), 1)

    def test_completion_during_the_snapshot_window_is_matched_from_the_stream(self):
        producer = self.producer()
        self.answer_with(
            producer, {"workflowId": "wf-1", "status": "running", "eventId": "stale"}, delay=1.0
        )
        spec = self.socket_spec(
            "snap-during", "wf-1", producer.path, snapshot=self.snapshot_config()
        )
        wait = self.start(spec)
        wait.read_armed()
        self.assertTrue(wait_until(lambda: producer.request_count() == 1))

        producer.emit({"workflowId": "wf-1", "status": "completed", "eventId": "live"})
        receipt = wait.finish()

        self.assertEqual(receipt["outcome"], "matched")
        self.assertEqual(receipt["matched_via"], "stream")
        self.assertEqual(receipt["events_during_snapshot"], 1)
        self.assertEqual(producer.request_count(), 1)

    def test_snapshot_is_sent_once_and_nothing_polls_after_it(self):
        producer = self.producer()
        self.answer_with(producer, {"workflowId": "wf-1", "status": "running", "eventId": "s0"})
        spec = self.socket_spec(
            "snap-once", "wf-1", producer.path, snapshot=self.snapshot_config(), deadline_seconds=3.0
        )
        wait = self.start(spec)
        wait.read_armed()
        self.assertTrue(wait_until(lambda: producer.request_count() == 1))
        before = producer.inbound_bytes

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "timeout")
        self.assertEqual(receipt["source_requests_sent"], 1)
        self.assertEqual(producer.request_count(), 1, "a second request means polling")
        self.assertEqual(producer.inbound_bytes, before, "no bytes after the one snapshot")

    def test_a_rejected_snapshot_is_an_explicit_source_error(self):
        producer = self.producer()
        self.answer_with(producer, {}, kind="err")
        spec = self.socket_spec("snap-err", "wf-1", producer.path, snapshot=self.snapshot_config())
        wait = self.start(spec)
        wait.read_armed()

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "source_error")
        self.assertEqual(receipt["error_code"], "snapshot_rejected")
        self.assertEqual(receipt["exit_code"], wait_event.EXIT_SOURCE_ERROR)
        self.assertFalse(receipt["event_received"])

    def test_completion_before_arming_without_a_snapshot_times_out_explicitly(self):
        producer = self.producer()
        spec = self.socket_spec("no-snap", "wf-1", producer.path, deadline_seconds=2.0)
        producer.emit(
            {"workflowId": "wf-1", "status": "completed", "eventId": "gone"}, expect_peers=0
        )
        wait = self.start(spec)
        wait.read_armed()

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "timeout")
        self.assertFalse(receipt["event_received"])
        self.assertEqual(receipt["source_requests_sent"], 0)

    def test_a_source_without_a_snapshot_is_never_written_to(self):
        producer = self.producer()
        spec = self.socket_spec("read-only", "wf-1", producer.path)
        wait = self.start(spec)
        wait.read_armed()
        producer.emit({"workflowId": "wf-1", "status": "completed", "eventId": "r1"})
        wait.finish()

        self.assertEqual(producer.inbound_bytes, 0)
        self.assertEqual(producer.request_count(), 0)


class StreamFailureTests(EventWaitTestCase):
    def test_a_malformed_frame_fails_closed_without_echoing_the_payload(self):
        producer = self.producer()
        spec = self.socket_spec("malformed", "wf-1", producer.path, deadline_seconds=5.0)
        wait = self.start(spec)
        wait.read_armed()
        producer.send_raw(frame(b"{not json SUPERSECRET"))

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "source_error")
        self.assertEqual(receipt["error_code"], "invalid_json")
        self.assertEqual(receipt["exit_code"], wait_event.EXIT_SOURCE_ERROR)
        self.assertNotIn("SUPERSECRET", json.dumps(receipt))
        self.assertNotIn("SUPERSECRET", wait.stderr)

    def test_an_oversize_frame_is_refused_before_it_is_read(self):
        producer = self.producer()
        spec = self.socket_spec(
            "oversize",
            "wf-1",
            producer.path,
            deadline_seconds=5.0,
            limits={"max_frame_bytes": 1024, "max_record_bytes": 512},
        )
        wait = self.start(spec)
        wait.read_armed()
        producer.send_raw(struct.pack(">I", 5_000_000) + b"x" * 100)

        receipt = wait.finish()
        self.assertEqual(receipt["error_code"], "frame_too_large")
        self.assertEqual(receipt["exit_code"], wait_event.EXIT_SOURCE_ERROR)

    def test_a_truncated_frame_at_disconnect_is_reported_as_truncated(self):
        producer = self.producer()
        spec = self.socket_spec("truncated", "wf-1", producer.path, deadline_seconds=8.0)
        wait = self.start(spec)
        wait.read_armed()
        producer.send_raw(struct.pack(">I", 400) + b'{"kind":"pub"')
        time.sleep(0.2)
        producer.drop_peers(expect=1)

        receipt = wait.finish()
        self.assertEqual(receipt["error_code"], "truncated_frame")
        self.assertFalse(receipt["event_received"])

    def test_a_clean_disconnect_before_any_match_is_a_source_error(self):
        producer = self.producer()
        spec = self.socket_spec("eof", "wf-1", producer.path, deadline_seconds=8.0)
        wait = self.start(spec)
        wait.read_armed()
        self.assertTrue(producer.wait_for_peers(1))
        time.sleep(0.2)
        producer.drop_peers(expect=1)

        receipt = wait.finish()
        self.assertEqual(receipt["error_code"], "source_closed")
        self.assertEqual(receipt["exit_code"], wait_event.EXIT_SOURCE_ERROR)
        self.assertFalse(receipt["event_received"])
        self.assertFalse(receipt["wake_delivered"])

    def test_a_missing_socket_reports_an_unarmed_source(self):
        spec = self.socket_spec(
            "no-socket", "wf-1", os.path.join(self.dir, "absent.sock"), deadline_seconds=5.0
        )
        wait = self.start(spec)
        armed = wait.read_armed()

        self.assertFalse(armed["source_ready"])
        self.assertEqual(armed["error_code"], "connect_failed")
        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "source_error")

    def test_a_matched_event_larger_than_the_record_limit_is_truncated(self):
        producer = self.producer()
        spec = self.socket_spec(
            "excerpt",
            "wf-1",
            producer.path,
            limits={"max_frame_bytes": 1024 * 1024, "max_record_bytes": 200},
        )
        wait = self.start(spec)
        wait.read_armed()
        producer.emit(
            {"workflowId": "wf-1", "status": "completed", "eventId": "big", "log": "y" * 5000}
        )

        receipt = wait.finish()
        self.assertTrue(receipt["event_truncated"])
        self.assertLessEqual(len(receipt["event_excerpt"].encode("utf-8")), 200)
        self.assertEqual(receipt["status"], "completed")


class JsonStreamTests(EventWaitTestCase):
    def stream_spec(self, wait_id: str, subject: str, script: str, **overrides) -> dict:
        spec = {
            "wait_id": wait_id,
            "deadline_seconds": overrides.pop("deadline_seconds", 15.0),
            "receipt_path": os.path.join(self.dir, f"{wait_id}.receipt.json"),
            "source": {
                "kind": "json_stream",
                "command": [sys.executable, "-u", "-c", script],
                "framing": {"kind": "lines"},
            },
            "match": {
                "subject_path": ["workflowId"],
                "subject": subject,
                "status_path": ["status"],
                "terminal_statuses": ["completed", "failed"],
            },
            "wake": {"mode": "none"},
        }
        spec.update(overrides)
        return spec

    def test_a_line_delimited_child_process_stream_is_consumed_to_a_match(self):
        script = (
            "import json,time,sys\n"
            "for row in [{'workflowId':'wf-x','status':'running'},"
            "{'workflowId':'wf-1','status':'running'},"
            "{'workflowId':'wf-1','status':'completed'}]:\n"
            "    print(json.dumps(row)); time.sleep(0.05)\n"
            "time.sleep(30)\n"
        )
        spec = self.stream_spec("stream-ok", "wf-1", script)
        wait = self.start(spec)
        self.assertTrue(wait.read_armed()["source_ready"])

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "matched")
        self.assertEqual(receipt["matched_via"], "stream")
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(receipt["source_requests_sent"], 0)

    def test_a_stream_that_ends_before_the_match_is_a_source_error(self):
        script = "import json\nprint(json.dumps({'workflowId':'wf-1','status':'running'}))\n"
        spec = self.stream_spec("stream-eof", "wf-1", script)
        wait = self.start(spec)
        wait.read_armed()

        receipt = wait.finish()
        self.assertEqual(receipt["error_code"], "source_closed")
        self.assertFalse(receipt["event_received"])

    def test_a_stream_source_may_not_declare_a_snapshot(self):
        spec = self.stream_spec("stream-snap", "wf-1", "pass")
        spec["source"]["snapshot"] = {"request": {}}
        wait = self.start(spec)

        receipt = wait.finish()
        self.assertEqual(receipt["outcome"], "spec_invalid")
        self.assertEqual(receipt["error_code"], "spec_unknown_key")
        self.assertEqual(wait.process.returncode, wait_event.EXIT_SPEC_INVALID)


class WakeTests(EventWaitTestCase):
    def test_no_declared_wake_reports_the_mechanism_as_unsupported(self):
        producer = self.producer()
        spec = self.socket_spec("wake-none", "wf-1", producer.path)
        wait = self.start(spec)
        armed = wait.read_armed()
        self.assertFalse(armed["callback_ready"])
        self.assertEqual(armed["callback_status"], "session_wake_unsupported")

        producer.emit({"workflowId": "wf-1", "status": "completed", "eventId": "w1"})
        receipt = wait.finish()
        self.assertTrue(receipt["event_received"])
        self.assertFalse(receipt["wake_delivered"])
        self.assertEqual(receipt["wake_status"], "session_wake_unsupported")
        self.assertEqual(receipt["exit_code"], 0)

    def test_a_delivered_wake_runs_once_and_sees_only_spec_derived_values(self):
        producer = self.producer()
        marker = os.path.join(self.dir, "woke.json")
        wake_script = os.path.join(self.dir, "wake.py")
        with open(wake_script, "w", encoding="utf-8") as handle:
            handle.write(
                "import json,os,sys\n"
                f"json.dump({{'id':os.environ['EVENT_WAIT_ID'],"
                "'subject':os.environ['EVENT_WAIT_SUBJECT'],"
                "'status':os.environ['EVENT_WAIT_STATUS'],"
                "'owner':os.environ['EVENT_WAIT_OWNER'],"
                f"'argv':sys.argv[1:]}}, open({marker!r},'w'))\n"
            )
        spec = self.socket_spec(
            "wake-ok",
            "wf-1",
            producer.path,
            wake={
                "mode": "command",
                "owner": "session-owner-1",
                "argv": [sys.executable, wake_script],
                "ready_argv": [sys.executable, "-c", "pass"],
                "append_receipt_path": True,
            },
        )
        wait = self.start(spec)
        armed = wait.read_armed()
        self.assertTrue(armed["source_ready"])
        self.assertTrue(armed["callback_ready"])
        self.assertEqual(armed["callback_status"], "ready")

        producer.emit(
            {"workflowId": "wf-1", "status": "completed", "eventId": "w2", "secret": "SUPERSECRET"}
        )
        receipt = wait.finish()

        self.assertTrue(receipt["wake_delivered"])
        self.assertEqual(receipt["wake_status"], "delivered")
        self.assertEqual(receipt["exit_code"], 0)
        with open(marker, encoding="utf-8") as handle:
            seen = json.load(handle)
        self.assertEqual(seen["id"], "wake-ok")
        self.assertEqual(seen["subject"], "wf-1")
        self.assertEqual(seen["status"], "completed")
        self.assertEqual(seen["owner"], "session-owner-1")
        self.assertEqual(seen["argv"], [spec["receipt_path"]])
        self.assertNotIn("SUPERSECRET", json.dumps(seen))

    def test_a_failing_wake_keeps_the_event_but_reports_undelivered(self):
        producer = self.producer()
        spec = self.socket_spec(
            "wake-fail",
            "wf-1",
            producer.path,
            wake={
                "mode": "command",
                "owner": "session-owner-1",
                "argv": [sys.executable, "-c", "import sys; sys.exit(9)"],
            },
        )
        wait = self.start(spec)
        armed = wait.read_armed()
        self.assertFalse(armed["callback_ready"])
        self.assertEqual(armed["callback_status"], "unproven")

        producer.emit({"workflowId": "wf-1", "status": "failed", "eventId": "w3"})
        receipt = wait.finish()

        self.assertTrue(receipt["event_received"])
        self.assertEqual(receipt["status"], "failed")
        self.assertFalse(receipt["wake_delivered"])
        self.assertEqual(receipt["wake_status"], "failed")
        self.assertEqual(receipt["exit_code"], wait_event.EXIT_CALLBACK_FAILED)
        self.assertEqual(wait.process.returncode, wait_event.EXIT_CALLBACK_FAILED)
        self.assertIn("says nothing about the watched job", wait.stderr)

    def test_a_failing_readiness_probe_arms_the_source_but_not_the_callback(self):
        producer = self.producer()
        spec = self.socket_spec(
            "wake-unready",
            "wf-1",
            producer.path,
            deadline_seconds=3.0,
            wake={
                "mode": "command",
                "owner": "session-owner-1",
                "argv": [sys.executable, "-c", "pass"],
                "ready_argv": [sys.executable, "-c", "import sys; sys.exit(3)"],
            },
        )
        wait = self.start(spec)
        armed = wait.read_armed()

        self.assertTrue(armed["source_ready"])
        self.assertFalse(armed["callback_ready"])
        self.assertEqual(armed["callback_status"], "not_ready")
        wait.finish()


class ClaimTests(EventWaitTestCase):
    def test_a_reused_wait_id_is_refused(self):
        producer = self.producer()
        first = self.socket_spec("reused", "wf-1", producer.path)
        wait_one = self.start(first)
        wait_one.read_armed()

        second = dict(first)
        second["receipt_path"] = os.path.join(self.dir, "other.receipt.json")
        wait_two = self.start(second)
        receipt = wait_two.finish()

        self.assertEqual(receipt["outcome"], "claim_conflict")
        self.assertEqual(receipt["error_code"], "wait_id_in_use")
        self.assertEqual(wait_two.process.returncode, wait_event.EXIT_CLAIM_CONFLICT)
        self.assertFalse(os.path.exists(second["receipt_path"]))

    def test_a_reused_receipt_path_is_refused_and_leaves_the_first_claim_intact(self):
        producer = self.producer()
        first = self.socket_spec("path-one", "wf-1", producer.path)
        wait_one = self.start(first)
        wait_one.read_armed()

        second = self.socket_spec("path-two", "wf-2", producer.path)
        second["receipt_path"] = first["receipt_path"]
        wait_two = self.start(second)
        receipt = wait_two.finish()

        self.assertEqual(receipt["error_code"], "receipt_path_in_use")
        self.assertEqual(wait_two.process.returncode, wait_event.EXIT_CLAIM_CONFLICT)
        self.assertFalse(os.path.exists(os.path.join(self.dir, "path-two.claim")))
        self.assertTrue(os.path.exists(os.path.join(self.dir, "path-one.claim")))

    def test_a_shared_writable_receipt_directory_is_refused(self):
        producer = self.producer()
        shared = os.path.join(self.dir, "shared")
        os.mkdir(shared, 0o777)
        os.chmod(shared, 0o777)
        spec = self.socket_spec("shared-dir", "wf-1", producer.path)
        spec["receipt_path"] = os.path.join(shared, "r.json")
        wait = self.start(spec)
        receipt = wait.finish()

        self.assertEqual(receipt["error_code"], "receipt_dir_not_private")
        self.assertEqual(wait.process.returncode, wait_event.EXIT_CLAIM_CONFLICT)

    def test_a_shared_claim_directory_makes_wait_ids_exclusive_across_directories(self):
        producer = self.producer()
        claims = os.path.join(self.dir, "claims")
        os.mkdir(claims, 0o700)
        left = os.path.join(self.dir, "left")
        right = os.path.join(self.dir, "right")
        os.mkdir(left, 0o700)
        os.mkdir(right, 0o700)

        first = self.socket_spec("cross", "wf-1", producer.path)
        first["receipt_path"] = os.path.join(left, "r.json")
        first["claim_dir"] = claims
        wait_one = self.start(first)
        wait_one.read_armed()

        second = self.socket_spec("cross", "wf-1", producer.path)
        second["receipt_path"] = os.path.join(right, "r.json")
        second["claim_dir"] = claims
        wait_two = self.start(second)
        receipt = wait_two.finish()
        self.assertEqual(receipt["error_code"], "wait_id_in_use")


class SpecValidationTests(unittest.TestCase):
    def test_unknown_keys_and_bad_types_are_refused_with_stable_codes(self):
        base = {
            "wait_id": "ok",
            "deadline_seconds": 1,
            "receipt_path": "/tmp/r.json",
            "source": {"kind": "json_stream", "path": "/tmp/f", "framing": {"kind": "lines"}},
            "match": {
                "subject_path": ["id"],
                "subject": "a",
                "status_path": ["status"],
                "terminal_statuses": ["done"],
            },
        }
        self.assertEqual(wait_event.parse_spec(base)["wait_id"], "ok")

        with self.assertRaises(wait_event.SpecError) as caught:
            wait_event.parse_spec({**base, "extra": 1})
        self.assertEqual(caught.exception.code, "spec_unknown_key")

        with self.assertRaises(wait_event.SpecError) as caught:
            wait_event.parse_spec({**base, "receipt_path": "relative.json"})
        self.assertEqual(caught.exception.code, "spec_path")

        with self.assertRaises(wait_event.SpecError) as caught:
            wait_event.parse_spec({**base, "wait_id": "bad id/../x"})
        self.assertEqual(caught.exception.code, "spec_range")

        with self.assertRaises(wait_event.SpecError) as caught:
            wait_event.parse_spec({**base, "deadline_seconds": 10 ** 9})
        self.assertEqual(caught.exception.code, "spec_range")

    def test_a_source_must_name_exactly_one_stream_origin(self):
        both = {
            "kind": "json_stream",
            "command": ["true"],
            "path": "/tmp/f",
            "framing": {"kind": "lines"},
        }
        with self.assertRaises(wait_event.SpecError) as caught:
            wait_event.parse_source(both)
        self.assertEqual(caught.exception.code, "spec_range")

    def test_a_snapshot_must_say_how_to_recognise_its_own_reply(self):
        with self.assertRaises(wait_event.SpecError) as caught:
            wait_event.parse_snapshot({"request": {"kind": "req"}}, "source.snapshot")
        self.assertEqual(caught.exception.code, "spec_range")

    def test_the_decoder_refuses_a_frame_header_over_the_limit(self):
        decoder = wait_event.Decoder(
            {"kind": "length_prefix", "prefix_bytes": 4, "byte_order": "big"}, 16
        )
        with self.assertRaises(wait_event.SourceError) as caught:
            decoder.feed(struct.pack(">I", 999) + b"x")
        self.assertEqual(caught.exception.code, "frame_too_large")
        self.assertNotIn("x", caught.exception.detail)


if __name__ == "__main__":
    unittest.main(verbosity=2)
