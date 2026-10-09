import csv
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('rpm_report', 'scripts/build_rpm_acceptance.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record_file(tmp_path, change=None):
    row = dict(elapsed_seconds=0, commanded_duty_percent=50, observed_rpm=900, pulse_count=150)
    row.update({'member_%02d_celsius' % i: 45 for i in range(1, 5)})
    row.update(change or {})
    path = tmp_path / 'samples.csv'
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row), lineterminator='\n')
        writer.writeheader(); writer.writerow(row)
    return path


def test_observed_zero_is_a_valid_complete_count(tmp_path):
    rows = module.read_samples(record_file(tmp_path, {'observed_rpm': 0, 'pulse_count': 0}))
    assert rows[0]['observed_rpm'] == 0


@pytest.mark.parametrize('change', [
    {'elapsed_seconds': -1}, {'commanded_duty_percent': 101},
    {'observed_rpm': float('nan')}, {'member_01_celsius': float('inf')},
    {'observed_rpm': 901}, {'pulse_count': 150.5}])
def test_invalid_measurements_are_rejected(tmp_path, change):
    with pytest.raises(ValueError): module.read_samples(record_file(tmp_path, change))
