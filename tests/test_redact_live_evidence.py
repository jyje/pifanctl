import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from redact_live_evidence import public_summary


def test_public_runtime_projection_drops_private_objects_and_identifiers():
    raw = {'passed': True, 'secret': 'private-token', 'samples': [{
        'observed_at_utc': '2026-10-06T00:00:00Z', 'hold_seconds': 120,
        'worker_report': {'ready': True, 'heartbeatTime': 100, 'nodeUID': 'private-node-uid',
                          'fans': {'private-fan': {'dutyPercent': 38}}},
        'member_temperatures': {'private-host': 49}, 'member_source_times': {'private-host': 99},
        'application': {'metadata': {'uid': 'private-app-uid'}, 'spec': {'source': {'repoURL': 'https://private-service'}},
                        'status': {'sync': {'status': 'Synced'}, 'health': {'status': 'Healthy'}}},
        'worker': {'status': {'podIP': '10.123.4.5'}},
    }]}
    projected = public_summary(raw)
    encoded = json.dumps(projected)
    assert 'private-' not in encoded and '10.123.4.5' not in encoded
    assert projected['samples'][0]['member_temperatures'] == {'node-a': 49}
    assert projected['samples'][0]['requested_duty_percent'] == 38


def test_storage_projection_reports_identity_equality_without_publishing_uid():
    samples = [{'worker_uid': worker, 'stage': 'sample', 'resources': [{
        'kind': 'Fan', 'metadata': {'uid': uid, 'name': 'private-fan'},
        'status': {'dutyPercent': 38, 'conditions': [{'type': 'Ready', 'status': 'True'}]}}]}
        for uid, worker in [('private-uid', 'private-worker'), ('replacement-uid', 'replacement-worker')]]
    raw = {'mode': 'roundtrip', 'passed': False, 'samples': samples,
           'checks': [{'name': 'inventory', 'passed': False, 'resources': ['private-fan']}]}
    projected = public_summary(raw)
    assert 'private-' not in json.dumps(projected) and 'replacement-' not in json.dumps(projected)
    assert projected['samples'][0]['resource_identity_unchanged']['Fan']
    assert not projected['samples'][1]['resource_identity_unchanged']['Fan']
    assert not projected['samples'][1]['worker_identity_unchanged']


def test_failed_observer_never_exports_arbitrary_error_or_claims_guards():
    projected = public_summary({'passed': False, 'samples': [], 'error': 'private-token at private-host'})
    assert 'private-' not in json.dumps(projected)
    assert projected['completed_guards'] == []


def test_unknown_check_labels_and_gitops_strings_cannot_disclose_identifiers():
    storage = public_summary({'mode': 'private-mode', 'passed': False, 'checks': [
        {'name': 'private-check-name', 'passed': False}], 'samples': []})
    runtime = public_summary({'passed': False, 'samples': [], 'final_application': {
        'status': {'sync': {'status': 'private-host'}, 'health': {'status': 'private-token'}}}})
    assert 'private-' not in json.dumps(storage) + json.dumps(runtime)


@pytest.mark.parametrize('field,value', [('minimum_hold_seconds', 'private-token'),
                                        ('minimum_hold_seconds', float('nan')),
                                        ('started_at_utc', 'private-host'),
                                        ('finished_at_utc', None)])
def test_invalid_measurement_types_fail_without_echoing_private_values(field, value):
    with pytest.raises(ValueError) as error:
        public_summary({field: value})
    assert 'private-' not in str(error.value)
