"""Synthetic socket -> child-owned process -> native child-final notification.
Run only after parent explicitly says PARENT IDLE. Parent alone may ack-wake.
"""
import argparse
import os
from pathlib import Path
import secrets
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--parent-idle', action='store_true', required=True)
parser.add_argument('--receipts', type=Path, required=True)
parser.add_argument('--owner', required=True)
args = parser.parse_args()
os.umask(0o077)
import test_wait_event as fixture  # noqa: E402
registry = args.receipts.resolve()
registry.mkdir(mode=0o700, exist_ok=True)
assert registry.stat().st_mode & 0o777 == 0o700
wait_id = 'native-' + secrets.token_hex(6)
owner = args.owner
child = None
servers = []
with tempfile.TemporaryDirectory(prefix='ew-native-', dir='/tmp') as short:
    short = Path(short)
    def callback(peer, message):
        assert message['owner'] == owner
        if message['type'] == 'register':
            # Child-final notifications are native to this child agent. This
            # handshake attests route registration, never parent resumption.
            peer.send({k: message[k] for k in ('wait_id', 'owner', 'nonce')} | {'type': 'callback_ready'})
        else:
            assert message['type'] == 'event_received'
    def source_request(peer, message):
        assert message == {'operation': 'subscribe', 'channel': 'jobs'}
        peer.send({'subscription': 'ready'})
    try:
        source = fixture.Server(short / 'source', handler=source_request)
        servers.append(source)
        wake = fixture.Server(short / 'wake', handler=callback)
        servers.append(wake)
        spec = {'wait_id': wait_id, 'registry': str(registry),
                'receipt': str(registry / wait_id / 'terminal.json'),
                'deadline': time.time() + 20,
                'source': {'identity': 'synthetic-native-probe', 'transport': 'unix',
                           'path': str(short / 'source'), 'read_only': True,
                           'event': fixture.mapping(),
                           'subscribe': {'request': {'operation': 'subscribe', 'channel': 'jobs'},
                                         'response': [{'path': ['subscription'], 'equals': 'ready'}]}},
                'wake': {'mode': 'native', 'owner': owner, 'socket': str(short / 'wake')}}
        child = fixture.Child(spec, short / 'spec.json')
        source_ready = child.ready('source_ready')
        callback_ready = child.ready('callback_ready')
        source.broadcast(fixture.event(identity='synthetic-native-complete'))
        code, stderr = child.finish()
        receipt = child.receipt()
        assert (code, stderr) == (0, ''), (code, stderr)
        assert receipt['result'] == 'wake_pending', receipt
        assert receipt['target_outcome'] == 'success', receipt
        assert receipt['event_received'] and receipt['callback_ready'] and receipt['source_ready']
        assert not receipt['wake_delivered']
        assert receipt['snapshot_requests'] == 0
        assert source.requests == [{'operation': 'subscribe', 'channel': 'jobs'}]
        assert not Path(spec['receipt']).with_name('wake-delivered.json').exists()
        for filename in ('source-ready.json', 'callback-ready.json', 'event.json', 'terminal.json'):
            path = Path(spec['receipt']).with_name(filename)
            assert path.stat().st_mode & 0o777 == 0o600
            print(filename + ': ' + path.read_text().strip(), flush=True)
        print('PASS synthetic source event -> child-owned runner completion; parent acknowledgment pending', flush=True)
        print('runner_exit_code=0 status_requests=0 subscription_requests=1', flush=True)
        print('terminal_receipt=' + spec['receipt'], flush=True)
        print('owner=' + owner + ' nonce=' + receipt['nonce'], flush=True)
    finally:
        if child:
            child.close()
        for server in servers:
            server.close()
            assert not server.errors, server.errors
