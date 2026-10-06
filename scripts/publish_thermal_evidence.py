#!/usr/bin/env python3
"""Publish anonymous thermal samples and reproducible measured figures."""
import argparse
import csv
from datetime import datetime
import json
import math
from pathlib import Path

from verify_thermal_acceptance import evaluate


def project(rows):
    expected = sorted(json.loads(rows[0]['member_temperatures_json'])) if rows else []
    aliases = {name: 'node-'+chr(97+i) for i, name in enumerate(expected)}
    public = []
    for row in rows:
        values = json.loads(row['member_temperatures_json'])
        clocks = json.loads(row['member_observed_timestamps_json'])
        if sorted(values) != expected or sorted(clocks) != expected:
            raise ValueError('Inconsistent member inventory')
        item = {}
        for key in ('timestamp_utc', 'source_observed_at_utc'):
            item[key] = datetime.fromisoformat(row[key]).isoformat()
        if row['phase'] not in ('baseline', 'load-fixed', 'cooldown'):
            raise ValueError('Unknown measurement phase')
        item['phase'] = row['phase']
        for key in ('elapsed_s', 'hottest_c', 'requested_duty_percent',
                    'max_source_age_s', 'worker_heartbeat_age_s'):
            item[key] = float(row[key])
            if not math.isfinite(item[key]):
                raise ValueError('Non-finite measurement')
        for key, source in (('member_temperatures_json', values), ('member_observed_timestamps_json', clocks)):
            mapped = {aliases[name]: float(value) for name, value in source.items()}
            if not all(math.isfinite(value) for value in mapped.values()):
                raise ValueError('Non-finite member measurement')
            item[key] = json.dumps(mapped, sort_keys=True)
        public.append(item)
    return public


def figure(rows, target, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    x = [float(r['elapsed_s'])/60 for r in rows]
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True,
                             gridspec_kw={'height_ratios': [2, 1, 1]})
    for node in sorted(json.loads(rows[0]['member_temperatures_json'])):
        axes[0].plot(x, [json.loads(r['member_temperatures_json'])[node] for r in rows], label=node, linewidth=1.5)
    axes[0].axhspan(target-1, target+1, color='#ed3158', alpha=0.08, label='Target observation band')
    axes[0].axhline(target, color='#ed3158', linestyle='--', linewidth=0.8)
    axes[0].set_ylabel('CPU temperature (C)')
    axes[0].legend(ncol=3, fontsize=8, loc='lower right')
    axes[1].plot(x, [r['requested_duty_percent'] for r in rows], color='#218b82')
    axes[1].set_ylabel('Requested duty (%)')
    axes[1].set_ylim(0, 100)
    axes[2].plot(x, [r['max_source_age_s'] for r in rows], label='Oldest member acquisition', color='#3478b9')
    axes[2].plot(x, [r['worker_heartbeat_age_s'] for r in rows], label='Worker heartbeat', color='#e87544')
    axes[2].set_ylabel('Age (seconds)')
    axes[2].set_xlabel('Elapsed time (minutes)')
    axes[2].legend(fontsize=8)
    load = [float(r['elapsed_s'])/60 for r in rows if r['phase']=='load-fixed']
    if load:
        for ax in axes:
            ax.axvspan(min(load), max(load), color='#7f63ad', alpha=0.06)
            ax.axvline(min(load), color='#7f63ad', linestyle=':', linewidth=0.8)
            ax.axvline(max(load), color='#7f63ad', linestyle=':', linewidth=0.8)
    for ax in axes:
        ax.grid(alpha=0.2)
    fig.suptitle('Fixed-load thermal acceptance: measured response', fontweight='bold')
    fig.text(0.5, 0.01, 'Shading spans sampled load observations. Duty is a command, not RPM or measured voltage.',
             ha='center', fontsize=8)
    fig.tight_layout(rect=(0, 0.035, 1, 0.96))
    for suffix in ('.svg', '.png'):
        fig.savefig(output.with_suffix(suffix), dpi=180)
    plt.close(fig)


def execution(log):
    value = json.loads(log)
    reason = value['reason']
    if reason not in ('local_temperature_cutoff', 'local_duration_deadline'):
        raise ValueError('Unknown local guard result')
    elapsed, cpu = float(value['elapsed_seconds']), float(value['cpu_seconds'])
    if not math.isfinite(elapsed) or not math.isfinite(cpu) or elapsed <= 0 or cpu < 0:
        raise ValueError('Invalid load execution counters')
    return {'reason': reason, 'elapsed_seconds': elapsed, 'cpu_seconds': cpu,
            'average_consumed_vcpu': cpu / elapsed}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output-prefix', type=Path, required=True)
    args = p.parse_args()
    paths = [args.output_prefix.with_suffix(s) for s in ('.csv', '.json', '.svg', '.png')]
    if any(path.exists() for path in paths):
        raise SystemExit('Output exists: retain prior evidence and choose a new prefix')
    with (args.archive/'samples.csv').open(newline='') as stream:
        public = project(list(csv.DictReader(stream)))
    raw = json.loads((args.archive/'report.json').read_text())
    acceptance = evaluate(public, raw['target_celsius'])
    report = {'visibility': 'public_anonymous_measurements', 'full_originals_excluded': True,
              'target_celsius': raw['target_celsius'], 'cpu_millicores': raw['cpu_millicores'],
              'collector_passed': raw['collector_passed'], 'cleanup_verified': raw['cleanup_verified'],
              'cooldown_recorded': raw.get('cooldown_recorded', False), 'acceptance': acceptance,
              'load_stop_reason': raw['load_stop_reason'] if raw['load_stop_reason'] in
              ('maximum_load_duration', 'local_guard_or_deadline', 'remote_temperature_cutoff',
               'strict_stability_observed', 'not_started') else 'collector_failure',
              'started_at_utc': datetime.fromisoformat(raw['started_at_utc']).isoformat(),
              'finished_at_utc': datetime.fromisoformat(raw['finished_at_utc']).isoformat()}
    log = args.archive/'load.log'
    if log.exists() and log.read_text().strip():
        report['load_execution'] = execution(log.read_text())
    if (args.archive/'load-process-cpu.json').exists():
        value = float(json.loads((args.archive/'load-process-cpu.json').read_text())['process_cpu_seconds'])
        if not math.isfinite(value) or value < 0:
            raise ValueError('Invalid process CPU counter')
        report['load_process_cpu_seconds_at_intermediate_observation'] = value
    with paths[0].open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(public[0]))
        writer.writeheader()
        writer.writerows(public)
    paths[1].write_text(json.dumps(report, indent=2)+'\n')
    figure(public, raw['target_celsius'], args.output_prefix)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
