from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_live_runtime import main, telemetry, source_clock_query


def series(node, value):
    return {'metric': {'node': node}, 'value': [9999, str(value)]}


def test_member_freshness_uses_source_clock_not_query_evaluation_time():
    values, clocks = [series('pi', 49)], [series('pi', 90)]
    assert telemetry(values, clocks, ['pi'], 100) == ({'pi': 49}, {'pi': 90})
    with pytest.raises(RuntimeError, match='stale'):
        telemetry(values, clocks, ['pi'], 121)


@pytest.mark.parametrize('values,clocks', [
    ([], [series('pi', 99)]), ([series('pi', 49)], []),
    ([series('other', 49)], [series('pi', 99)]),
    ([series('pi', 65)], [series('pi', 99)]),
    ([series('pi', 49)], [series('pi', 101)]),
])
def test_missing_hot_and_future_sources_are_rejected(values, clocks):
    with pytest.raises(RuntimeError):
        telemetry(values, clocks, ['pi'], 100)


def test_runtime_report_is_never_overwritten_before_api_access(monkeypatch, tmp_path):
    report = tmp_path / 'existing.json'
    report.write_text('original')
    monkeypatch.setattr(sys, 'argv', ['verify', '--context', 'microk8s', '--application', 'app',
                                     '--revision', 'a' * 40, '--image', 'example', '--digest', 'example',
                                     '--baseline', str(tmp_path / 'unused'), '--report', str(report)])
    with pytest.raises(SystemExit, match='already exists'):
        main()
    assert report.read_text() == 'original'


def test_runtime_observer_queries_sensor_acquisition_clock():
    assert source_clock_query('{node=~"pi"}') == (
        'min by(node)(pifanctl_temperature_observed_timestamp_seconds{node=~"pi"})')
