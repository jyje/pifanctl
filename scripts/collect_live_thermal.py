#!/usr/bin/env python3
"""Collect a bounded fixed-load trial without changing fan configuration."""
import argparse
import csv
from datetime import datetime, timezone
import inspect
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote
import uuid

from verify_gitops_lifecycle import synced_healthy
from verify_live_storage_migration import worker_ready
from verify_thermal_acceptance import evaluate


def guarded_load(seconds, cutoff, read_temperature=None, clock=None):
    """A node-local guard independent of the remote collector and Prometheus."""
    import math
    import time
    from pathlib import Path
    read_temperature = read_temperature or (lambda: float(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000)
    clock = clock or time.monotonic
    deadline = clock() + seconds
    while clock() < deadline:
        temperature = read_temperature()
        if not math.isfinite(temperature) or temperature < -20:
            raise RuntimeError('Invalid local thermal reading')
        if temperature >= cutoff:
            return 'local_temperature_cutoff'
        chunk_end = min(deadline, clock() + 0.05)
        while clock() < chunk_end:
            pass
    return 'local_duration_deadline'


def validate_sample(values, clocks, expected, worker, fan_name, now):
    temperatures = {r['metric']['node']: float(r['value'][1]) for r in values}
    observed = {r['metric']['node']: float(r['value'][1]) for r in clocks}
    if set(temperatures) != set(expected) or set(observed) != set(expected):
        raise RuntimeError('Incomplete member telemetry')
    if any(not math.isfinite(v) or not -20 <= v < 65 for v in temperatures.values()):
        raise RuntimeError('Unsafe member temperature')
    if any(not math.isfinite(t) or not 0 <= now-t <= 25 for t in observed.values()):
        raise RuntimeError('Stale or future member acquisition clock')
    fan = worker.get('fans', {}).get(fan_name, {})
    age = now - float(worker.get('heartbeatTime', 0))
    duty = float(fan.get('dutyPercent', math.nan))
    if (not worker.get('ready') or not fan.get('ready') or fan.get('reason')
            or not 0 <= age <= 15 or not math.isfinite(duty) or not 0 <= duty <= 100):
        raise RuntimeError('Unhealthy worker or invalid duty')
    return temperatures, observed, duty, age


def load_pod(name, namespace, node, image, cpu, seconds, cutoff):
    source = inspect.getsource(guarded_load)
    command = source + ('\nimport json,time\nstart=time.monotonic(); cpu=time.process_time()\n'
                        'reason=guarded_load(' + repr(seconds) + ', ' + repr(cutoff) + ')\n'
                        'print(json.dumps({"reason":reason,"elapsed_seconds":time.monotonic()-start,'
                        '"cpu_seconds":time.process_time()-cpu}),flush=True)\n')
    return {'apiVersion': 'v1', 'kind': 'Pod',
            'metadata': {'name': name, 'namespace': namespace,
                         'labels': {'app.kubernetes.io/name': 'pifanctl-thermal-trial'}},
            'spec': {'nodeName': node, 'restartPolicy': 'Never',
                     'automountServiceAccountToken': False,
                     'activeDeadlineSeconds': seconds + 90, 'terminationGracePeriodSeconds': 0,
                     'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001,
                                         'seccompProfile': {'type': 'RuntimeDefault'}},
                     'containers': [{'name': 'load', 'image': image,
                                     'command': ['python', '-c', command],
                                     'resources': {'requests': {'cpu': str(cpu)+'m', 'memory': '32Mi'},
                                                   'limits': {'cpu': str(cpu)+'m', 'memory': '64Mi'}},
                                     'securityContext': {'allowPrivilegeEscalation': False,
                                                         'readOnlyRootFilesystem': True,
                                                         'capabilities': {'drop': ['ALL']}}}]}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context', required=True)
    p.add_argument('--application', required=True)
    p.add_argument('--fan', required=True)
    p.add_argument('--zone', required=True)
    p.add_argument('--node', required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--target', type=int, choices=(50, 55, 60), required=True)
    p.add_argument('--cpu-millicores', type=int, default=250)
    p.add_argument('--load-seconds', type=int, default=360)
    p.add_argument('--execute', action='store_true')
    args = p.parse_args()
    if (not args.execute or args.context != 'microk8s' or args.archive.exists()
            or not 1 <= args.cpu_millicores <= 1000 or not 120 <= args.load_seconds <= 360):
        raise SystemExit('Require explicit microk8s execution, a new archive and bounded CPU/duration')
    os.umask(0o077)
    args.archive.mkdir(parents=True, mode=0o700)
    prefix = ['kubectl', '--context', args.context]

    def command(*parts, body=None):
        return subprocess.check_output(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                                       text=True, timeout=35)

    def get(*parts):
        return json.loads(command('get', *parts, '-o', 'json'))

    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'target_celsius': args.target,
              'cpu_millicores': args.cpu_millicores, 'collector_passed': False,
              'load_stop_reason': 'not_started', 'cleanup_verified': False}
    rows, created, pod_uid = [], False, None
    load_started = False
    name = 'pifanctl-thermal-' + uuid.uuid4().hex[:12]
    namespace = None
    started = time.monotonic()
    try:
        app = get('application', args.application, '-n', 'argocd')
        if not synced_healthy(app):
            raise RuntimeError('Application lacks source-matched GitOps success')
        namespace = app['spec']['destination']['namespace']
        resources = get('fans,coolingzones')['items']
        originals = {(r['kind'], r['metadata']['name']): r for r in resources}
        fan = originals[('Fan', args.fan)]
        zone = originals[('CoolingZone', args.zone)]
        expected = zone['spec']['nodeNames']
        if args.node not in expected or any(not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', n) for n in expected):
            raise RuntimeError('Invalid or unassigned load member')
        workers = get('pods', '-n', namespace, '-l', 'app.kubernetes.io/component=worker')['items']
        if len(workers) != 1 or not worker_ready(workers[0]):
            raise RuntimeError('Require exactly one healthy worker')
        worker = workers[0]
        image = worker['spec']['containers'][0]['image']
        baseline = {'application': app, 'resources': resources, 'worker': worker}
        (args.archive / 'baseline.json').write_text(json.dumps(baseline, indent=2)+'\n')
        selector = '{node=~"'+'|'.join(expected)+'"}'
        prom = '/api/v1/namespaces/observability/services/http:prometheus-kube-prometheus-prometheus:9090/proxy/api/v1/query?query='

        def snapshot(phase):
            current_app = get('application', args.application, '-n', 'argocd')
            if current_app['spec'] != app['spec'] or not synced_healthy(current_app):
                raise RuntimeError('GitOps configuration or readiness changed')
            current = get('fans,coolingzones')['items']
            if len(current) != len(originals):
                raise RuntimeError('Resource inventory changed')
            for obj in current:
                old = originals[(obj['kind'], obj['metadata']['name'])]
                if obj['spec'] != old['spec'] or obj['metadata']['uid'] != old['metadata']['uid']:
                    raise RuntimeError('Topology or fan configuration changed')
            nodes = get('nodes')['items']
            by_name = {n['metadata']['name']: n for n in nodes}
            if any(not any(c['type']=='Ready' and c['status']=='True' for c in by_name[n]['status']['conditions']) for n in expected):
                raise RuntimeError('Member Node is not Ready')
            active = get('pods', '-n', namespace, '-l', 'app.kubernetes.io/component=worker')['items']
            legacy = get('pods', '-n', namespace, '-l', 'app.kubernetes.io/component=controller')['items']
            if len(active) != 1 or legacy or active[0]['metadata']['uid'] != worker['metadata']['uid'] or not worker_ready(active[0]):
                raise RuntimeError('Worker identity/readiness changed')
            direct = json.loads(command('get', '--raw=/api/v1/namespaces/'+namespace+'/pods/'+worker['metadata']['name']+':9103/proxy/status'))
            if direct['nodeUID'] != fan['status']['nodeUID'] or direct['appliedTopologyHash'] != fan['status']['appliedTopologyHash']:
                raise RuntimeError('Actuator identity or plan changed')
            def query(expr):
                payload = json.loads(command('get', '--raw='+prom+quote(expr, safe='')))
                if payload.get('status') != 'success':
                    raise RuntimeError('Prometheus query failed')
                return payload['data']['result']
            values = query('max by(node)(pifanctl_temperature_celsius'+selector+')')
            clocks = query('min by(node)(pifanctl_temperature_observed_timestamp_seconds'+selector+')')
            now = time.time()
            temperatures, observed, duty, age = validate_sample(values, clocks, expected, direct, args.fan, now)
            row = {'timestamp_utc': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                   'source_observed_at_utc': datetime.fromtimestamp(min(observed.values()), timezone.utc).isoformat(),
                   'phase': phase, 'elapsed_s': round(time.monotonic()-started, 2),
                   'member_temperatures_json': json.dumps(temperatures, sort_keys=True),
                   'member_observed_timestamps_json': json.dumps(observed, sort_keys=True),
                   'hottest_c': max(temperatures.values()), 'requested_duty_percent': duty,
                   'max_source_age_s': now-min(observed.values()), 'worker_heartbeat_age_s': age}
            if not rows or min(observed.values()) > report.get('last_source_time', 0):
                rows.append(row)
                report['last_source_time'] = min(observed.values())
                print(json.dumps({'phase': phase, 'hottest_c': row['hottest_c'], 'duty_percent': duty}), flush=True)
            return max(temperatures.values())

        for _ in range(6):
            if snapshot('baseline') >= args.target+3:
                raise RuntimeError('Baseline already exceeds load stop threshold')
            time.sleep(5)
        definition = load_pod(name, namespace, args.node, image, args.cpu_millicores,
                              args.load_seconds, min(args.target+5, 65))
        (args.archive / 'load-pod.json').write_text(json.dumps(definition, indent=2)+'\n')
        command('create', '-f', '-', body=definition)
        created = True
        load_started = True
        pod_uid = get('pod', name, '-n', namespace)['metadata']['uid']
        command('wait', '-n', namespace, '--for=condition=Ready', 'pod/'+name, '--timeout=30s')
        end = time.monotonic()+args.load_seconds
        report['load_stop_reason'] = 'maximum_load_duration'
        while time.monotonic() < end:
            if snapshot('load-fixed') >= min(args.target+3, 65):
                report['load_stop_reason'] = 'remote_temperature_cutoff'
                break
            pod = get('pod', name, '-n', namespace)
            if pod['status'].get('phase') in ('Succeeded', 'Failed'):
                report['load_stop_reason'] = 'local_guard_or_deadline'
                break
            if evaluate(rows, args.target)['thermal_stability_passed']:
                report['load_stop_reason'] = 'approved_stability_observed'
                break
            time.sleep(5)
        (args.archive / 'load-pod-final.json').write_text(json.dumps(get('pod', name, '-n', namespace), indent=2)+'\n')
        (args.archive / 'load.log').write_text(command('logs', name, '-n', namespace))
        command('delete', 'pod', name, '-n', namespace, '--wait=true', '--timeout=30s')
        created = False
        report['cleanup_verified'] = True
        report['collector_passed'] = True
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if created:
            try:
                current = get('pod', name, '-n', namespace)
                if pod_uid is not None and current['metadata']['uid'] != pod_uid:
                    raise RuntimeError('Refuse cleanup of a replaced Pod')
                command('delete', 'pod', name, '-n', namespace, '--wait=true', '--timeout=30s')
                report['cleanup_verified'] = True
            except Exception as error:
                report['cleanup_error'] = str(error)
        if load_started and report['cleanup_verified']:
            try:
                end = time.monotonic()+120
                while time.monotonic() < end:
                    snapshot('cooldown')
                    time.sleep(5)
                report['cooldown_recorded'] = True
            except Exception as error:
                report['cooldown_error'] = str(error)
                report['collector_passed'] = False
        if rows:
            with (args.archive / 'samples.csv').open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        report['acceptance'] = evaluate(rows, args.target)
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        (args.archive / 'report.json').write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
