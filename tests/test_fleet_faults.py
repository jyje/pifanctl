import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_fleet_faults import expired, fixtures
from pifanctl.topology.model import normalize
from pifanctl.topology.planner import plan


@pytest.mark.parametrize('count', [1, 4, 16])
def test_declared_fleet_has_unique_channels_and_valid_local_zones(count):
    fans, zones = fixtures('node-a', count)
    node = {'metadata': {'name': 'node-a', 'uid': 'uid', 'labels': {}}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    topology = plan(normalize(fans + zones), [node])
    assert len(topology['fans']) == count
    assert len(topology['zones']) == count*4
    assert len({f['spec']['hardware']['rpigpio']['pin'] for f in fans}) == count
    assert all(not f['issues'] for f in topology['fans'].values())
    assert all(not z['issues'] for z in topology['zones'].values())


def test_fixture_bounds_and_failsafe_predicate():
    with pytest.raises(ValueError):
        fixtures('node', 28)
    value = {'ready': False, 'fans': {'a': {'ready': False, 'dutyPercent': 100, 'reason': 'OperatorHeartbeatExpired'}}}
    assert expired(value, ['a'])
    assert not expired(value, ['a', 'b'])
    assert not expired({'ready': True, 'fans': value['fans']}, ['a'])
    value['fans']['a']['dutyPercent'] = 99
    assert not expired(value, ['a'])


def test_api_counter_filters_group_and_ignores_comments_and_other_metrics():
    from measure_lab_resources import api_totals
    assert api_totals('# apiserver_request_total help\napiserver_request_total{group="pifanctl.jyje.online",verb="GET"} 12\napiserver_request_total{group="",verb="GET"} 9\nother{group="pifanctl.jyje.online"} 88\n') == 12


def test_telemetry_fault_requires_unhealthy_full_duty_and_expected_reason():
    from verify_telemetry_faults import failed, run_simulator
    import inspect
    assert not failed({}, 'stale')
    value = {'ready': False, 'fans': {'fault-fan': {'ready': False, 'dutyPercent': 100, 'reason': 'MissingOrStaleTemperature'}}}
    assert failed(value, 'MissingOrStaleTemperature')
    assert not failed(value, 'Prometheus query failed')
    value['fans']['fault-fan']['ready'] = True
    assert not failed(value, 'MissingOrStaleTemperature')
    compile(inspect.getsource(run_simulator)+'\nrun_simulator()', '<fixture>', 'exec')


def test_abrupt_stop_requires_exact_simulated_worker_identity():
    from verify_telemetry_faults import checked_runtime_pid
    pod = {'spec': {'nodeName': 'pifanctl-release-control-plane'}, 'metadata': {'uid': 'owned'}}
    inspection = {'info': {'pid': 123}, 'status': {'image': {'image': 'docker.io/library/pifanctl-runtime-lab:alpha6'},
        'labels': {'io.kubernetes.pod.uid': 'owned', 'io.kubernetes.pod.namespace': 'pifanctl-release', 'io.kubernetes.container.name': 'worker'}}}
    assert checked_runtime_pid(inspection, pod) == 123
    inspection['info']['pid'] = 1
    with pytest.raises(ValueError):
        checked_runtime_pid(inspection, pod)
    inspection['info']['pid'] = 123
    inspection['status']['labels']['io.kubernetes.pod.uid'] = 'replacement'
    with pytest.raises(ValueError):
        checked_runtime_pid(inspection, pod)


@pytest.mark.parametrize('field,value', [('image', 'ghcr.io/jyje/pifanctl:stable'),
                                         ('namespace', 'production'), ('container', 'operator'),
                                         ('node', 'actual-pi')])
def test_abrupt_stop_rejects_other_images_namespaces_containers_and_nodes(field, value):
    from verify_telemetry_faults import checked_runtime_pid
    pod = {'spec': {'nodeName': 'pifanctl-release-control-plane'}, 'metadata': {'uid': 'owned'}}
    inspection = {'info': {'pid': 123}, 'status': {'image': {'image': 'pifanctl-runtime-lab:alpha6'},
        'labels': {'io.kubernetes.pod.uid': 'owned', 'io.kubernetes.pod.namespace': 'pifanctl-release', 'io.kubernetes.container.name': 'worker'}}}
    if field == 'image':
        inspection['status']['image']['image'] = value
    elif field == 'node':
        pod['spec']['nodeName'] = value
    else:
        key = 'io.kubernetes.pod.namespace' if field == 'namespace' else 'io.kubernetes.container.name'
        inspection['status']['labels'][key] = value
    with pytest.raises(ValueError):
        checked_runtime_pid(inspection, pod)
