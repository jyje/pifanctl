"""Summarize alternating GPIO observations without claiming calibrated PWM."""
import json
import math
import statistics
import sys


def analyze(events):
    if len(events) < 3:
        raise ValueError('At least three transitions required')
    previous = None
    for stamp, level in events:
        if not isinstance(stamp, (int, float)) or not math.isfinite(stamp) or stamp < 0:
            raise ValueError('Invalid event clock')
        if level not in (0, 1):
            raise ValueError('Invalid level')
        if previous and (stamp <= previous[0] or level == previous[1]):
            raise ValueError('Events must have increasing clocks and alternating levels')
        previous = stamp, level
    cycles = []
    for i in range(len(events) - 2):
        if events[i][1] == 1:
            period = events[i + 2][0] - events[i][0]
            cycles.append((period, 100 * (events[i + 1][0] - events[i][0]) / period))
    if not cycles:
        raise ValueError('No complete rising-edge cycle')
    return {'complete_cycles': len(cycles),
            'median_cycle_hz': 1 / statistics.median(p for p, _ in cycles),
            'median_observed_high_percent': statistics.median(d for _, d in cycles),
            'cycle_min_seconds': min(p for p, _ in cycles),
            'cycle_max_seconds': max(p for p, _ in cycles),
            'period_p95_seconds': sorted(p for p, _ in cycles)[int(.95 * len(cycles))],
            'fan_connector_measured': False, 'voltage_measured': False}


if __name__ == '__main__':
    with open(sys.argv[1]) as f:
        report = json.load(f)
    print(json.dumps(analyze(report['pwm_transitions']), indent=2))
