#!/usr/bin/env python3
"""Evaluate recorded thermal stability under explicit, versioned policies."""

import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Observation times must include a timezone")
    return parsed.timestamp()


POLICIES = ('v1-3c', 'legacy-1c')


def evaluate(rows, target=55.0, duration=120.0, policy='v1-3c'):
    """Apply approved bounds while preserving the original legacy verdict."""
    if policy not in POLICIES:
        raise ValueError('Unknown thermal acceptance policy')
    if not math.isfinite(target) or not math.isfinite(duration) or duration <= 0:
        raise ValueError("Target and positive duration must be finite")
    samples = []
    invalid = 0
    source_identity = True
    for row in rows:
        if not str(row.get("phase", "")).startswith("load-"):
            continue
        try:
            values = [float(row[name]) for name in (
                "hottest_c", "requested_duty_percent", "max_source_age_s",
                "worker_heartbeat_age_s")]
            if not all(math.isfinite(value) for value in values):
                raise ValueError("Non-finite telemetry")
            temperature, duty, age, heartbeat = values
            observed = timestamp(row["source_observed_at_utc"])
            collected = timestamp(row["timestamp_utc"])
            if row.get("member_temperatures_json"):
                members = json.loads(row["member_temperatures_json"])
            else:
                members = {name: float(row[name]) for name in row
                           if re.fullmatch(r"raspi_\d+_c", name)}
            if not isinstance(members, dict) or not members or not all(math.isfinite(float(v)) for v in members.values()):
                raise ValueError("Incomplete member temperatures")
            if not math.isclose(max(float(v) for v in members.values()), temperature, abs_tol=0.001):
                raise ValueError("Rack maximum disagrees with member temperatures")
            if row.get("member_observed_timestamps_json"):
                clocks = json.loads(row["member_observed_timestamps_json"])
                if not isinstance(clocks, dict) or set(clocks) != set(members):
                    raise ValueError("Member source identities are incomplete")
                if any(not math.isfinite(float(t)) or not 0 <= collected-float(t) <= 25
                       for t in clocks.values()):
                    raise ValueError("Stale or future member telemetry")
                if not math.isclose(min(float(t) for t in clocks.values()), observed, abs_tol=1):
                    raise ValueError("Composite source clock disagrees with member clocks")
            else:
                source_identity = False
            healthy = (0 <= duty <= 100 and 0 <= age <= 25 and
                       0 <= heartbeat <= 15 and 0 <= collected-observed <= 25)
            samples.append((observed, temperature, duty, healthy))
        except (ValueError, KeyError, TypeError, json.JSONDecodeError):
            invalid += 1
            samples.append((0, 0, 0, False))

    def longest(spread, low, high):
        best = 0.0
        for index, first in enumerate(samples):
            window = []
            previous = None
            for sample in samples[index:]:
                at, temp, duty, healthy = sample
                if not healthy or not low <= temp <= high:
                    break
                if previous is not None and not 0 < at-previous <= 20:
                    break
                window.append(sample)
                temps = [x[1] for x in window]
                duties = [x[2] for x in window]
                if max(temps)-min(temps) > spread+1e-9 or max(duties)-min(duties) > 5:
                    break
                if len(window) >= 8:
                    best = max(best, at-first[0])
                previous = at
        return round(best, 2)

    legacy_strict = longest(1.0, target-1, target+1)
    legacy_band = longest(2.0, target-1, target+1)
    legacy = policy == 'legacy-1c'
    low, high, span = (target-1, target+1, 1.0) if legacy else (target-1, target+2, 3.0)
    stability = legacy_strict if legacy else longest(span, low, high)
    result = {
        "target_celsius": target,
        "required_duration_seconds": duration,
        "maximum_temperature_span_celsius": span,
        "maximum_duty_span_percentage_points": 5.0,
        "load_observations": len(samples),
        "invalid_observations": invalid,
        "target_band_seconds": legacy_band if legacy else longest(3.0, low, high),
        "strict_stability_seconds": legacy_strict,
        "member_source_identity_recorded": source_identity and bool(samples),
        "thermal_stability_passed": stability >= duration and invalid == 0 and
                                    source_identity and bool(samples),
    }
    if not legacy:
        result.update(policy=policy, target_band_lower_celsius=low,
                      target_band_upper_celsius=high, stability_seconds=stability,
                      minimum_observations=8, maximum_source_gap_seconds=20,
                      legacy_target_band_seconds=legacy_band,
                      legacy_strict_stability_seconds=legacy_strict)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", type=Path)
    parser.add_argument("--target", type=float, default=55.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", choices=POLICIES, default="v1-3c")
    args = parser.parse_args()
    with args.csv.open(newline="") as stream:
        result = evaluate(list(csv.DictReader(stream)), args.target, policy=args.policy)
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0 if result["thermal_stability_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
