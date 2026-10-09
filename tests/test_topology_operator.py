import copy
import json
import time

import pytest
from typer.testing import CliRunner

from pifanctl.topology.kube import APIError, resource
from pifanctl.topology.model import TopologyError, bundle
from pifanctl.topology.operator import Lease, Operator, OWNER, FINALIZER, app as operator_app, worker_name
from test_topology import fan, zone, node


class FakeAPI:
    def __init__(self): self.objects = {}; self.calls = []; self.counter = 0
    def put(self, path, item):
        item = copy.deepcopy(item); self.counter += 1
        item['metadata'].setdefault('uid', f'uid-{self.counter}')
        item['metadata']['resourceVersion'] = str(self.counter)
        self.objects[path] = item; return copy.deepcopy(item)
    def get(self, path):
        if path not in self.objects: raise APIError(404, 'NotFound')
        return copy.deepcopy(self.objects[path])
    def optional(self, path): return self.get(path) if path in self.objects else None
    def items(self, path):
        return [copy.deepcopy(v) for k, v in self.objects.items() if k.rsplit('/', 1)[0] == path]
    def request(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, copy.deepcopy(body)))
        if method == 'POST':
            path += '/' + body['metadata']['name']
            if path in self.objects: raise APIError(409, 'AlreadyExists')
            return self.put(path, body)
        if method == 'PUT':
            old = self.get(path)
            if old['metadata']['resourceVersion'] != body['metadata'].get('resourceVersion'): raise APIError(409, 'Conflict')
            return self.put(path, body)
        if method == 'DELETE':
            self.objects.pop(path); return {}
        raise AssertionError(method)
    def patch(self, path, body):
        self.calls.append(('PATCH', path, copy.deepcopy(body)))
        old = self.get(path.removesuffix('/status'))
        rv = body.get('metadata', {}).get('resourceVersion')
        if rv and rv != old['metadata']['resourceVersion']: raise APIError(409, 'Conflict')
        def merge(obj, patch):
            for key, value in patch.items():
                if isinstance(value, dict): merge(obj.setdefault(key, {}), value)
                elif value is None: obj.pop(key, None)
                else: obj[key] = copy.deepcopy(value)
        merge(old, body)
        return self.put(path.removesuffix('/status'), old)
    def events(self, kind): return iter([])


@pytest.fixture
def setup():
    k = FakeAPI()
    for item in [fan(), zone()]: k.put(resource(item['kind'], item['metadata']['name']), item)
    n = node(labels={'kubernetes.io/hostname': 'pi-host'})
    k.put('/api/v1/nodes/pi-a', n)
    o = Operator(k, report_reader=lambda worker, now: None)
    return k, o


def test_lease():
    k = FakeAPI(); a = Lease(k, 'ns', 'operator', 'a'); b = Lease(k, 'ns', 'operator', 'b')
    assert a.acquire(100)
    assert not b.acquire(110)
    assert b.acquire(131)
    assert not a.acquire(132)
    assert b.acquire(140)


def test_operator_command_builds_crd_only_operator(monkeypatch):
    import pifanctl.topology.cli as topology_cli
    import pifanctl.topology.operator as operator_module

    kube = object()
    created = []
    monkeypatch.setattr(topology_cli, 'api', lambda ctx: kube)
    monkeypatch.setattr(operator_module, 'run_operator', created.append)
    result = CliRunner().invoke(operator_app, [
        '--namespace', 'pifanctl-system', '--operator-id', 'rack-controller',
        '--image', 'ghcr.io/jyje/pifanctl:test',
    ])
    assert result.exit_code == 0, result.output
    assert len(created) == 1
    assert created[0].kube is kube
    assert created[0].namespace == 'pifanctl-system'
    assert created[0].id == 'rack-controller'
    assert created[0].input_configmap is None
    assert created[0].image == 'ghcr.io/jyje/pifanctl:test'


def test_reconcile_placement_and_ownership(setup):
    k, o = setup; assert o.reconcile()
    config = k.get(o.core + '/configmaps/' + worker_name('pi-a') + '-plan')
    p = json.loads(config['data']['plan.json'])
    assert p['nodeUID'] == 'uid-a'
    deployment = k.get(o.apps + '/deployments/' + worker_name('pi-a'))
    spec = deployment['spec']; pod = spec['template']['spec']
    assert spec['replicas'] == 1 and spec['strategy']['type'] == 'Recreate'
    assert not pod['automountServiceAccountToken']
    assert pod['affinity']['nodeAffinity']['requiredDuringSchedulingIgnoredDuringExecution']['nodeSelectorTerms'][0]['matchFields'][0]['values'] == ['pi-a']
    assert pod['containers'][0]['securityContext']['privileged']
    assert FINALIZER in k.get(resource('Fan', 'fan-a'))['metadata']['finalizers']
    k.objects[o.apps + '/deployments/' + worker_name('pi-a')]['metadata']['annotations'][OWNER] = 'foreign'
    with pytest.raises(TopologyError, match='refusing'): o.reconcile()


def test_primary_transfer_and_node_replacement(setup):
    k, o = setup; o.reconcile()
    k.put(resource('Fan', 'fan-b'), fan('fan-b', hardware={'rpigpio': {'pin': 12}}))
    old = k.objects[resource('Fan', 'fan-a')]; old['metadata']['deletionTimestamp'] = 'now'
    o.reconcile()
    d = k.get(o.apps + '/deployments/' + worker_name('pi-a'))
    assert d['metadata']['ownerReferences'][0]['name'] == 'fan-b'
    k.objects['/api/v1/nodes/pi-a']['metadata']['uid'] = 'replacement'
    o.reconcile()
    cm = k.get(o.core + '/configmaps/' + worker_name('pi-a') + '-plan')
    assert json.loads(cm['data']['plan.json'])['nodeUID'] == 'replacement'


def test_configmap_mode(setup):
    import yaml
    k, o = setup
    for kind in ['Fan', 'CoolingZone']: k.objects.pop(resource(kind, 'fan-a' if kind == 'Fan' else 'rack'))
    k.put(o.core + '/configmaps/topology', {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'topology'},
        'data': {'topology.yaml': yaml.safe_dump(bundle([fan(), zone()]))}})
    o.input_configmap = 'topology'; assert o.reconcile()
    d = k.get(o.apps + '/deployments/' + worker_name('pi-a'))
    assert d['metadata']['ownerReferences'][0]['kind'] == 'ConfigMap'
    assert not any('/fans/' in path for method, path, body in k.calls)


def test_leader_loss_invalid_input_and_missing_node(setup):
    k, o = setup; o.reconcile(); count = len(k.calls)
    other = Lease(k, o.namespace, o.id, 'other'); assert other.acquire(time.time() + 100)
    assert not o.reconcile(); assert len(k.calls) == count + 1
    k.objects.pop(other.path + '/' + other.name)
    k.objects[resource('Fan', 'fan-a')]['spec']['hardware'] = {}
    with pytest.raises(TopologyError): o.reconcile()
    k.objects[resource('Fan', 'fan-a')]['spec']['hardware'] = {'rpigpio': {'pin': 18}}
    k.objects.pop('/api/v1/nodes/pi-a')
    assert o.reconcile()


def test_duplicate_operators_and_adoption(setup):
    k, o = setup
    k.objects[resource('Fan', 'fan-a')]['metadata']['annotations'] = {OWNER: 'other'}
    with pytest.raises(TopologyError): o.reconcile()


def test_same_id_in_other_namespace_cannot_adopt_crs(setup):
    k, o = setup; o.reconcile()
    other = Operator(k, namespace='other-system', operator_id=o.id)
    with pytest.raises(TopologyError, match='another operator'): other.reconcile()


def reporter(k, o, ready=True):
    def read(worker, now):
        p = json.loads(k.get(o.core + '/configmaps/' + worker + '-plan')['data']['plan.json'])
        return {'nodeName': p['nodeName'], 'nodeUID': p['nodeUID'], 'appliedTopologyHash': p['hash'],
                'heartbeatTime': now, 'podName': 'worker-pod', 'fans': {
                    f: {'ready': ready, 'reason': '' if ready else 'MissingOrStaleTemperature: pi-b',
                        'dutyPercent': 60 if ready else 100, 'temperatureCelsius': 60 if ready else None,
                        'nodes': {'pi-a': 60} if ready else {},
                        'zones': {z['name']: 60 for z in spec['zones']} if ready else {}}
                    for f, spec in p['fans'].items()}}
    return read


def test_status_rate_and_failure_clears_temperature(setup):
    k, o = setup; o.report_reader = reporter(k, o)
    o.reconcile(100)
    status = k.get(resource('Fan', 'fan-a'))['status']
    assert status['conditions'][0]['status'] == 'True' and status['controlTemperatureCelsius'] == 60
    count = len([c for c in k.calls if c[1].endswith('/status')])
    o.reconcile(110)
    assert len([c for c in k.calls if c[1].endswith('/status')]) == count
    o.report_reader = reporter(k, o, False); o.reconcile(111)
    status = k.get(resource('Fan', 'fan-a'))['status']
    assert status['dutyPercent'] == 100 and 'controlTemperatureCelsius' not in status
    assert status['conditions'][0]['reason'] == 'MissingOrStaleTemperature'
    zone_status = k.get(resource('CoolingZone', 'rack'))['status']
    assert zone_status['missingNodeNames'] == ['pi-a']


def test_deletion_waits_for_ack(setup):
    k, o = setup; o.reconcile()
    k.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    o.reconcile()
    assert FINALIZER in k.get(resource('Fan', 'fan-a'))['metadata']['finalizers']
    o.report_reader = reporter(k, o); o.reconcile()
    assert FINALIZER not in k.get(resource('Fan', 'fan-a'))['metadata']['finalizers']
    assert k.optional(o.apps + '/deployments/' + worker_name('pi-a')) is None
    assert k.get(o.core + '/configmaps/' + worker_name('pi-a') + '-plan')['metadata']['annotations']['pifanctl.jyje.online/released-hash']


def test_zone_deletion_and_shared_node_transfer(setup):
    k, o = setup
    k.put(resource('Fan', 'fan-b'), fan('fan-b', hardware={'rpigpio': {'pin': 12}}))
    z = zone(refs=['fan-a', 'fan-b']); k.put(resource('CoolingZone', 'rack'), z)
    o.report_reader = reporter(k, o); o.reconcile()
    k.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    o.reconcile()
    assert FINALIZER not in k.get(resource('Fan', 'fan-a'))['metadata']['finalizers']
    k.objects.pop(resource('Fan', 'fan-a'))
    k.objects[resource('CoolingZone', 'rack')]['metadata']['deletionTimestamp'] = 'now'
    o.reconcile()
    assert FINALIZER not in k.get(resource('CoolingZone', 'rack'))['metadata']['finalizers']


def test_invalid_report_does_not_acknowledge(setup):
    k, o = setup; o.reconcile()
    o.report_reader = lambda w, now: {'nodeName': 'pi-a', 'nodeUID': 'wrong', 'appliedTopologyHash': 'wrong'}
    o.reconcile()
    assert k.get(resource('Fan', 'fan-a'))['status']['conditions'][0]['status'] == 'False'


def test_configmap_delete_and_status(setup):
    import yaml
    k, o = setup; o.input_configmap = 'topology'
    k.put(o.core + '/configmaps/topology', {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'topology'},
        'data': {'topology.yaml': yaml.safe_dump(bundle([fan(), zone()]))}})
    o.report_reader = reporter(k, o); o.reconcile()
    assert any('status.json' in c.get('data', {}) for c in k.items(o.core + '/configmaps'))
    k.objects[o.core + '/configmaps/topology']['metadata']['deletionTimestamp'] = 'now'
    o.reconcile()
    assert FINALIZER not in k.get(o.core + '/configmaps/topology')['metadata']['finalizers']


def test_cluster_events_use_default_namespace(setup):
    k, o = setup
    o.reconcile()
    events = [(path, body) for method, path, body in k.calls if method == 'POST' and path.endswith('/events')]
    assert events
    assert all(path == '/api/v1/namespaces/default/events' for path, _ in events)
    assert all(body['metadata']['namespace'] == 'default' and 'namespace' not in body['involvedObject'] for _, body in events)


def test_event_failure_does_not_block_reconciliation(setup, caplog):
    k, o = setup
    request = k.request
    failures = []
    def rejecting_event(method, path, body=None, **kwargs):
        if method == 'POST' and path.endswith('/events'):
            failures.append(path)
            raise APIError(403, 'Forbidden')
        return request(method, path, body, **kwargs)
    k.request = rejecting_event
    assert o.reconcile()
    assert o.ready and len(failures) == 2
    assert 'API status 403' in caplog.text
    assert o.reconcile()
    assert len(failures) == 2
    assert o.reconcile(now=time.time() + 61)
    assert len(failures) == 4
    assert all(k.get(resource(kind, name))['status']['conditions'] for kind, name in [('Fan', 'fan-a'), ('CoolingZone', 'rack')])


def test_optional_tachometer_status_clears_stale_measurements(setup):
    k, o = setup
    item = k.get(resource('Fan', 'fan-a'))
    item['spec']['feedback'] = {'tachometer': {'gpio': {'pin': 23, 'pull': 'up'}}}
    k.put(resource('Fan', 'fan-a'), item)
    base_reader = reporter(k, o)
    state = {'ready': True, 'reason': '', 'rpm': 1200, 'observedTime': 100,
             'sampleSeconds': 5, 'pulseCount': 200}
    def read(worker, now):
        report = base_reader(worker, now)
        report['fans']['fan-a']['feedback'] = {'tachometer': copy.deepcopy(state)}
        return report
    o.report_reader = read
    o.reconcile(100)
    tach = k.get(resource('Fan', 'fan-a'))['status']['feedback']['tachometer']
    assert tach['rpm'] == 1200 and tach['observedAt'].endswith('Z')
    state.clear(); state.update(ready=False, reason='CollectorError', sampleSeconds=0, pulseCount=0)
    o.reconcile(131)
    tach = k.get(resource('Fan', 'fan-a'))['status']['feedback']['tachometer']
    assert 'rpm' not in tach and 'observedAt' not in tach and not tach['ready']
    item = k.get(resource('Fan', 'fan-a')); item['spec'].pop('feedback')
    k.put(resource('Fan', 'fan-a'), item)
    o.reconcile(162)
    assert 'tachometer' not in k.get(resource('Fan', 'fan-a'))['status']['feedback']


def test_pwm_probe_status_clears_numbers_and_removed_configuration(setup):
    k, o = setup
    item = k.get(resource('Fan', 'fan-a'))
    item['spec']['feedback'] = {'pwm': {'gpio': {'pin': 24}}}
    k.put(resource('Fan', 'fan-a'), item)
    base_reader = reporter(k, o)
    state = {'ready': True, 'reason': '', 'frequencyHz': 1000, 'dutyPercent': 25,
             'observedTime': 100, 'sampleSeconds': 1, 'cycleCount': 999}
    def read(worker, now):
        report = base_reader(worker, now)
        report['fans']['fan-a']['feedback'] = {'pwm': copy.deepcopy(state)}
        return report
    o.report_reader = read; o.reconcile(100)
    probe = k.get(resource('Fan', 'fan-a'))['status']['feedback']['pwm']
    assert probe['frequencyHz'] == 1000 and probe['observedAt'].endswith('Z')
    state.clear(); state.update(ready=False, reason='InsufficientEdges', sampleSeconds=1, cycleCount=0)
    o.reconcile(131)
    probe = k.get(resource('Fan', 'fan-a'))['status']['feedback']['pwm']
    assert 'frequencyHz' not in probe and 'dutyPercent' not in probe and 'observedAt' not in probe
    item = k.get(resource('Fan', 'fan-a')); item['spec'].pop('feedback'); k.put(resource('Fan', 'fan-a'), item)
    o.reconcile(162)
    probe = k.get(resource('Fan', 'fan-a'))['status']['feedback']['pwm']
    assert not probe['ready'] and probe['reason'] == 'NotConfigured'
