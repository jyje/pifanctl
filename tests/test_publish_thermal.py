from pathlib import Path
import json
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from publish_thermal_evidence import project


def row():
    return {'timestamp_utc': '2026-10-07T00:00:00+00:00',
            'source_observed_at_utc': '2026-10-07T00:00:00+00:00',
            'phase': 'load-fixed', 'elapsed_s': 1, 'hottest_c': 50,
            'requested_duty_percent': 35, 'max_source_age_s': 1, 'worker_heartbeat_age_s': 1,
            'member_temperatures_json': '{"private-host":50}',
            'member_observed_timestamps_json': '{"private-host":1791331200}',
            'irrelevant_private_field': '10.0.0.1'}


def test_projection_excludes_names_extra_fields_and_preserves_measurements():
    data = project([row()])
    assert 'private-host' not in json.dumps(data)
    assert '10.0.0.1' not in json.dumps(data)
    assert json.loads(data[0]['member_temperatures_json']) == {'node-a': 50}
    assert data[0]['hottest_c'] == 50


@pytest.mark.parametrize('key,value', [('phase', 'private-error'), ('hottest_c', 'nan'),
                                      ('member_observed_timestamps_json', '{}'),
                                      ('member_temperatures_json', '{"private-host":NaN}')])
def test_projection_rejects_invalid_telemetry(key, value):
    sample = row()
    sample[key] = value
    with pytest.raises(ValueError):
        project([sample])


def test_execution_counters_are_projected_without_private_fields():
    from publish_thermal_evidence import execution
    result = execution('{"reason":"local_temperature_cutoff","elapsed_seconds":160,"cpu_seconds":40,"node":"private"}')
    assert result['average_consumed_vcpu'] == 0.25
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('reason,elapsed,cpu', [('private', 160, 40), ('local_duration_deadline', 0, 40),
                                              ('local_temperature_cutoff', 160, -1)])
def test_execution_rejects_unsupported_or_invalid_counters(reason, elapsed, cpu):
    from publish_thermal_evidence import execution
    with pytest.raises(ValueError):
        execution(json.dumps({'reason': reason, 'elapsed_seconds': elapsed, 'cpu_seconds': cpu}))
