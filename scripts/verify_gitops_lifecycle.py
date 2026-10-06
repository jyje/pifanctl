#!/usr/bin/env python3
"""Verify staged Argo CD installation and retirement with simulated I/O in kind."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import time

from verify_runtime_lifecycle import fan, ready, regulating

APP = 'pifanctl-release'
NS = 'pifanctl-release'
ARGO_NS = 'argocd'
FANS = ('gitops-fan-a', 'gitops-fan-b')
ZONE = 'gitops-zone'
CRDS = ('fans.pifanctl.jyje.online', 'coolingzones.pifanctl.jyje.online')


def application(revision, resources):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Use an immutable full Git commit SHA')
    return {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Application',
            'metadata': {'name': APP, 'namespace': ARGO_NS,
                         'finalizers': ['resources-finalizer.argocd.argoproj.io/background']},
            'spec': {'project': 'default',
                     'source': {'repoURL': 'https://github.com/jyje/pifanctl',
                                'targetRevision': revision, 'path': 'charts/pifanctl-operator',
                                'helm': {'releaseName': APP, 'valuesObject': {
                                    'image': {'repository': 'pifanctl-runtime-lab', 'tag': 'alpha6', 'pullPolicy': 'Never'},
                                    'agent': {'mode': 'reuse'}, 'networkPolicy': {'enabled': False},
                                    'extraResources': deepcopy(resources)}}},
                     'destination': {'namespace': NS, 'server': 'https://kubernetes.default.svc'},
                     'syncPolicy': {'automated': {'prune': True, 'selfHeal': True},
                                    'syncOptions': ['CreateNamespace=true', 'ServerSideApply=true',
                                                    'PrunePropagationPolicy=background', 'PruneLast=true']}}}


def synced_healthy(obj):
    status = obj.get('status', {})
    source = obj.get('spec', {}).get('source')
    sync = status.get('sync', {})
    result = status.get('operationState', {}).get('syncResult', {})
    return (isinstance(source, dict) and bool(source)
            and sync.get('comparedTo', {}).get('source') == source
            and result.get('source') == source
            and sync.get('revision') == source.get('targetRevision')
            and result.get('revision') == source.get('targetRevision')
            and sync.get('status') == 'Synced'
            and status.get('health', {}).get('status') == 'Healthy'
            and status.get('operationState', {}).get('phase') == 'Succeeded'
            and not any(c.get('type', '').endswith('Error') for c in status.get('conditions', [])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kubeconfig', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--logs', type=Path, required=True)
    parser.add_argument('--archive-dir', type=Path, required=True)
    args = parser.parse_args()
    prefix = ['kubectl', '--kubeconfig', str(args.kubeconfig)]

    def cmd(*parts, body=None, check=True):
        result = subprocess.run(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                                capture_output=True, text=True, timeout=45)
        if check and result.returncode:
            raise RuntimeError(result.stderr)
        return result

    def get(*parts):
        return json.loads(cmd('get', *parts, '-o', 'json').stdout)

    def absent(*parts):
        result = cmd('get', *parts, check=False)
        return result.returncode != 0 and 'NotFound' in result.stderr

    context = cmd('config', 'current-context').stdout.strip()
    if context != 'kind-pifanctl-release':
        raise SystemExit('Refusing GitOps lab outside kind-pifanctl-release')
    if not absent('application', APP, '-n', ARGO_NS):
        raise SystemExit('Application already exists: inspect instead of restarting a trial')
    if not all(absent('crd', name) for name in CRDS):
        raise SystemExit('Initial ordering trial requires both pifanctl CRDs to be absent')
    nodes = get('nodes')['items']
    node = nodes[0]['metadata']['name']
    controller = get('statefulset', 'argocd-application-controller', '-n', ARGO_NS)
    argo_image = controller['spec']['template']['spec']['containers'][0]['image']
    if controller.get('status', {}).get('readyReplicas') != 1:
        raise SystemExit('Argo CD controller must be Ready before the trial')
    zone = {'apiVersion': 'pifanctl.jyje.online/v1', 'kind': 'CoolingZone',
            'metadata': {'name': ZONE}, 'spec': {'fanRefs': list(FANS), 'nodeNames': [node],
                                              'telemetry': {'source': 'local'}}}
    resources = [fan(node, FANS[0], 18), fan(node, FANS[1], 19), zone]
    desired = application(args.revision, resources)
    args.archive_dir.mkdir(parents=True, exist_ok=True)
    checks, snapshots, logs = [], [], []
    report = {'context': context, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'revision': args.revision, 'argo_image': argo_image,
              'kubernetes_versions': sorted({n['status']['nodeInfo']['kubeletVersion'] for n in nodes}),
              'simulated_io': True, 'hardware_acceptance': False, 'checks': checks,
              'snapshots': snapshots, 'passed': False}

    def wait(name, probe, timeout=360):
        start, deadline, last_error = time.monotonic(), time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            try:
                if probe():
                    checks.append({'name': name, 'passed': True, 'elapsed_seconds': round(time.monotonic()-start, 2)})
                    print(name + ': passed', flush=True)
                    return
            except (RuntimeError, KeyError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
                last_error = str(error)
            time.sleep(2)
        raise RuntimeError(name + ': timeout; ' + str(last_error))

    def app():
        return get('application', APP, '-n', ARGO_NS)

    def stage(label, objects):
        desired['spec']['source']['helm']['valuesObject']['extraResources'] = deepcopy(objects)
        (args.archive_dir / (label + '-desired.json')).write_text(json.dumps(desired, indent=2)+'\n')
        cmd('apply', '-f', '-', body=desired)
        wait(label + '_synced_healthy', lambda: synced_healthy(app()))
        live = app()
        (args.archive_dir / (label + '-observed.json')).write_text(json.dumps(live, indent=2)+'\n')
        snapshots.append({'stage': label, 'at_utc': datetime.now(timezone.utc).isoformat(),
                          'application': live})

    def worker():
        pods = get('pods', '-n', NS, '-l', 'app.kubernetes.io/component=worker')['items']
        if len(pods) != 1:
            raise RuntimeError('Expected one worker Pod for the declared actuator Node')
        return pods[0]

    def status():
        pod = worker()
        ip = pod['status'].get('podIP')
        if not ip:
            raise RuntimeError('Worker does not have an IP yet')
        code = 'import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://' + ip + ':9103/status",timeout=3))))'
        result = cmd('exec', '-n', NS, 'deploy/' + APP + '-operator', '--', 'python', '-c', code)
        value = json.loads(result.stdout)
        snapshots.append({'at_utc': datetime.now(timezone.utc).isoformat(), 'worker_uid': pod['metadata']['uid'],
                          'worker_status': value})
        return value

    def capture_logs(label):
        logs.append('## ' + label + '\n' + cmd('logs', '-n', NS, worker()['metadata']['name']).stdout)

    try:
        checks.append({'name': 'initial_crds_absent', 'passed': True})
        stage('initial', resources)
        wait('two_fans_regulating', lambda: regulating(status(), FANS, 47.5))
        wait('instance_conditions_ready', lambda: all(ready(get('fan', n)) for n in FANS)
             and ready(get('coolingzone', ZONE)))
        first_worker = worker()
        assert first_worker['spec']['nodeName'] == node
        assert first_worker['spec']['automountServiceAccountToken'] is False
        assert status()['nodeUID'] == nodes[0]['metadata']['uid']
        checks.append({'name': 'node_bound_worker_no_credentials', 'passed': True})
        crds = [get('crd', n) for n in CRDS]
        creation = min(datetime.fromisoformat(get('fan', n)['metadata']['creationTimestamp'].replace('Z', '+00:00')) for n in FANS)
        for crd in crds:
            established = next(c for c in crd['status']['conditions'] if c['type'] == 'Established')
            assert established['status'] == 'True'
            assert datetime.fromisoformat(established['lastTransitionTime'].replace('Z', '+00:00')) <= creation
            assert set(crd['metadata']['annotations']['argocd.argoproj.io/sync-options'].split(',')) == {'Prune=false', 'Delete=false'}
        report['initial_crds'] = crds
        checks.append({'name': 'crd_establishment_before_instance_admission', 'passed': True})
        capture_logs('initial two fans')
        remaining_zone = deepcopy(zone)
        remaining_zone['spec']['fanRefs'] = [FANS[1]]
        stage('first_fan_prune', [resources[1], remaining_zone])
        wait('first_fan_pruned', lambda: absent('fan', FANS[0]))
        wait('remaining_fan_regulates', lambda: regulating(status(), [FANS[1]], 47.5))
        assert worker()['metadata']['uid'] == first_worker['metadata']['uid']
        capture_logs('after first fan prune')
        assert '"runtime_lab_gpio": "stop", "pin": 18' in '\n'.join(logs)
        checks.append({'name': 'ownership_transfer_preserves_worker_and_closes_driver', 'passed': True})
        stage('all_instances_prune', [])
        wait('all_instances_finalized', lambda: all(absent('fan', n) for n in FANS)
             and absent('coolingzone', ZONE))
        wait('worker_removed_before_operator', lambda: not get('pods', '-n', NS, '-l', 'app.kubernetes.io/component=worker')['items'])
        assert get('deployment', APP + '-operator', '-n', NS)['status'].get('availableReplicas') == 1
        checks.append({'name': 'operator_stays_ready_through_retirement', 'passed': True})
        cmd('delete', 'application', APP, '-n', ARGO_NS, '--wait=false')
        wait('application_deleted_after_retirement', lambda: absent('application', APP, '-n', ARGO_NS))
        wait('operator_removed', lambda: absent('deployment', APP + '-operator', '-n', NS))
        retained = [get('crd', n) for n in CRDS]
        assert [c['metadata']['uid'] for c in retained] == [c['metadata']['uid'] for c in crds]
        assert all(any(c['type'] == 'Established' and c['status'] == 'True' for c in d['status']['conditions']) for d in retained)
        assert not get('fans')['items'] and not get('coolingzones')['items']
        report['retained_crds'] = retained
        checks.append({'name': 'shared_crds_retained_after_application_deletion', 'passed': True})
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        try:
            report['failure_application'] = app()
            capture_logs('failure')
        except Exception:
            pass
        # Preserve failure state for diagnosis. Do not remove finalizers or
        # uninstall the operator while an active hardware claim needs release.
        raise
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2)+'\n')
        args.logs.write_text('\n'.join(logs))


if __name__ == '__main__':
    main()
