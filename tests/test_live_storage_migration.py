from copy import deepcopy
from pathlib import Path
import hashlib
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_live_storage_migration import healthy, main, manual, restore_definitions, worker_ready


def rack():
    ready = {'type': 'Ready', 'status': 'True', 'observedGeneration': 1}
    return [
        {'kind': 'Fan', 'metadata': {'name': 'rack-fan', 'generation': 1},
         'status': {'conditions': [deepcopy(ready)], 'heartbeatTime': '2026-10-06T00:00:00Z', 'dutyPercent': 38}},
        {'kind': 'CoolingZone', 'metadata': {'name': 'rack-zone', 'generation': 1},
         'status': {'conditions': [deepcopy(ready)], 'temperatureObservedAt': '2026-10-06T00:00:00Z',
                    'memberCount': 4, 'missingNodeNames': [], 'temperatureCelsius': 49}},
    ]


NOW = 1791244805


def test_healthy_rack_accepts_fresh_ready_inventory():
    resources = rack()
    assert healthy(resources, 'rack-fan', 'rack-zone', NOW) is resources[0]


@pytest.mark.parametrize('index,key,value', [
    (0, 'heartbeatTime', '2026-10-05T23:59:00Z'),
    (0, 'heartbeatTime', '2026-10-06T00:01:00Z'),
    (1, 'temperatureObservedAt', '2026-10-05T23:59:00Z'),
    (0, 'dutyPercent', -1), (0, 'dutyPercent', 101),
    (1, 'memberCount', 3), (1, 'missingNodeNames', ['absent']),
    (1, 'temperatureCelsius', 65),
])
def test_healthy_rack_rejects_unsafe_status(index, key, value):
    resources = rack()
    resources[index]['status'][key] = value
    with pytest.raises(RuntimeError):
        healthy(resources, 'rack-fan', 'rack-zone', NOW)


@pytest.mark.parametrize('change', ['deleting', 'unready', 'old_generation', 'extra_resource'])
def test_healthy_rack_rejects_incomplete_inventory(change):
    resources = rack()
    if change == 'deleting':
        resources[0]['metadata']['deletionTimestamp'] = '2026-10-06T00:00:00Z'
    elif change == 'unready':
        resources[0]['status']['conditions'][0]['status'] = 'False'
    elif change == 'old_generation':
        resources[0]['metadata']['generation'] = 2
    else:
        resources.append({'kind': 'Fan', 'metadata': {'name': 'other'}})
    with pytest.raises(RuntimeError):
        healthy(resources, 'rack-fan', 'rack-zone', NOW)


def test_manual_application_rejects_automation_and_active_sync():
    manual({'spec': {'syncPolicy': {}}})
    for obj in [
        {'spec': {'syncPolicy': {'automated': {}}}},
        {'spec': {}, 'operation': {'sync': {}}},
        {'spec': {}, 'status': {'operationState': {'phase': 'Running'}}},
    ]:
        with pytest.raises(RuntimeError):
            manual(obj)


def test_worker_requires_current_ready_container_and_no_retirement():
    assert worker_ready({'metadata': {}, 'status': {'containerStatuses': [{'ready': True}]}})
    for pod in [
        {'metadata': {}, 'status': {}},
        {'metadata': {}, 'status': {'containerStatuses': [{'ready': False}]}},
        {'metadata': {'deletionTimestamp': 'now'}, 'status': {'containerStatuses': [{'ready': True}]}},
    ]:
        assert not worker_ready(pod)


@pytest.mark.parametrize('context,execute', [('kind-pifanctl-release', True), ('microk8s', False)])
def test_live_execution_requires_explicit_context_and_flag(monkeypatch, context, execute):
    args = ['verify', '--context', context, '--application', 'rack', '--fan', 'f', '--zone', 'z',
            '--archive', '/tmp/unused-live-archive', '--report', '/tmp/unused-live-report.json']
    if execute:
        args.append('--execute')
    monkeypatch.setattr(sys, 'argv', args)
    with pytest.raises(SystemExit, match='Explicit'):
        main()


@pytest.mark.parametrize('change', [None, 'checksum', 'uid', 'storage', 'schema'])
def test_reverse_restore_requires_verified_alpha_archive(tmp_path, change):
    crds = {k: {'metadata': {'uid': k}, 'status': {'storedVersions': ['v1alpha1']},
                'spec': {'versions': [{'name': 'v1alpha1', 'storage': True, 'served': True}]}}
            for k in ('fans', 'coolingzones')}
    originals = deepcopy(crds)
    if change == 'uid':
        crds['fans']['metadata']['uid'] = 'foreign'
    if change == 'storage':
        crds['fans']['status']['storedVersions'] = ['v1']
    if change == 'schema':
        crds['fans']['spec']['versions'].append({'name': 'v1', 'storage': False, 'served': True})
    raw = json.dumps({'crds': crds}).encode()
    (tmp_path / 'baseline.json').write_bytes(raw)
    (tmp_path / 'SHA256SUMS.json').write_text(json.dumps({'baseline.json': hashlib.sha256(raw).hexdigest()}))
    if change == 'checksum':
        (tmp_path / 'baseline.json').write_bytes(raw + b' ')
    if change:
        with pytest.raises(RuntimeError):
            restore_definitions(tmp_path, originals)
    else:
        assert restore_definitions(tmp_path, originals) == crds
