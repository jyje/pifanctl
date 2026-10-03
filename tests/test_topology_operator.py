import copy
import json
import time

import pytest

from pifanctl.topology.kube import APIError, resource
from pifanctl.topology.model import TopologyError, bundle
from pifanctl.topology.operator import Lease, Operator, OWNER, FINALIZER, worker_name
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
