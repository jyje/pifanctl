from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from collect_live_thermal import guarded_load, load_pod, main, validate_sample


def series(node, value):
    return {'metric': {'node': node}, 'value': [999, str(value)]}


def worker():
    return {'ready': True, 'heartbeatTime': 99,
            'fans': {'fan': {'ready': True, 'reason': '', 'dutyPercent': 35}}}


def test_acquisition_clock_and_all_members_are_recorded():
    assert validate_sample([series('a', 49)], [series('a', 90)], ['a'], worker(), 'fan', 100) == (
        {'a': 49}, {'a': 90}, 35, 1)


@pytest.mark.parametrize('value,clock', [(65, 90), (float('nan'), 90), (49, 74),
                                        (49, 101), (49, float('nan'))])
def test_unsafe_or_stale_telemetry_stops_load(value, clock):
    with pytest.raises(RuntimeError):
        validate_sample([series('a', value)], [series('a', clock)], ['a'], worker(), 'fan', 100)


def test_missing_members_rejected():
    with pytest.raises(RuntimeError, match='Incomplete'):
        validate_sample([], [series('a', 90)], ['a'], worker(), 'fan', 100)


@pytest.mark.parametrize('change', [lambda w: w.update(ready=False),
                                    lambda w: w.update(heartbeatTime=80),
                                    lambda w: w['fans']['fan'].update(reason='missing'),
                                    lambda w: w['fans']['fan'].update(dutyPercent=float('nan'))])
def test_worker_guards(change):
    w = worker()
    change(w)
    with pytest.raises(RuntimeError, match='Unhealthy'):
        validate_sample([series('a', 49)], [series('a', 90)], ['a'], w, 'fan', 100)


def test_local_guard_exits_before_heating():
    assert guarded_load(360, 55, lambda: 55, lambda: 0) == 'local_temperature_cutoff'


def test_local_guard_rejects_invalid_sensor():
    with pytest.raises(RuntimeError):
        guarded_load(360, 55, lambda: float('nan'), lambda: 0)


def test_local_guard_fails_closed_on_sensor_loss():
    def missing():
        raise OSError('missing sensor')
    with pytest.raises(OSError):
        guarded_load(360, 55, missing, lambda: 0)


def test_local_guard_deadline_is_independent_of_remote_collector():
    counter = iter(range(100))
    assert guarded_load(3, 55, lambda: 49, lambda: next(counter)) == 'local_duration_deadline'


def test_load_has_no_host_devices_credentials_or_privilege():
    pod = load_pod('trial', 'ns', 'node', 'image', 250, 360, 55)
    spec = pod['spec']
    assert spec['activeDeadlineSeconds'] == 450
    assert spec['automountServiceAccountToken'] is False
    assert 'volumes' not in spec
    assert spec['securityContext']['runAsNonRoot']
    c = spec['containers'][0]
    assert c['resources']['limits'] == {'cpu': '250m', 'memory': '64Mi'}
    assert c['securityContext']['capabilities']['drop'] == ['ALL']
    assert c['securityContext']['readOnlyRootFilesystem']
    assert not c['securityContext']['allowPrivilegeEscalation']
    assert '/sys/class/thermal/thermal_zone0/temp' in c['command'][2]
    compile(c['command'][2], '<load>', 'exec')


def test_archive_is_not_overwritten_before_api_access(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'argv', ['trial', '--context', 'microk8s', '--application', 'app',
                                    '--fan', 'fan', '--zone', 'zone', '--node', 'node',
                                    '--archive', str(tmp_path), '--target', '50', '--execute'])
    with pytest.raises(SystemExit, match='new archive'):
        main()


@pytest.mark.parametrize('fail_after_create', [False, True])
def test_collection_cleanup_and_cooldown_after_runtime_failure(monkeypatch, tmp_path, fail_after_create):
    import json
    import collect_live_thermal as module
    archive = tmp_path / 'new'
    source = {'targetRevision': 'abc'}
    app = {'spec': {'source': source, 'destination': {'namespace': 'ns'}},
           'status': {'sync': {'status': 'Synced', 'revision': 'abc', 'comparedTo': {'source': source}},
                      'health': {'status': 'Healthy'},
                      'operationState': {'phase': 'Succeeded', 'syncResult': {'source': source, 'revision': 'abc'}}}}
    fan = {'kind': 'Fan', 'metadata': {'name': 'fan', 'uid': 'fan-id'}, 'spec': {},
           'status': {'nodeUID': 'node-id', 'appliedTopologyHash': 'hash'}}
    zone = {'kind': 'CoolingZone', 'metadata': {'name': 'zone', 'uid': 'zone-id'},
            'spec': {'nodeNames': ['node']}}
    pod = {'metadata': {'name': 'worker', 'uid': 'worker-id'},
           'spec': {'containers': [{'image': 'image'}]},
           'status': {'containerStatuses': [{'ready': True}]}}
    state = {'time': 0, 'load': False, 'deleted': False, 'failed_once': False}

    def api(parts, **kwargs):
        parts = parts[3:]
        if parts[0] == 'create':
            state['load'] = True
            return '{}'
        if parts[0] == 'delete':
            state['load'] = False
            state['deleted'] = True
            return ''
        if parts[0] in ('logs', 'wait'):
            return 'local_duration_deadline'
        if parts[0] != 'get':
            raise AssertionError(parts)
        if parts[1] == 'application':
            if fail_after_create and state['load'] and not state['failed_once']:
                state['failed_once'] = True
                raise RuntimeError('injected API failure')
            return json.dumps(app)
        if parts[1] == 'fans,coolingzones':
            return json.dumps({'items': [fan, zone]})
        if parts[1] == 'nodes':
            return json.dumps({'items': [{'metadata': {'name': 'node'},
                                          'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]})
        if parts[1] == 'pods':
            return json.dumps({'items': [] if parts[-3].endswith('=controller') else [pod]})
        if parts[1] == 'pod':
            return json.dumps({'metadata': {'uid': 'load-id'}, 'status': {'phase': 'Succeeded'}})
        if parts[1].startswith('--raw='):
            if '/status' in parts[1]:
                direct = worker()
                direct.update(nodeUID='node-id', appliedTopologyHash='hash', heartbeatTime=100+state['time'])
                return json.dumps(direct)
            value = 100+state['time'] if 'observed_timestamp' in parts[1] else 49
            return json.dumps({'status': 'success', 'data': {'result': [series('node', value)]}})
        raise AssertionError(parts)

    monkeypatch.setattr(module.subprocess, 'check_output', api)
    monkeypatch.setattr(module.time, 'monotonic', lambda: state['time'])
    monkeypatch.setattr(module.time, 'time', lambda: 100+state['time'])
    monkeypatch.setattr(module.time, 'sleep', lambda seconds: state.update(time=state['time']+seconds))
    monkeypatch.setattr(sys, 'argv', ['trial', '--context', 'microk8s', '--application', 'app',
                                    '--fan', 'fan', '--zone', 'zone', '--node', 'node',
                                    '--archive', str(archive), '--target', '50', '--execute'])
    if fail_after_create:
        with pytest.raises(RuntimeError, match='injected'):
            main()
    else:
        main()
    report = json.loads((archive / 'report.json').read_text())
    assert state['deleted'] and not state['load']
    assert report['cleanup_verified']
    assert report['cooldown_recorded']
    assert report['collector_passed'] is not fail_after_create
    assert not report['acceptance']['thermal_stability_passed']
    assert (archive / 'samples.csv').stat().st_mode & 0o777 == 0o600


def test_local_guard_records_peak_without_changing_cutoff():
    observations = {}
    assert guarded_load(360, 60, lambda: 60.25, lambda: 0, observations) == 'local_temperature_cutoff'
    assert observations == {'local_peak_celsius': 60.25, 'last_local_celsius': 60.25}
