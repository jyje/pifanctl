"""Thermal release evidence must satisfy the explicit versioned measurement criteria."""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from verify_thermal_acceptance import evaluate


def observations(temperatures=None):
    temperatures = temperatures or [55.0] * 13
    rows = []
    for index, temperature in enumerate(temperatures):
        time = 1700000000 + index * 10
        iso = datetime.fromtimestamp(time, timezone.utc).isoformat()
        rows.append({
            "phase": "load-1cpu", "timestamp_utc": iso,
            "source_observed_at_utc": iso, "hottest_c": temperature,
            "requested_duty_percent": 50, "max_source_age_s": 0,
            "worker_heartbeat_age_s": 1,
            "member_temperatures_json": json.dumps({"node-a": temperature, "node-b": 40}),
            "member_observed_timestamps_json": json.dumps({"node-a": time, "node-b": time}),
        })
    return rows


def test_accepts_full_fresh_stability_interval():
    result = evaluate(observations([54.5, 55.5] * 6 + [55]))
    assert result["thermal_stability_passed"]
    assert result["strict_stability_seconds"] == 120


def test_band_hold_does_not_replace_one_degree_span():
    result = evaluate(observations([54.55, 55.65] * 6 + [55]), policy="legacy-1c")
    assert result["target_band_seconds"] == 120
    assert not result["thermal_stability_passed"]


@pytest.mark.parametrize("field,value", [
    ("hottest_c", "nan"), ("requested_duty_percent", 101),
    ("max_source_age_s", 26), ("worker_heartbeat_age_s", 16),
    ("member_observed_timestamps_json", json.dumps({"node-a": 1700000000})),
    ("member_observed_timestamps_json", json.dumps({"node-a": 1, "node-b": 1})),
    ("member_temperatures_json", "[]"),
    ("member_observed_timestamps_json", "[]"),
])
def test_invalid_or_unhealthy_samples_break_the_interval(field, value):
    rows = observations()
    rows[6][field] = value
    assert not evaluate(rows)["thermal_stability_passed"]


def test_missing_source_identity_is_not_certified():
    rows = observations()
    for row in rows:
        del row["member_observed_timestamps_json"]
    result = evaluate(rows)
    assert result["strict_stability_seconds"] == 120
    assert not result["member_source_identity_recorded"]
    assert not result["thermal_stability_passed"]


def test_duplicate_source_clock_cannot_extend_stability():
    rows = observations()
    for row in rows:
        row["source_observed_at_utc"] = rows[0]["source_observed_at_utc"]
    assert not evaluate(rows)["thermal_stability_passed"]


def test_checked_in_trial_is_partial_evidence():
    import csv
    path = Path(__file__).resolve().parents[1] / "docs/v1/thermal-stability-55c-2026-10-06.csv"
    with path.open(newline="") as stream:
        result = evaluate(list(csv.DictReader(stream)), policy="legacy-1c")
    assert result["strict_stability_seconds"] == 75
    assert result["target_band_seconds"] == 144
    assert not result["thermal_stability_passed"]
    assert result == json.loads(path.with_name(path.stem + "-verification.json").read_text())


def test_nonfinite_target_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        evaluate(observations(), target=float("nan"))


def test_approved_three_degree_policy_uses_fixed_asymmetric_bounds():
    result = evaluate(observations([54, 57] * 6 + [55]))
    assert result['policy'] == 'v1-3c'
    assert result['target_band_lower_celsius'] == 54
    assert result['target_band_upper_celsius'] == 57
    assert result['maximum_temperature_span_celsius'] == 3
    assert result['stability_seconds'] == 120
    assert result['thermal_stability_passed']
    assert result['legacy_strict_stability_seconds'] == 0


@pytest.mark.parametrize('temperature', [53.99, 57.01])
def test_three_degree_window_cannot_shift_to_fit_samples(temperature):
    result = evaluate(observations([temperature] * 13))
    assert not result['thermal_stability_passed']


def test_fewer_than_eight_samples_cannot_pass_even_with_duration():
    rows = observations()[:7]
    for i, r in enumerate(rows):
        time = 1700000000 + i * 20
        iso = datetime.fromtimestamp(time, timezone.utc).isoformat()
        r.update(timestamp_utc=iso, source_observed_at_utc=iso,
                 member_observed_timestamps_json=json.dumps({'node-a': time, 'node-b': time}))
    assert not evaluate(rows)['thermal_stability_passed']


def test_approval_does_not_relax_duty_variation():
    rows = observations()
    rows[6]['requested_duty_percent'] = 55.01
    assert not evaluate(rows)['thermal_stability_passed']


def test_source_gap_breaks_continuity_under_approved_policy():
    rows = observations()
    for r in rows[6:]:
        at = datetime.fromisoformat(r['timestamp_utc']).timestamp()+21
        iso = datetime.fromtimestamp(at, timezone.utc).isoformat()
        r.update(timestamp_utc=iso, source_observed_at_utc=iso,
                 member_observed_timestamps_json=json.dumps({'node-a': at, 'node-b': at}))
    assert not evaluate(rows)['thermal_stability_passed']


def test_unknown_policy_rejected():
    with pytest.raises(ValueError, match='Unknown'):
        evaluate(observations(), policy='unbounded')


def test_actual_50c_reassessment_preserves_both_verdicts():
    import csv
    path = Path(__file__).resolve().parents[1] / 'docs/v1/thermal-fixed-250m-50c-2026-10-07.csv'
    with path.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    original = evaluate(rows, target=50, policy='legacy-1c')
    approved = evaluate(rows, target=50)
    assert original == json.loads(path.with_suffix('.json').read_text())['acceptance']
    assert not original['thermal_stability_passed']
    assert approved['thermal_stability_passed']
    assert approved['stability_seconds'] == 140.24
    assert approved == json.loads(path.with_name(path.stem+'-reassessment.json').read_text())['acceptance']
    assert approved['strict_stability_seconds'] == 0
    assert approved['invalid_observations'] == 0
    assert approved['member_source_identity_recorded']


@pytest.mark.parametrize('policy,expected', [('v1-3c', 0), ('legacy-1c', 1)])
def test_cli_reproduces_approved_and_original_verdicts(monkeypatch, capsys, policy, expected):
    from verify_thermal_acceptance import main
    path = Path(__file__).resolve().parents[1] / 'docs/v1/thermal-fixed-250m-50c-2026-10-07.csv'
    monkeypatch.setattr(sys, 'argv', ['verify', str(path), '--target', '50', '--policy', policy])
    assert main() == expected
    assert json.loads(capsys.readouterr().out)['thermal_stability_passed'] is (expected == 0)



def test_rounding_cannot_certify_less_than_120_seconds():
    rows = observations()
    for i, row in enumerate(rows):
        iso = datetime.fromtimestamp(1700000000+i*119.999/12, timezone.utc).isoformat()
        at = datetime.fromisoformat(iso).timestamp()
        row.update(timestamp_utc=iso, source_observed_at_utc=iso,
                   member_observed_timestamps_json=json.dumps({'node-a': at, 'node-b': at}))
    result = evaluate(rows)
    assert result['stability_seconds'] == 120
    assert result['stability_seconds_unrounded'] < 120
    assert not result['thermal_stability_passed']
