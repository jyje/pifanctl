"""Thermal release evidence must satisfy the original measurement criteria."""

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
    result = evaluate(observations([54.55, 55.65] * 6 + [55]))
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
        result = evaluate(list(csv.DictReader(stream)))
    assert result["strict_stability_seconds"] == 75
    assert result["target_band_seconds"] == 144
    assert not result["thermal_stability_passed"]
    assert result == json.loads(path.with_name(path.stem + "-verification.json").read_text())


def test_nonfinite_target_is_rejected():
    with pytest.raises(ValueError, match="finite"):
        evaluate(observations(), target=float("nan"))
