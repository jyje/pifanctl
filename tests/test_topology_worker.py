import copy
import json
import threading
from urllib.request import urlopen
from urllib.error import HTTPError

import pytest
import yaml

from pifanctl.topology.model import TopologyError, digest
from pifanctl.topology.planner import plan, worker_plan
from pifanctl.topology.locks import HostLock
from pifanctl.topology import worker as w
from test_topology import fan, zone


def desired():
    return worker_plan(plan([fan(), zone(telemetry={'source': 'local'})]), 'pi-a')


def worker(monkeypatch):
    worker = w.Worker('pi-a', mock=True)
    monkeypatch.setattr(worker.local, 'read', lambda: 55)
    worker.apply(desired())
    return worker


def test_lock_and_symlink(tmp_path):
    with HostLock(tmp_path):
        with pytest.raises(RuntimeError):
            with HostLock(tmp_path): pass
    with HostLock(tmp_path): pass
    (tmp_path / 'worker.lock').unlink()
    (tmp_path / 'worker.lock').symlink_to(tmp_path / 'other')
    with pytest.raises(OSError):
        with HostLock(tmp_path): pass


def test_regulation_and_failsafe(monkeypatch):
    x = worker(monkeypatch)
    assert x.drivers['fan-a'].duty == 100
    assert x.cycle(now=100)['fans']['fan-a']['dutyPercent'] == 95
    assert x.cycle(now=101)['fans']['fan-a']['dutyPercent'] == 95
    assert x.cycle(now=105)['fans']['fan-a']['dutyPercent'] == 90
    assert x.cycle(False, 'Watchdog', now=106)['fans']['fan-a']['dutyPercent'] == 100
    assert not x.snapshot()['ready']
    monkeypatch.setattr(x.local, 'read', lambda: float('nan'))
    assert 'LocalSensorUnavailable' in x.cycle()['fans']['fan-a']['reason']
    d = x.drivers['fan-a']; x.close(); assert d.duty == 100


def test_reload_removal_and_hardware_immutable(monkeypatch):
    x = worker(monkeypatch); p = desired(); p['fans']['fan-a']['hardware']['rpigpio']['pin'] = 12
    p['hash'] = digest({k: v for k, v in p.items() if k != 'hash'})
    with pytest.raises(TopologyError): x.apply(p)
    empty = worker_plan(plan([]), 'pi-a'); x.apply(empty)
    assert x.cycle()['releasedFans'] == ['fan-a']
    assert not x.drivers
    x.apply(desired()); assert not x.released


@pytest.mark.parametrize('field,value', [('format', 2), ('nodeName', 'other'), ('nodeUID', 'other'), ('hash', 'bad'), ('watchdogSeconds', 0), ('fans', [])])
def test_bad_plan(field, value):
    p = desired(); p[field] = value
    with pytest.raises(TopologyError): w.validate_plan(p, 'pi-a', 'uid')


def test_plan_identity_and_conflict():
    p = desired(); p['fans']['fan-a']['name'] = 'other'; p['hash'] = digest({k: v for k, v in p.items() if k != 'hash'})
    with pytest.raises(TopologyError): w.validate_plan(p, 'pi-a')
    p = worker_plan(plan([fan(), fan('fan-b'), zone()]), 'pi-a')
    p['fans']['fan-a']['issues'] = []; p['hash'] = digest({k: v for k, v in p.items() if k != 'hash'})
    with pytest.raises(TopologyError): w.validate_plan(p, 'pi-a')
    p = worker_plan(plan([fan(), fan('fan-b'), zone()]), 'pi-a')
    x = w.Worker('pi-a', mock=True); x.apply(p); assert not x.drivers
    assert x.cycle()['fans']['fan-a']['reason'] == 'HardwareUnavailable'


def test_heartbeat(tmp_path):
    path = tmp_path / 'heartbeat'; p = desired()
    assert not w.heartbeat_ok(path, p, 100)
    for timestamp, ok in [(100, True), (-100, False), (110, False)]:
        path.write_text(json.dumps({'time': timestamp, 'healthy': True, 'planHash': p['hash'], 'nodeUID': ''}))
        assert w.heartbeat_ok(path, p, 100) == ok
    path.write_text('{}'); assert not w.heartbeat_ok(path, p)


def test_http(monkeypatch):
    x = worker(monkeypatch); x.cycle()
    server = w.serve(x, 0, '127.0.0.1')
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        for path in ['/status', '/healthz', '/readyz', '/metrics']:
            with urlopen(base + path) as r: assert r.status == 200
        x.cycle(False, 'expired')
        for path in ['/readyz', '/bad']:
            with pytest.raises(HTTPError): urlopen(base + path)
    finally: server.shutdown(); server.server_close(); x.close()


def test_run_reload_and_shutdown(monkeypatch, tmp_path):
    p = tmp_path / 'plan'; p.write_text(yaml.safe_dump(desired()))
    monkeypatch.setattr(w, 'install_stop_handlers', lambda stop: None)
    stop = threading.Event(); original = w.Worker.cycle
    calls = []
    def cycle(self, *args):
        monkeypatch.setattr(self.local, 'read', lambda: 55)
        result = original(self, *args); calls.append(result); stop.set(); return result
    monkeypatch.setattr(w.Worker, 'cycle', cycle)
    w.run(p, 'pi-a', mock=True, port=0, lock_dir=tmp_path / 'locks', stop=stop)
    assert calls[0]['ready']
    stop.clear(); p.write_text('bad')
    w.run(p, 'pi-a', mock=True, port=0, lock_dir=tmp_path / 'locks', stop=stop)
    assert calls[-1]['reason'].startswith('PlanInvalid')
