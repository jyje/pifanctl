"""Systems-manual scenarios exercise the actual planner/worker with mock PWM."""
import copy
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from kubernetes import client

from pifanctl.topology.kube import Kube, APIError
from pifanctl.topology.model import load, digest
from pifanctl.topology.planner import plan, worker_plan
from pifanctl.topology.worker import Worker
from pifanctl.topology import telemetry, operator as op
from test_topology import node
from test_topology_operator import FakeAPI, reporter


def test_two_racks_hot_missing_watchdog(monkeypatch):
    items = load('design/v1/examples/two-racks.yaml')
    labels = [('a' if i <= 4 else 'b') for i in range(1, 9)]
    # The examples use this label and hostname can differ from Node name.
    nodes = [node(f'pi-{i:02}', {'cooling.pifanctl.jyje.online/rack': rack}, uid=f'uid-{i}') for i, rack in enumerate(labels, 1)]
    selector = next(o['spec']['nodeSelector'] for o in items if o['kind'] == 'CoolingZone')
    key, _ = next(iter(selector['matchLabels'].items()))
    for n, rack in zip(nodes, labels): n['metadata']['labels'] = {key: rack}
    topology = plan(items, nodes)
    temperatures = {f'pi-{i:02}': t for i, t in enumerate([51, 55, 62, 57, 49, 53, 55, 54], 1)}
    def query(url, expression):
        return {(('node', n), ('zone', 'cpu'), ('type', 'cpu')): (100 if 'timestamp' in expression else value)
                for n, value in temperatures.items()}
    monkeypatch.setattr(telemetry, 'query', query)
    workers = {}
    for name, fan in topology['fans'].items():
        w = Worker(fan['nodeName'], fan['nodeUID'], mock=True)
        monkeypatch.setattr(w.local, 'read', lambda: 40)
        w.apply(worker_plan(topology, fan['nodeName'])); workers[name] = w
    try:
        # Repeated identical fresh inputs settle the configured downward ramp.
        for i in range(11):
            for w in workers.values(): w.cycle(now=100 + i * 0.01); w.updated.clear()
        duties = {n: w.snapshot()['fans'][n]['dutyPercent'] for n, w in workers.items()}
        assert sorted(duties.values()) == [47.5, 72]
        fan_a = next(n for n, f in topology['fans'].items() if 'pi-03' in f['zones'][0]['members'])
        fan_b = next(n for n in workers if n != fan_a)
        temperatures['pi-03'] = 78
        for w in workers.values(): w.cycle(now=100)
        assert workers[fan_a].snapshot()['fans'][fan_a]['dutyPercent'] == 100
        assert workers[fan_b].snapshot()['fans'][fan_b]['dutyPercent'] == 47.5
        temperatures.pop('pi-03')
        for w in workers.values(): w.cycle(now=100)
        assert not workers[fan_a].snapshot()['ready'] and workers[fan_b].snapshot()['ready']
        for w in workers.values():
            assert all(s['dutyPercent'] == 100 for s in w.cycle(False, 'OperatorHeartbeatExpired')['fans'].values())
    finally:
        for w in workers.values(): w.close()


def test_official_client_http_transport():
    calls = []
    class Handler(BaseHTTPRequestHandler):
        def do_PATCH(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append((self.path, self.headers['Content-Type'], body))
            self.send_response(200); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(json.dumps(body).encode())
        def do_GET(self):
            self.send_response(403); self.send_header('Content-Type', 'application/json'); self.end_headers()
            self.wfile.write(b'{"message":"PRIVATE","reason":"Forbidden"}')
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    config = client.Configuration(); config.host = f'http://127.0.0.1:{server.server_port}'
    api_client = client.ApiClient(config); k = Kube(client=api_client)
    from test_topology import fan
    try:
        assert k.apply(fan(), True)['kind'] == 'Fan'
        assert 'dryRun=All' in calls[0][0] and 'force=false' in calls[0][0]
        assert calls[0][1] == 'application/apply-patch+yaml'
        with pytest.raises(APIError) as error: k.get('/denied')
        assert 'PRIVATE' not in str(error.value)
    finally: api_client.close(); server.shutdown(); server.server_close()


def test_operator_loop_watch_recovery_and_health(monkeypatch):
    from test_topology import fan, zone
    from pifanctl.topology.kube import resource
    k = FakeAPI()
    for item in [fan(), zone()]: k.put(resource(item['kind'], item['metadata']['name']), item)
    k.put('/api/v1/nodes/pi-a', node(labels={'kubernetes.io/hostname': 'host'}))
    o = op.Operator(k); o.report_reader = reporter(k, o)
    stop = threading.Event()
    monkeypatch.setattr(op, 'install_stop_handlers', lambda stop: None)
    def events(kind):
        stop.wait(0.05)
        raise APIError(410, 'Expired')
        yield
    monkeypatch.setattr(k, 'events', events)
    original = o.reconcile
    def reconcile():
        try: return original()
        finally: stop.set()
    monkeypatch.setattr(o, 'reconcile', reconcile)
    op.run_operator(o, stop, port=0)
    assert o.snapshot()['ready']
    o.last_reconcile = time.time() - 31
    assert not o.snapshot()['ready']
