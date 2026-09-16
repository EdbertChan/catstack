"""Black-box subprocess/socket contract tests; synthetic protocol, not live CI."""
import copy
import json
import os
from pathlib import Path
import queue
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import unittest

RUNNER = Path(__file__).resolve().parents[1] / 'scripts/wait_event.py'


def frame(value):
    raw = json.dumps(value).encode()
    return struct.pack('!I', len(raw)) + raw


def receive(sock):
    def exact(n):
        parts = bytearray()
        while len(parts) < n:
            data = sock.recv(n - len(parts))
            if not data:
                raise EOFError
            parts.extend(data)
        return bytes(parts)
    return json.loads(exact(struct.unpack('!I', exact(4))[0]))


def event(subject='A', status='done', identity='e1', **extra):
    return dict(channel='jobs', subject=subject, attempt='v1', id=identity, status=status, **extra)


def mapping():
    return {'channel': {'path': ['channel'], 'equals': 'jobs'},
            'subject': [{'path': ['subject'], 'equals': 'A'},
                        {'path': ['attempt'], 'equals': 'v1'}],
            'identity_paths': [['id']], 'status_path': ['status'],
            'terminal': {'done': 'success', 'failed': 'failure', 'cancelled': 'cancelled'}}


class Peer:
    def __init__(self, sock):
        self.sock = sock
        self.lock = threading.Lock()

    def send(self, value):
        self.raw(frame(value))

    def raw(self, value):
        with self.lock:
            self.sock.sendall(value)

    def shutdown(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


class Server:
    def __init__(self, endpoint, handler=None, attached=None):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.bind(str(endpoint))
        self.sock.listen(64)
        self.handler = handler
        self.attached = attached
        self.peers = []
        self.accepted = queue.Queue()
        self.requests = []
        self.errors = []
        self.threads = []
        self.stopped = False
        self.thread = threading.Thread(target=self.accept, daemon=True)
        self.thread.start()

    def accept(self):
        while not self.stopped:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            if self.stopped:
                conn.close()
                return
            peer = Peer(conn)
            self.peers.append(peer)
            self.accepted.put(peer)
            thread = threading.Thread(target=self.read, args=(peer,), daemon=True)
            self.threads.append(thread)
            thread.start()

    def read(self, peer):
        try:
            if self.attached:
                self.attached(peer)
            while True:
                message = receive(peer.sock)
                self.requests.append(message)
                if self.handler:
                    self.handler(peer, message)
        except (EOFError, ConnectionResetError, BrokenPipeError):
            return
        except Exception as exc:
            if not self.stopped:
                self.errors.append(type(exc).__name__)

    def broadcast(self, message):
        for peer in self.peers:
            try:
                peer.send(message)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def close(self):
        self.stopped = True
        for peer in self.peers:
            peer.shutdown()
        # Wake accept without a timeout loop.
        wake = socket.socket(socket.AF_UNIX)
        try:
            wake.connect(self.sock.getsockname())
        finally:
            wake.close()
        self.thread.join(2)
        self.sock.close()
        for thread in self.threads:
            thread.join(2)
        for peer in self.peers:
            peer.sock.close()


class Child:
    def __init__(self, spec, filename):
        filename.write_text(json.dumps(spec))
        self.spec = spec
        self.proc = subprocess.Popen([sys.executable, str(RUNNER), 'wait', '--spec', str(filename)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.output = []
        self.messages = queue.Queue()
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        for line in self.proc.stdout:
            record = json.loads(line)
            self.output.append(record)
            self.messages.put(record)

    def ready(self, kind='callback_ready'):
        while True:
            record = self.messages.get(timeout=6)
            if record.get('type') == kind:
                return record
            if 'result' in record:
                raise AssertionError(record)

    def finish(self):
        code = self.proc.wait(timeout=8)
        self.thread.join(2)
        error = self.proc.stderr.read().decode()
        return code, error

    def receipt(self):
        return json.loads(Path(self.spec['receipt']).read_text())

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2)
        self.thread.join(2)
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            if not stream.closed:
                stream.close()


class EventWaitTests(unittest.TestCase):
    def setUp(self):
        # Short Unix paths are necessary on macOS even in deeply nested worktrees.
        self.temp = tempfile.TemporaryDirectory(prefix='ew-test-', dir='/tmp')
        self.root = Path(self.temp.name)
        self.registry = self.root / 'receipts'
        self.registry.mkdir(mode=0o700)
        self.children = []
        self.servers = []
        self.callback = self.server('callback', handler=self.callback_handler)

    def tearDown(self):
        for child in self.children:
            child.close()
        for server in self.servers:
            server.close()
            self.assertEqual(server.errors, [])
        self.temp.cleanup()

    @staticmethod
    def callback_handler(peer, message):
        base = {key: message[key] for key in ('wait_id', 'owner', 'nonce')}
        if message['type'] == 'register':
            peer.send(base | {'type': 'callback_ready'})
        else:
            peer.send(base | {'type': 'wake_delivered'})

    def server(self, name='source', **kwargs):
        server = Server(self.root / name, **kwargs)
        self.servers.append(server)
        return server

    def spec(self, name='A', seconds=5, snapshot=False, mode='acknowledged'):
        src = {'identity': 'test-source', 'transport': 'unix', 'path': str(self.root / 'source'),
               'read_only': True, 'event': mapping()}
        src['event']['subject'][0]['equals'] = name
        if snapshot:
            src['snapshot'] = {'request': {'method': 'snapshot', 'subject': name, 'id': name},
                               'response': [{'path': ['reply'], 'equals': name}],
                               'error': [{'path': ['error_for'], 'equals': name}],
                               'record_path': ['record'], 'mapping': copy.deepcopy(src['event'])}
        wake = {'mode': mode, 'owner': 'test-parent'}
        if mode != 'unsupported':
            wake['socket'] = str(self.root / 'callback')
        return {'wait_id': name, 'registry': str(self.registry),
                'receipt': str(self.registry / name / 'terminal.json'),
                'deadline': time.time() + seconds, 'source': src, 'wake': wake}

    def launch(self, spec=None):
        child = Child(spec or self.spec(), self.root / f'spec-{len(self.children)}.json')
        self.children.append(child)
        return child

    def assert_result(self, child, result, code=0, outcome=None):
        actual_code, stderr = child.finish()
        self.assertEqual((actual_code, stderr), (code, ''))
        receipt = child.receipt()
        self.assertEqual(receipt['result'], result)
        self.assertEqual(receipt['target_outcome'], outcome)
        self.assertLess(len(Path(child.spec['receipt']).read_bytes()), 4096)
        self.assertEqual(sum('result' in row for row in child.output), 1)
        self.assertEqual(os.stat(Path(child.spec['receipt'])).st_mode & 0o777, 0o600)
        return receipt

    def test_twenty_concurrent_reverse_routing_no_polling(self):
        def handler(peer, msg):
            peer.send({'reply': msg['id'], 'record': event(msg['subject'], 'running', 'snap')})
        source = self.server(handler=handler)
        children = [self.launch(self.spec(f'w{i}', snapshot=True, seconds=15)) for i in range(20)]
        for child in children:
            child.ready()
        # Events may race the initial requests; consumers must reconcile both orders.
        completed = set()
        digests = set()
        for child in reversed(children):
            source.broadcast(event(child.spec['wait_id'], identity='complete-' + child.spec['wait_id']))
            receipt = self.assert_result(child, 'wake_delivered', outcome='success')
            self.assertEqual(receipt['snapshot_requests'], 1)
            self.assertEqual(receipt['wait_id'], child.spec['wait_id'])
            completed.add(child)
            digests.add(receipt['event_digest'])
            for pending in set(children) - completed:
                self.assertIsNone(pending.proc.poll(), 'another wait completed without its event')
        self.assertEqual(len(digests), 20)
        self.assertEqual(len(source.requests), 20)
        self.assertEqual({m['method'] for m in source.requests}, {'snapshot'})
        print('PROOF concurrent_waits=20 reverse_completion=true initial_status_requests=20 post_start_status_requests=0')

    def test_unrelated_duplicates_wrong_source_channel_target_attempt(self):
        source = self.server()
        child = self.launch()
        child.ready()
        source.broadcast(event(status='running', identity='same'))
        source.broadcast(event(status='running', identity='same'))
        source.broadcast(event(subject='B'))
        wrong = event(); wrong['channel'] = 'other'; source.broadcast(wrong)
        wrong = event(); wrong['attempt'] = 'v0'; source.broadcast(wrong)
        # Independent socket cannot route into this source's subscription.
        other = self.server('other-source')
        other_spec = self.spec('other')
        other_spec['source']['path'] = str(self.root / 'other-source')
        other_spec['source']['event']['subject'][0]['equals'] = 'A'
        other_child = self.launch(other_spec)
        other_child.ready()
        other.broadcast(event())
        self.assert_result(other_child, 'wake_delivered', outcome='success')
        self.assertIsNone(child.proc.poll())
        source.broadcast(event(identity='correct'))
        receipt = self.assert_result(child, 'wake_delivered', outcome='success')
        self.assertEqual(receipt['origin'], 'stream')
        self.assertEqual(source.requests, [])

    def test_completion_before_attach_one_snapshot(self):
        source = self.server(handler=lambda p, m: p.send({'reply': m['id'], 'record': event(identity='snapshot')}))
        child = self.launch(self.spec(snapshot=True))
        receipt = self.assert_result(child, 'wake_delivered', outcome='success')
        self.assertEqual(receipt['origin'], 'snapshot')
        self.assertEqual(len(source.requests), 1)

    def test_completion_during_snapshot_beats_stale_reply(self):
        def handler(peer, msg):
            peer.send(event())
            peer.send(event())
            peer.send({'reply': msg['id'], 'record': event(status='running', identity='old')})
        source = self.server(handler=handler)
        child = self.launch(self.spec(snapshot=True))
        receipt = self.assert_result(child, 'wake_delivered', outcome='success')
        self.assertEqual(receipt['origin'], 'stream')
        self.assertEqual(len(source.requests), 1)

    def test_immediate_completion_before_callback_ready(self):
        self.server(attached=lambda p: p.send(event()))
        child = self.launch()
        self.assert_result(child, 'wake_delivered', outcome='success')
        self.assertEqual([r.get('type') for r in child.output[:2]], ['source_ready', 'callback_ready'])

    def test_subscribe_ack_buffers_early_event_before_snapshot(self):
        def handler(peer, msg):
            if msg['method'] == 'subscribe':
                peer.send(event())
                peer.send({'subscribed': 'A'})
            else:
                peer.send({'reply': 'A', 'record': event(status='running', identity='old')})
        source = self.server(handler=handler)
        spec = self.spec(snapshot=True)
        spec['source']['subscribe'] = {'request': {'method': 'subscribe', 'subject': 'A'},
                                       'response': [{'path': ['subscribed'], 'equals': 'A'}]}
        child = self.launch(spec)
        self.assert_result(child, 'wake_delivered', outcome='success')
        self.assertEqual([m['method'] for m in source.requests], ['subscribe', 'snapshot'])
        self.assertEqual(child.output[0]['scope'], 'subscription_ack')

    def test_timeout_under_continuous_unrelated_traffic(self):
        stop = threading.Event()
        def flood(peer):
            while not stop.is_set():
                peer.send(event(subject='unrelated'))
        source = self.server(attached=flood)
        try:
            start = time.monotonic()
            child = self.launch(self.spec(seconds=0.45))
            receipt = self.assert_result(child, 'timeout', 1)
            self.assertFalse(receipt['event_received'])
            self.assertLess(time.monotonic() - start, 2)
            self.assertEqual(source.requests, [])
        finally:
            stop.set()

    def test_cancellation_a_leaves_b_alive(self):
        source = self.server()
        a = self.launch(); b = self.launch(self.spec('B'))
        a.ready(); b.ready()
        a.proc.terminate()
        self.assert_result(a, 'cancelled', 1)
        self.assertIsNone(b.proc.poll())
        source.broadcast(event('B'))
        self.assert_result(b, 'wake_delivered', outcome='success')
        self.assertTrue((self.root / 'source').exists())
        self.assertEqual(source.requests, [])

    def test_malformed_oversize_truncated_frames_and_eof(self):
        cases = [(struct.pack('!I', 1) + b'{', 'malformed_json'),
                 (struct.pack('!I', 65537), 'oversize_frame'),
                 (b'\x00\x01', 'truncated_stream'),
                 (struct.pack('!I', 20) + b'{}', 'truncated_stream'),
                 (b'', 'source_eof'),
                 (struct.pack('!I', 0), 'oversize_frame')]
        source = self.server()
        for i, (raw, expected) in enumerate(cases):
            with self.subTest(expected=expected, case=i):
                child = self.launch(self.spec(f'bad{i}'))
                peer = source.accepted.get(timeout=5)
                child.ready()
                peer.raw(raw); peer.shutdown()
                self.assert_result(child, expected, 1)

    def test_fragmented_frame(self):
        source = self.server()
        child = self.launch()
        peer = source.accepted.get(timeout=5)
        child.ready()
        for byte in frame(event()):
            peer.raw(bytes([byte]))
        self.assert_result(child, 'wake_delivered', outcome='success')

    def test_reused_id_and_receipt_path_never_overwrite(self):
        source = self.server()
        first = self.launch(); first.ready()
        duplicate = self.launch()
        code, error = duplicate.finish()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(error), {'error': 'ownership_conflict'})
        alias = self.spec('B'); alias['receipt'] = first.spec['receipt']
        conflict = self.launch(alias)
        self.assertEqual(conflict.finish()[0], 2)
        source.broadcast(event())
        self.assert_result(first, 'wake_delivered', outcome='success')
        saved = Path(first.spec['receipt']).read_bytes()
        again = self.launch()
        self.assertEqual(again.finish()[0], 2)
        self.assertEqual(Path(first.spec['receipt']).read_bytes(), saved)

    def test_simultaneous_same_id_claim(self):
        source = self.server()
        a = self.launch(); b = self.launch()
        # Exactly one owns the directory; only it connects. Reading its socket is blocking.
        source.accepted.get(timeout=5)
        source.broadcast(event())
        results = [a.finish(), b.finish()]
        self.assertEqual(sorted(r[0] for r in results), [0, 2])
        self.assertEqual(len(source.peers), 1)

    def test_read_only_source_and_no_producer_commands(self):
        source = self.server()
        child = self.launch()
        child.ready()
        source.broadcast(event(secret='$(touch should-not-exist); `danger`'))
        self.assert_result(child, 'wake_delivered', outcome='success')
        self.assertEqual(source.requests, [])
        self.assertNotIn('danger', Path(child.spec['receipt']).read_text())
        self.assertTrue((self.root / 'source').is_socket())

    def test_source_request_failure_is_not_target_failure(self):
        self.server(handler=lambda p, m: p.send({'error_for': 'A', 'secret': 'do-not-print'}))
        child = self.launch(self.spec(snapshot=True))
        receipt = self.assert_result(child, 'source_request_failed', 1)
        self.assertFalse(receipt['event_received'])
        self.assertNotIn('do-not-print', str(child.output))

    def test_callback_unsupported_still_records_event(self):
        source = self.server()
        child = self.launch(self.spec(mode='unsupported'))
        child.ready('source_ready'); source.broadcast(event())
        receipt = self.assert_result(child, 'session_wake_unsupported', 1, 'success')
        self.assertTrue(receipt['event_received'])
        self.assertFalse(receipt['callback_ready'])
        self.assertFalse(receipt['wake_delivered'])

    def test_callback_bad_ready_ack(self):
        self.server()
        self.callback.handler = lambda p, m: p.send({'type': 'callback_ready', 'wait_id': 'wrong'})
        child = self.launch()
        receipt = self.assert_result(child, 'callback_failed', 1)
        self.assertFalse(receipt['callback_ready'])

    def test_callback_delivery_failure_retains_event(self):
        self.server(attached=lambda p: p.send(event()))
        def handler(peer, message):
            if message['type'] == 'register':
                self.callback_handler(peer, message)
            else:
                peer.shutdown()
        self.callback.handler = handler
        child = self.launch()
        receipt = self.assert_result(child, 'callback_failed', 1, 'success')
        self.assertTrue(receipt['event_received'])
        self.assertFalse(receipt['wake_delivered'])

    def test_native_completion_requires_separate_owner_ack(self):
        self.server(attached=lambda p: p.send(event()))
        self.callback.handler = lambda p, m: self.callback_handler(p, m) if m['type'] == 'register' else None
        child = self.launch(self.spec(mode='native'))
        receipt = self.assert_result(child, 'wake_pending', outcome='success')
        self.assertFalse(receipt['wake_delivered'])
        ack_path = Path(child.spec['receipt']).with_name('wake-delivered.json')
        self.assertFalse(ack_path.exists())
        args = [sys.executable, str(RUNNER), 'ack-wake', '--receipt', child.spec['receipt'],
                '--owner', 'test-parent', '--nonce', receipt['nonce']]
        wrong = args.copy(); wrong[-1] = 'wrong'
        self.assertNotEqual(subprocess.run(wrong, capture_output=True).returncode, 0)
        ack = subprocess.run(args, capture_output=True, text=True)
        self.assertEqual(ack.returncode, 0, ack.stderr)
        self.assertTrue(json.loads(ack_path.read_text())['wake_delivered'])
        self.assertEqual(json.loads(Path(child.spec['receipt']).read_text()), receipt)
        self.assertNotEqual(subprocess.run(args, capture_output=True).returncode, 0)

    def test_target_failure_is_separate_from_listener_exit(self):
        self.server(attached=lambda p: p.send(event(status='failed')))
        self.assert_result(self.launch(), 'wake_delivered', outcome='failure')

    def test_json_lines_pipe_and_oversize_record(self):
        for name, raw, expected, code, outcome in [
            ('A', json.dumps(event()).encode() + b'\n', 'wake_delivered', 0, 'success'),
            ('B', b'x' * 65538, 'oversize_record', 1, None),
            ('C', b'{"broken":', 'truncated_stream', 1, None),
            ('D', b'{"x":NaN}\n', 'malformed_json', 1, None),
            ('E', b'{"x":1,"x":2}\n', 'malformed_json', 1, None)]:
            with self.subTest(name=name):
                spec = self.spec(name)
                spec['source']['transport'] = 'stdin'; del spec['source']['path']
                child = self.launch(spec)
                child.ready()
                try:
                    child.proc.stdin.write(raw); child.proc.stdin.flush()
                except BrokenPipeError:
                    pass
                child.proc.stdin.close()
                self.assert_result(child, expected, code, outcome)

    def test_validation_rejects_unknown_expressions_and_nonprivate_registry(self):
        spec = self.spec(); spec['source']['event']['expression'] = 'arbitrary()'
        child = self.launch(spec)
        self.assertEqual(child.finish()[0], 2)
        self.assertFalse(Path(spec['receipt']).parent.exists())
        self.registry.chmod(0o755)
        child = self.launch()
        code, error = child.finish()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(error), {'error': 'registry_not_private'})

    def test_deadline_before_start_still_has_terminal_receipt(self):
        child = self.launch(self.spec(seconds=-1))
        receipt = self.assert_result(child, 'timeout', 1)
        self.assertFalse(receipt['source_ready'])

    def test_callback_handshake_deadline_and_cancellation(self):
        self.server()
        self.callback.handler = lambda p, m: None
        child = self.launch(self.spec(seconds=0.35))
        self.assert_result(child, 'timeout', 1)
        child = self.launch(self.spec('B'))
        child.ready('source_ready')
        child.proc.terminate()
        self.assert_result(child, 'cancelled', 1)

    def test_bounded_identity_set(self):
        source = self.server()
        child = self.launch(self.spec(seconds=10))
        child.ready()
        peer = source.accepted.get(timeout=5)
        for number in range(4097):
            peer.send(event(status='running', identity=f'id-{number}'))
        self.assert_result(child, 'identity_limit', 1)

    def test_snapshot_wrong_subject_does_not_complete(self):
        self.server(handler=lambda p, m: p.send({'reply': 'A', 'record': event('wrong')}))
        child = self.launch(self.spec(snapshot=True, seconds=0.4))
        receipt = self.assert_result(child, 'timeout', 1)
        self.assertEqual(receipt['snapshot_requests'], 1)

    def test_connect_failure_has_terminal_receipt(self):
        child = self.launch()
        self.assert_result(child, 'connect_failed', 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
