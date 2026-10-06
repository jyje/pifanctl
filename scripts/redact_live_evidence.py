#!/usr/bin/env python3
"""Project private live trial reports into public measurements and check results.

Never publish complete Kubernetes objects, resource names/UIDs, IPs, service
URLs, configuration, arbitrary errors or credentials. Keep originals private.
"""
import argparse
from datetime import datetime
import json
import math
from pathlib import Path


def ready(obj):
    return any(c.get('type') == 'Ready' and c.get('status') == 'True'
               for c in obj.get('status', {}).get('conditions', []))


def timestamp(value):
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).isoformat()
    except (AttributeError, ValueError):
        raise ValueError('Invalid evidence timestamp') from None


def number(value):
    try:
        result = float(value)
        if not math.isfinite(result):
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise ValueError('Invalid numeric evidence') from None


def public_summary(raw):
    out = {'passed': raw.get('passed') is True}
    for key in ('started_at_utc', 'finished_at_utc'):
        if key in raw:
            out[key] = timestamp(raw[key])
    if 'minimum_hold_seconds' in raw:
        out['minimum_hold_seconds'] = number(raw['minimum_hold_seconds'])
    out.update({'visibility': 'public_redacted_summary', 'full_originals_excluded': True})
    samples = raw.get('samples', [])
    if 'mode' in raw:
        out['mode'] = raw['mode'] if raw['mode'] in ('roundtrip', 'promote', 'reverse') else 'unrecognized_mode'
        known = {'dual_api_installed', 'complete_v1_rewrite', 'reverse_rewrite_and_definition_restore',
                 'worker_uid_identity_readiness_preserved'}
        out['checks'] = [{'name': c['name'] if c['name'] in known else 'unrecognized_check',
                          'passed': c.get('passed') is True} for c in raw.get('checks', [])]
        first = samples[0] if samples else {}
        identities = {o['kind']: o['metadata']['uid'] for o in first.get('resources', []) if o['kind'] in ('Fan', 'CoolingZone')}
        worker = first.get('worker_uid')
        definitions = first.get('definitions', {})
        out['samples'] = []
        for sample in samples:
            objects = {o['kind']: o for o in sample.get('resources', []) if o['kind'] in ('Fan', 'CoolingZone')}
            stages = {'baseline', 'dual_api_installed', 'v1_storage_rewritten', 'alpha_storage_restored', 'final'}
            projected = {'stage': sample.get('stage') if sample.get('stage') in stages else 'unrecognized_stage'}
            if 'observed_at_utc' in sample:
                projected['observed_at_utc'] = timestamp(sample['observed_at_utc'])
            if 'fresh_snapshot_wait_seconds' in sample:
                projected['fresh_snapshot_wait_seconds'] = number(sample['fresh_snapshot_wait_seconds'])
            projected['worker_identity_unchanged'] = bool(worker) and sample.get('worker_uid') == worker
            projected['resource_identity_unchanged'] = {
                kind: obj['metadata']['uid'] == identities[kind] for kind, obj in objects.items()}
            projected['ready'] = {kind: ready(obj) for kind, obj in objects.items()}
            if 'Fan' in objects:
                duty = objects['Fan']['status'].get('dutyPercent')
                projected['requested_duty_percent'] = number(duty) if duty is not None else None
            if 'CoolingZone' in objects:
                status = objects['CoolingZone']['status']
                projected.update({k: number(status[k]) for k in ('memberCount', 'temperatureCelsius') if k in status})
                if 'temperatureObservedAt' in status:
                    projected['temperatureObservedAt'] = timestamp(status['temperatureObservedAt'])
            projected['definitions'] = {plural: {
                'identity_unchanged': definition['uid'] == definitions[plural]['uid'],
                'storage': [v for v in definition['storage'] if v in ('v1', 'v1alpha1')],
                'stored_versions': [v for v in definition['storedVersions'] if v in ('v1', 'v1alpha1')]}
                for plural, definition in sample.get('definitions', {}).items() if plural in ('fans', 'coolingzones')}
            out['samples'].append(projected)
        if raw.get('error'):
            out['failure_category'] = 'strict_snapshot_freshness_limit'
    else:
        names = sorted(samples[0]['member_temperatures']) if samples else []
        aliases = {name: 'node-' + chr(ord('a') + index) for index, name in enumerate(names)}
        out['samples'] = []
        for sample in samples:
            direct = sample['worker_report']
            fan_states = list(direct.get('fans', {}).values())
            out['samples'].append({
                'observed_at_utc': timestamp(sample['observed_at_utc']), 'hold_seconds': number(sample['hold_seconds']),
                'worker_ready': direct.get('ready') is True, 'worker_heartbeat_time': number(direct['heartbeatTime']),
                'requested_duty_percent': number(fan_states[0]['dutyPercent']) if len(fan_states) == 1 else None,
                'member_temperatures': {aliases[k]: number(v) for k, v in sample['member_temperatures'].items()},
                'member_source_times': {aliases[k]: number(v) for k, v in sample['member_source_times'].items()},
            })
        app = raw.get('final_application', samples[-1].get('application', {}) if samples else {})
        status = app.get('status', {})
        out['final_gitops'] = {}
        for key, value, choices in [
            ('sync', status.get('sync', {}).get('status'), ('Synced', 'OutOfSync', 'Unknown')),
            ('health', status.get('health', {}).get('status'), ('Healthy', 'Progressing', 'Degraded', 'Missing', 'Suspended', 'Unknown')),
            ('phase', status.get('operationState', {}).get('phase'), ('Succeeded', 'Failed', 'Error', 'Running', 'Terminating')),
        ]:
            out['final_gitops'][key] = value if value in choices else None
        out['final_gitops']['automatic_self_heal'] = app.get('spec', {}).get('syncPolicy', {}).get('automated', {}).get('selfHeal') is True
        out['final_stored_versions'] = {o['spec']['names']['kind']: [v for v in o['status']['storedVersions'] if v in ('v1', 'v1alpha1')]
                                       for o in raw.get('final_crds', []) if o['spec']['names']['kind'] in ('Fan', 'CoolingZone')}
        out['completed_guards'] = ['current_source_and_revision', 'single_worker_and_no_legacy_controller',
                                   'resource_identity_and_spec', 'image_digest', 'actuator_node_identity',
                                   'plan_hash', 'no_worker_credentials', 'shared_host_lock',
                                   'direct_worker_heartbeat', 'every_member_source_clock'] if out['passed'] else []
        if raw.get('error'):
            out['failure_category'] = 'observer_request_failed'
    return out


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    args = p.parse_args()
    raw = json.loads(args.input.read_text())
    args.output.write_text(json.dumps(public_summary(raw), indent=2) + '\n')


if __name__ == '__main__':
    main()
