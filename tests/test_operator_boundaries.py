"""Realistic API and lifecycle boundaries, with only external IO substituted."""
import copy
import io
import json
import threading
import time
from unittest.mock import Mock

import pytest

from pifanctl.topology import operator as op
from pifanctl.topology.kube import APIError, resource
from pifanctl.topology.model import TopologyError
from test_topology_operator import FakeAPI, setup
from test_topology import zone


@pytest.mark.parametrize('error', [APIError(409, 'Conflict'), APIError(403, 'Forbidden')])
def test_lease_api_rejection_is_not_ownership(error):
    kube = FakeAPI()
    kube.request = Mock(side_effect=error)
    lease = op.Lease(kube, 'system', 'cooling', 'candidate')
    if error.status == 409:
        assert lease.acquire(100) is False
    else:
        with pytest.raises(APIError) as caught:
            lease.acquire(100)
        assert caught.value is error
    assert not kube.objects


def test_foreign_lease_without_optional_timestamps_is_not_stolen():
    kube = FakeAPI()
    lease = op.Lease(kube, 'system', 'cooling', 'candidate')
    kube.put(lease.path + '/cooling', {'metadata': {'name': 'cooling'},
             'spec': {'holderIdentity': 'another'}})
    assert lease.acquire(100) is False
    assert not kube.calls


@pytest.mark.parametrize('pods', [[], [{'metadata': {}, 'status': {}}],
    [{'metadata': {'deletionTimestamp': 'now'}, 'status': {'podIP': '127.0.0.1'}}],
    [{'metadata': {}, 'status': {'podIP': '127.0.0.1'}}] * 2])
def test_report_requires_exactly_one_live_addressable_pod(pods):
    kube = FakeAPI()
    kube.items = lambda path: copy.deepcopy(pods)
    assert op.Operator(kube).read_report('worker', 100) is None


@pytest.mark.parametrize('address,expected_host', [('127.0.0.1', '127.0.0.1'), ('::1', '[::1]')])
@pytest.mark.parametrize('heartbeat,accepted', [(100, True), (105, True), (10, True), (106, False), (9, False)])
def test_report_checks_source_time_and_formats_endpoint(monkeypatch, address, expected_host, heartbeat, accepted):
    kube = FakeAPI()
    kube.items = lambda path: [{'metadata': {'name': 'worker-pod'}, 'status': {'podIP': address}}]
    # Only the remote pod endpoint is substituted. Decode/time validation is real.
    request = Mock(return_value=io.BytesIO(json.dumps({'heartbeatTime': heartbeat}).encode()))
    monkeypatch.setattr(op, 'urlopen', request)
    result = op.Operator(kube).read_report('worker', 100)
    request.assert_called_once_with(f'http://{expected_host}:9103/status', timeout=2)
    assert (result is not None) is accepted
    if accepted:
        assert result == {'heartbeatTime': heartbeat, 'podName': 'worker-pod'}


@pytest.mark.parametrize('payload', [b'not-json', b'{}', b'{"heartbeatTime":null}', b'{"heartbeatTime":"bad"}'])
def test_corrupt_worker_report_is_not_accepted(monkeypatch, payload):
    kube = FakeAPI()
    kube.items = lambda path: [{'metadata': {'name': 'worker-pod'}, 'status': {'podIP': '127.0.0.1'}}]
    monkeypatch.setattr(op, 'urlopen', lambda *a, **k: io.BytesIO(payload))
    assert op.Operator(kube).read_report('worker', 100) is None


def test_unreachable_worker_is_not_accepted(monkeypatch):
    kube = FakeAPI()
    kube.items = lambda path: [{'metadata': {'name': 'worker-pod'}, 'status': {'podIP': '127.0.0.1'}}]
    monkeypatch.setattr(op, 'urlopen', Mock(side_effect=OSError('connection refused')))
    assert op.Operator(kube).read_report('worker', 100) is None


def test_oversized_plan_never_creates_worker(setup):
    kube, operator = setup
    # Valid CRs can expand beyond the ConfigMap payload budget when one
    # actuator serves many zones. Keep the production limit unchanged.
    members = ['.'.join(['n' * 60] * 3) + f'.pi-{i}' for i in range(128)]
    for i in range(32):
        item = zone(f'rack-{i}', nodes=members)
        kube.put(resource('CoolingZone', item['metadata']['name']), item)
    with pytest.raises(TopologyError, match='exceeds'):
        operator.reconcile(100)
    assert not kube.items(operator.apps + '/deployments')
    assert not kube.items(operator.core + '/configmaps')


def test_missing_hostname_does_not_place_worker(setup):
    kube, operator = setup
    kube.objects['/api/v1/nodes/pi-a']['metadata']['labels'].clear()
    with pytest.raises(TopologyError, match='hostname'):
        operator.reconcile(100)
    assert not kube.items(operator.apps + '/deployments')


def test_workload_deletion_does_not_recreate_it(setup):
    kube, operator = setup
    operator.reconcile(100)
    deployment = kube.objects[operator.apps + '/deployments/' + op.worker_name('pi-a')]
    deployment['metadata']['deletionTimestamp'] = 'now'
    with pytest.raises(TopologyError, match='deleting'):
        operator.reconcile(101)


def test_status_retries_failed_event_without_duplicate_patch(setup):
    kube, operator = setup
    original = kube.request
    def request(method, path, body=None, **kwargs):
        if path.endswith('/events'):
            raise APIError(403, 'Forbidden')
        return original(method, path, body, **kwargs)
    kube.request = request
    operator.reconcile(100)
    before = sum(path.endswith('/status') for method, path, body in kube.calls)
    operator.reconcile(101)
    assert sum(path.endswith('/status') for method, path, body in kube.calls) == before
    assert operator.failed_events


def test_run_loop_recovers_from_reconcile_failure_and_closes_server(monkeypatch):
    stop = threading.Event()
    operator = op.Operator(FakeAPI())
    calls = []
    def reconcile():
        calls.append(1)
        if len(calls) == 1:
            raise APIError(503, 'Unavailable')
        stop.set()
    operator.reconcile = reconcile
    threads = []
    class DeferredThread:
        def __init__(self, target, args=(), daemon=False): threads.append((target, args))
        def start(self): pass
    # Schedulers are controlled to test resync deterministically, without sleeping.
    monkeypatch.setattr(op.threading, 'Thread', DeferredThread)
    class Wake:
        def set(self): pass
        def wait(self, timeout): return True
        def clear(self): pass
    monkeypatch.setattr(op.threading, 'Event', Wake)
    monkeypatch.setattr(op, 'install_stop_handlers', lambda event: None)
    from pifanctl.topology import worker
    server = Mock()
    monkeypatch.setattr(worker, 'serve', lambda *args: server)
    op.run_operator(operator, stop, port=9104)
    assert len(calls) == 2 and not operator.ready
    server.shutdown.assert_called_once()
    server.server_close.assert_called_once()
    assert [args[0] for _, args in threads] == ['Node', 'Fan', 'CoolingZone']

    # Watch disconnection must back off and must not replace the resync loop.
    stop.clear()
    operator.kube.events = Mock(side_effect=APIError(503, 'Unavailable'))
    monkeypatch.setattr(stop, 'wait', lambda timeout: stop.set())
    threads[0][0](*threads[0][1])
    operator.kube.events.assert_called_once_with('Node')
    stop.clear()
    def events(kind):
        yield {'type': 'MODIFIED'}
        stop.set()
        yield {'type': 'MODIFIED'}
    operator.kube.events = events
    threads[0][0](*threads[0][1])
    assert stop.is_set()
    stop.clear()
    def timeout(kind):
        stop.set()
        return iter([])
    operator.kube.events = timeout
    threads[0][0](*threads[0][1])
    assert stop.is_set()


def test_identical_reconcile_does_not_rewrite_managed_resources(setup):
    kube, operator = setup
    operator.reconcile(100)
    before = len([c for c in kube.calls if '/deployments' in c[1] or '/configmaps' in c[1]])
    operator.reconcile(100)
    after = len([c for c in kube.calls if '/deployments' in c[1] or '/configmaps' in c[1]])
    assert before == after


def test_same_ready_condition_preserves_transition_through_other_conditions(setup):
    kube, operator = setup
    operator.reconcile(100)
    item = kube.objects[resource('Fan', 'fan-a')]
    item['status']['conditions'].insert(0, {'type': 'Initialized', 'status': 'True'})
    operator.reconcile(131)
    assert item['status']['conditions'][-1]['lastTransitionTime'] == op.timestamp(100)
    assert kube.get(resource('Fan', 'fan-a'))['status']['conditions'][0]['lastTransitionTime'] == op.timestamp(100)


def test_lease_loss_during_plan_write_does_not_send_heartbeat(setup):
    kube, operator = setup
    original = kube.request
    renewals = []
    def request(method, path, body=None, **kwargs):
        if '/leases/' in path:
            renewals.append(path)
            # Lease renewals made by protect have already happened; reject
            # the renewal immediately before writing the worker ConfigMap.
            if len(renewals) == 3:
                raise APIError(409, 'Conflict')
        return original(method, path, body, **kwargs)
    kube.request = request
    assert operator.reconcile(100) is False
    assert not kube.items(operator.core + '/configmaps')


def test_released_empty_plan_is_not_recreated_after_operator_restart(setup):
    from test_topology_operator import reporter
    kube, operator = setup
    operator.report_reader = reporter(kube, operator)
    operator.reconcile(100)
    kube.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    operator.reconcile(101)
    replacement = op.Operator(kube, report_reader=reporter(kube, operator))
    # Kubernetes removes the CR after its finalizer is released. A new
    # leader can then acquire the expired lease without changing its identity.
    kube.objects.pop(resource('Fan', 'fan-a'))
    replacement.reconcile(time.time() + 31)
    assert not kube.items(operator.apps + '/deployments')


@pytest.mark.parametrize('race', ['config-gone', 'foreign-workload', 'pods-terminating'])
def test_release_handles_concurrent_api_changes(setup, race):
    from test_topology_operator import reporter
    kube, operator = setup
    operator.report_reader = reporter(kube, operator)
    operator.reconcile(100)
    kube.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    config_path = operator.core + '/configmaps/' + op.worker_name('pi-a') + '-plan'
    deployment_path = operator.apps + '/deployments/' + op.worker_name('pi-a')
    original_optional, original_items = kube.optional, kube.items
    counts = {}
    def optional(path):
        counts[path] = counts.get(path, 0) + 1
        value = original_optional(path)
        # The second lookup is release observation, after normal managed writes.
        if counts[path] == 2 and path == config_path and race == 'config-gone':
            kube.objects.pop(path)
            return None
        if counts[path] == 2 and path == deployment_path and race == 'foreign-workload':
            value['metadata']['annotations'][op.OWNER] = 'other/operator'
        return value
    def items(path):
        if '/pods?' in path and race == 'pods-terminating':
            return [{'metadata': {'name': 'worker', 'deletionTimestamp': 'now'}}]
        return original_items(path)
    kube.optional, kube.items = optional, items
    if race == 'foreign-workload':
        with pytest.raises(TopologyError, match='foreign workload'):
            operator.reconcile(101)
        assert original_optional(deployment_path) is not None
    else:
        operator.reconcile(101)
        # The worker acknowledged actuator release. Terminating pods prevent
        # retirement bookkeeping, but no longer hold a physical fan claim.
        assert op.FINALIZER not in kube.get(resource('Fan', 'fan-a'))['metadata']['finalizers']
        if race == 'pods-terminating':
            assert original_optional(deployment_path) is None
            assert original_optional(config_path)['metadata']['annotations'][op.RELEASED]


def test_deleting_resource_without_runtime_claim_releases_finalizer(setup):
    kube, operator = setup
    # Adopt the desired resources before any worker is placed. The actuator
    # disappears before reconciliation, so no plan/workload ever existed.
    for kind, name in [('Fan', 'fan-a'), ('CoolingZone', 'rack')]:
        item = kube.get(resource(kind, name))
        operator.protect(item, resource(kind, name))
    kube.objects.pop('/api/v1/nodes/pi-a')
    kube.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    operator.reconcile(100)
    assert op.FINALIZER not in kube.get(resource('Fan', 'fan-a'))['metadata']['finalizers']


def test_untrusted_report_cannot_acknowledge_a_still_claimed_fan(setup):
    from test_topology_operator import reporter
    kube, operator = setup
    operator.reconcile(100)
    kube.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    reader = reporter(kube, operator)
    def report(worker, now):
        value = reader(worker, now)
        # Reports are external, not trusted as compliant Worker instances.
        value['fans']['fan-a'] = {'ready': False, 'dutyPercent': 100}
        return value
    operator.report_reader = report
    operator.reconcile(101)
    assert op.FINALIZER in kube.get(resource('Fan', 'fan-a'))['metadata']['finalizers']


@pytest.mark.parametrize('action', ['patch', 'write'])
def test_write_guard_rechecks_lease_before_mutation(setup, action):
    kube, operator = setup
    operator.reconcile(100)
    original = kube.request
    def request(method, path, body=None, **kwargs):
        if '/leases/' in path:
            raise APIError(409, 'Conflict')
        return original(method, path, body, **kwargs)
    kube.request = request
    before = len(kube.calls)
    with pytest.raises(TopologyError, match='LeadershipLost'):
        if action == 'patch': operator.patch(resource('Fan', 'fan-a'), {'status': {}})
        else: operator.write('DELETE', resource('Fan', 'fan-a'), {})
    assert len(kube.calls) == before


def test_deleting_unowned_resource_cannot_be_adopted(setup):
    kube, operator = setup
    kube.objects[resource('Fan', 'fan-a')]['metadata']['deletionTimestamp'] = 'now'
    with pytest.raises(TopologyError, match='cannot adopt'):
        operator.reconcile(100)
    assert not kube.items(operator.apps + '/deployments')


def test_configmap_status_does_not_repeat_within_rate_limit(setup):
    import yaml
    from pifanctl.topology.model import bundle
    from test_topology import fan
    kube, operator = setup
    operator.input_configmap = 'topology'
    kube.put(operator.core + '/configmaps/topology', {'apiVersion': 'v1', 'kind': 'ConfigMap',
        'metadata': {'name': 'topology'}, 'data': {'topology.yaml': yaml.safe_dump(bundle([fan(), zone()]))}})
    operator.reconcile(100)
    before = len([c for c in kube.calls if 'pifanctl-status-' in c[1]])
    operator.reconcile(101)
    assert len([c for c in kube.calls if 'pifanctl-status-' in c[1]]) == before


def test_operator_accepts_already_requested_shutdown(monkeypatch):
    stop = threading.Event()
    stop.set()
    monkeypatch.setattr(op, 'install_stop_handlers', lambda event: None)
    operator = op.Operator(FakeAPI())
    op.run_operator(operator, stop, port=0)
    assert not operator.kube.calls


def test_operator_reads_real_worker_http_report(tmp_path, monkeypatch):
    from pifanctl.topology import worker as runtime
    from test_topology_worker import desired
    from pifanctl.topology.model import digest
    sensor = tmp_path / 'thermal_zone0'
    sensor.mkdir()
    (sensor / 'temp').write_text('55000')
    worker = runtime.Worker('pi-a', thermal_path=str(tmp_path), mock=True)
    value = desired()
    value['nodeUID'] = 'uid-a'
    value['hash'] = digest({k: v for k, v in value.items() if k != 'hash'})
    worker.apply(value)
    worker.cycle(now=100)
    server = runtime.serve(worker, 0, '127.0.0.1')
    real_urlopen = op.urlopen
    # Only redirect the fixed pod port to the temporary localhost server.
    # Requests, HTTP handling, serialization and decoding all run unchanged.
    monkeypatch.setattr(op, 'urlopen', lambda url, **kwargs: real_urlopen(
        url.replace(':9103/', f':{server.server_port}/'), **kwargs))
    kube = FakeAPI()
    kube.items = lambda path: [{'metadata': {'name': 'worker-pod'}, 'status': {'podIP': '127.0.0.1'}}]
    try:
        report = op.Operator(kube).read_report('worker', 100)
        assert report['nodeUID'] == 'uid-a' and report['ready']
        assert report['appliedTopologyHash'] == value['hash']
        assert report['fans']['fan-a']['dutyPercent'] == 95
    finally:
        server.shutdown()
        server.server_close()
        worker.close()
