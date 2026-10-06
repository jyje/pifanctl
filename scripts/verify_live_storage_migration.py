#!/usr/bin/env python3
"""Exercise an archived storage round trip with an existing live rack worker.

The Application must be in manual sync mode. This does not change images,
topology, PWM settings, workloads or finalizers. Failure state is archived.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import yaml

from verify_storage_migration import GROUP, KINDS, identity, rewrite

ROOT = Path(__file__).resolve().parents[1]


def healthy(resources, fan_name, zone_name, now):
    objects = {(o['kind'], o['metadata']['name']): o for o in resources}
    if set(objects) != {('Fan', fan_name), ('CoolingZone', zone_name)}:
        raise RuntimeError('Expected exactly the archived rack Fan and CoolingZone')
    for obj in objects.values():
        if obj['metadata'].get('deletionTimestamp') or not any(
                c.get('type') == 'Ready' and c.get('status') == 'True'
                and c.get('observedGeneration') == obj['metadata'].get('generation')
                for c in obj.get('status', {}).get('conditions', [])):
            raise RuntimeError('Rack resource is not Ready or is retiring')
    fan, zone = objects[('Fan', fan_name)], objects[('CoolingZone', zone_name)]
    for stamp, limit in ((fan['status']['heartbeatTime'], 20),
                         (zone['status']['temperatureObservedAt'], 30)):
        age = now - datetime.fromisoformat(stamp.replace('Z', '+00:00')).timestamp()
        if not 0 <= age <= limit:
            raise RuntimeError(f'Stale or future rack telemetry: age {age:.3f}s, limit {limit}s')
    if not 0 <= fan['status']['dutyPercent'] <= 100:
        raise RuntimeError('Invalid requested duty')
    if zone['status'].get('memberCount') != 4 or zone['status'].get('missingNodeNames'):
        raise RuntimeError('Expected four resolved rack members')
    if not zone['status']['temperatureCelsius'] < 65:
        raise RuntimeError('Rack temperature exceeds migration guardrail')
    return fan


def manual(app):
    policy = app['spec'].get('syncPolicy', {})
    if 'automated' in policy:
        raise RuntimeError('Application must be explicitly in manual sync mode')
    if app.get('operation') or app.get('status', {}).get('operationState', {}).get('phase') == 'Running':
        raise RuntimeError('An Application operation is still active')


def worker_ready(pod):
    statuses = pod.get('status', {}).get('containerStatuses', [])
    return bool(statuses) and not pod['metadata'].get('deletionTimestamp') and all(s.get('ready') for s in statuses)


def restore_definitions(archive, originals):
    raw = (archive / 'baseline.json').read_bytes()
    hashes = json.loads((archive / 'SHA256SUMS.json').read_text())
    if hashlib.sha256(raw).hexdigest() != hashes['baseline.json']:
        raise RuntimeError('Restore archive checksum mismatch')
    restore = json.loads(raw)['crds']
    for plural in KINDS:
        if restore[plural]['metadata']['uid'] != originals[plural]['metadata']['uid']:
            raise RuntimeError('Restore archive CRD identity mismatch')
        versions = restore[plural]['spec']['versions']
        if (restore[plural]['status']['storedVersions'] != ['v1alpha1']
                or len(versions) != 1 or versions[0]['name'] != 'v1alpha1'
                or not versions[0]['storage'] or not versions[0]['served']):
            raise RuntimeError('Restore archive must contain original alpha storage')
    return restore


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context', required=True)
    p.add_argument('--application', required=True)
    p.add_argument('--fan', required=True)
    p.add_argument('--zone', required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--mode', choices=('roundtrip', 'promote', 'reverse'), default='roundtrip')
    p.add_argument('--restore-archive', type=Path)
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    if not args.execute or args.context != 'microk8s':
        raise SystemExit('Explicit --execute and --context microk8s are required')
    if args.report.exists():
        raise SystemExit('Report already exists: retain it and choose a new path')
    os.umask(0o077)
    prefix = ['kubectl', '--context', args.context, '--request-timeout=20s']

    def cmd(*parts, body=None, check=True):
        r = subprocess.run(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                           text=True, capture_output=True, timeout=30)
        if check and r.returncode:
            raise RuntimeError(r.stderr)
        return r

    def get(*parts):
        return json.loads(cmd('get', *parts, '-o', 'json').stdout)

    app = get('application', args.application, '-n', 'argocd')
    manual(app)
    ns = app['spec']['destination']['namespace']
    originals = {k: get('crd', k + '.' + GROUP) for k in KINDS}
    expected_storage = 'v1' if args.mode == 'reverse' else 'v1alpha1'
    if any(o['status']['storedVersions'] != [expected_storage] for o in originals.values()):
        raise RuntimeError('Unexpected initial storage history')
    restore = originals
    if args.mode == 'reverse':
        if not args.restore_archive:
            raise RuntimeError('Reverse migration requires the original archive')
        restore = restore_definitions(args.restore_archive, originals)
    deadline = time.monotonic() + 30
    while True:
        inventory = {k: json.loads(cmd('get', '--raw=/apis/' + GROUP + '/v1alpha1/' + k).stdout)['items']
                     for k in KINDS}
        try:
            fan = healthy([o for items in inventory.values() for o in items], args.fan, args.zone, time.time())
            break
        except RuntimeError as error:
            if not str(error).startswith('Stale or future') or time.monotonic() >= deadline:
                raise
            # Before mutations only, wait for a fresh source observation.
            time.sleep(2)
    pod = get('pod', fan['status']['workerPodName'], '-n', ns)
    if not worker_ready(pod):
        raise RuntimeError('Original worker is not Ready')
    args.archive.mkdir(mode=0o700, parents=True, exist_ok=False)
    baseline = {'application': app, 'crds': originals, 'resources': inventory, 'worker': pod}
    raw = json.dumps(baseline, indent=2) + '\n'
    (args.archive / 'baseline.json').write_text(raw)
    (args.archive / 'SHA256SUMS.json').write_text(json.dumps(
        {'baseline.json': hashlib.sha256(raw.encode()).hexdigest()}, indent=2) + '\n')
    report = {'context': args.context, 'mode': args.mode,
              'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'passed': False, 'checks': [], 'samples': []}

    def observe(label):
        manual(get('application', args.application, '-n', 'argocd'))
        started = time.monotonic()
        while True:
            # The alpha endpoint stays served through both directions. Avoid
            # kubectl's cached preferred-version discovery after restoration.
            items = [obj for plural in KINDS for obj in json.loads(cmd(
                'get', '--raw=/apis/' + GROUP + '/v1alpha1/' + plural).stdout)['items']]
            try:
                current = healthy(items, args.fan, args.zone, time.time())
                break
            except RuntimeError as error:
                if not str(error).startswith('Stale or future') or time.monotonic() - started >= 35:
                    raise
                # CR status is published at most every 30 seconds. Wait for
                # a genuinely fresh snapshot without relaxing the age limit.
                time.sleep(2)
        for obj in items:
            plural = 'fans' if obj['kind'] == 'Fan' else 'coolingzones'
            if identity(obj) != identity(inventory[plural][0]):
                raise RuntimeError('Rack identity or topology changed during migration')
        worker = get('pod', current['status']['workerPodName'], '-n', ns)
        if worker['metadata']['uid'] != pod['metadata']['uid']:
            raise RuntimeError('Storage migration replaced the original worker')
        if not worker_ready(worker):
            raise RuntimeError('Worker readiness was lost')
        peers = get('pods', '-n', ns, '-l', 'app.kubernetes.io/component=worker')['items']
        if len(peers) != 1 or peers[0]['metadata']['uid'] != pod['metadata']['uid']:
            raise RuntimeError('Expected one original worker')
        definitions = {}
        for plural, original in originals.items():
            definition = get('crd', plural + '.' + GROUP)
            if definition['metadata']['uid'] != original['metadata']['uid']:
                raise RuntimeError('A CRD identity changed')
            definitions[plural] = {'uid': definition['metadata']['uid'],
                                   'storedVersions': definition['status']['storedVersions'],
                                   'storage': [v['name'] for v in definition['spec']['versions'] if v['storage']]}
            expected = {'v1_storage_rewritten': 'v1', 'alpha_storage_restored': 'v1alpha1'}.get(label)
            if expected and (definitions[plural]['storedVersions'] != [expected] or definitions[plural]['storage'] != [expected]):
                raise RuntimeError('Storage declaration/history does not match the completed rewrite')
            if label == 'alpha_storage_restored' and definition['spec'] != restore[plural]['spec']:
                raise RuntimeError('Original alpha definition was not restored')
        report['samples'].append({'stage': label, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
                                  'resources': items, 'worker_uid': worker['metadata']['uid'],
                                  'definitions': definitions, 'fresh_snapshot_wait_seconds': time.monotonic() - started})

    promoted = False
    try:
        observe('baseline')
        if args.mode != 'reverse':
            for plural in KINDS:
                definition = yaml.safe_load((ROOT / 'charts/pifanctl-operator/crds' / (plural + '.yaml')).read_text())
                # Explicit spec replacement in a frozen migration window avoids
                # stealing arbitrary SSA ownership or overwriting current metadata.
                cmd('patch', 'crd', plural + '.' + GROUP, '--type=merge',
                    '-p', json.dumps({'spec': definition['spec'], 'metadata': {
                        'annotations': definition['metadata']['annotations']}}))
            promoted = True
            cmd('wait', '--for=condition=Established', *['crd/' + k + '.' + GROUP for k in KINDS], '--timeout=30s')
            observe('dual_api_installed')
            report['checks'].append({'name': 'dual_api_installed', 'passed': True})
            rewritten = rewrite(cmd, 'v1', inventory)
            observe('v1_storage_rewritten')
            report['checks'].append({'name': 'complete_v1_rewrite', 'passed': True, 'resources': rewritten})
        if args.mode in ('roundtrip', 'reverse'):
            for plural in KINDS:
                current = get('crd', plural + '.' + GROUP)
                spec = deepcopy(current['spec'])
                for version in spec['versions']:
                    version['storage'] = version['name'] == 'v1alpha1'
                cmd('patch', 'crd', plural + '.' + GROUP, '--type=merge', '-p', json.dumps({'spec': spec}))
            rewrite(cmd, 'v1alpha1', inventory)
            for plural, original in restore.items():
                cmd('patch', 'crd', plural + '.' + GROUP, '--type=merge',
                    '-p', json.dumps({'spec': original['spec']}))
            observe('alpha_storage_restored')
            report['checks'].append({'name': 'reverse_rewrite_and_definition_restore', 'passed': True})
        observe('final')
        report['checks'].append({'name': 'worker_uid_identity_readiness_preserved', 'passed': True})
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        report['dual_definitions_applied'] = promoted
        # Preserve the served endpoints and failure state for an inspected
        # rollback. Never delete definitions or clear finalizers on failure.
        raise
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
