#!/usr/bin/env python3
"""Bounded single-actuator fan/zone scale and software-fault probe in kind only."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import subprocess
import time

from verify_runtime_lifecycle import fan, ready, regulating

NS = 'pifanctl-release'
DEPLOY = 'pifanctl-release-operator'
LABEL = 'pifanctl.jyje.online/acceptance=fleet-fault'


def fixtures(node, count):
    if count not in (1, 4, 16):
        raise ValueError('Require a declared fixture size: 1, 4 or 16')
    fans = [fan(node, 'acceptance-fan-' + str(i), i + 2) for i in range(count)]
    zones = [{'apiVersion': 'pifanctl.jyje.online/v1', 'kind': 'CoolingZone',
              'metadata': {'name': 'acceptance-zone-' + str(i)},
              'spec': {'fanRefs': [fans[i % count]['metadata']['name']],
                       'nodeNames': [node], 'telemetry': {'source': 'local'}}}
             for i in range(count * 4)]
    for obj in fans + zones:
        obj['metadata']['labels'] = {'pifanctl.jyje.online/acceptance': 'fleet-fault'}
    return fans, zones


def expired(status, names):
    values = status.get('fans', {})
    return (not status.get('ready') and set(values) == set(names) and all(
        not v.get('ready') and v.get('dutyPercent') == 100
        and v.get('reason') == 'OperatorHeartbeatExpired' for v in values.values()))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    if args.report.exists():
        raise SystemExit('Refuse to overwrite evidence')
    prefix = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'simulated_io': True, 'hardware_acceptance': False,
              'distributed_fleet_acceptance': False, 'passed': False,
              'stages': [], 'checks': [], 'harness_commands': 0}

    def cmd(*parts, body=None, check=True):
        report['harness_commands'] += 1
        result = subprocess.run(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                                text=True, capture_output=True, timeout=35)
        if check and result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout

    def get(*parts):
        return json.loads(cmd('get', *parts, '-o', 'json'))

    context = cmd('config', 'current-context').strip()
    if context != 'kind-pifanctl-release':
        raise SystemExit('Require the explicitly owned kind lab context')
    deployment = get('deployment', DEPLOY, '-n', NS)
    image = deployment['spec']['template']['spec']['containers'][0]['image']
    if not image.startswith('pifanctl-runtime-lab:') or deployment['spec']['replicas'] != 1:
        raise SystemExit('Require exactly one explicitly simulated lab operator')
    if get('fans,coolingzones')['items']:
        raise SystemExit('Require an empty lab topology')
    node = get('nodes')['items'][0]
    report.update(context=context, image=image, kubernetes_version=node['status']['nodeInfo']['kubeletVersion'])
    restore_operator = False

    def wait(name, probe, timeout=180):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            value = probe()
            if value:
                result = {'name': name, 'passed': True, 'elapsed_seconds': time.monotonic()-start}
                report['checks'].append(result)
                print(json.dumps(result), flush=True)
                return value
            time.sleep(2)
        raise RuntimeError(name + ': timed out')

    def worker():
        pods = get('pods', '-n', NS, '-l', 'app.kubernetes.io/component=worker')['items']
        return pods[0] if len(pods) == 1 else None

    def status():
        pod = worker()
        if not pod or not pod.get('status', {}).get('podIP'):
            return {}
        # API proxy does not require the operator to remain alive during the fault.
        raw = cmd('get', '--raw=/api/v1/namespaces/' + NS + '/pods/' + pod['metadata']['name'] + ':9103/proxy/status', check=False)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def all_ready(names):
        items = get('fans,coolingzones', '-l', LABEL)['items']
        return len(items) == len(names)*5 and all(ready(obj) for obj in items) and regulating(status(), names, 47.5)

    def clean():
        cmd('delete', 'coolingzones', '-l', LABEL, '--wait=false')
        cmd('delete', 'fans', '-l', LABEL, '--wait=false')
        wait('cooperative_cleanup', lambda: not get('fans,coolingzones', '-l', LABEL)['items'] and not worker())

    try:
        for count in (1, 4, 16):
            fans, zones = fixtures(node['metadata']['name'], count)
            names = [obj['metadata']['name'] for obj in fans]
            started = time.monotonic()
            cmd('apply', '-f', '-', body={'apiVersion': 'v1', 'kind': 'List', 'items': fans + zones})
            wait('ready_' + str(count) + '_fans', lambda: all_ready(names))
            stage = {'fans': count, 'zones': len(zones), 'actuator_nodes': 1, 'member_nodes': 1,
                     'apply_to_ready_seconds': time.monotonic()-started, 'samples': []}
            pod = worker()
            metrics_path = '--raw=/api/v1/namespaces/' + NS + '/pods/' + pod['metadata']['name'] + ':9103/proxy/metrics'
            for _ in range(12):
                start = time.monotonic()
                state = status()
                latency = time.monotonic()-start
                if not regulating(state, names, 47.5):
                    raise RuntimeError('Fleet became unhealthy during observation')
                metrics = cmd('get', metrics_path)
                if sum(line.startswith('pifanctl_worker_fan_duty_percent{') for line in metrics.splitlines()) != count:
                    raise RuntimeError('Incomplete fan metrics')
                stage['samples'].append({'at_utc': datetime.now(timezone.utc).isoformat(),
                                        'status_seconds': latency, 'metrics_bytes': len(metrics.encode()),
                                        'heartbeat_age_seconds': time.time()-state['heartbeatTime']})
                time.sleep(5)
            latencies = sorted(s['status_seconds'] for s in stage['samples'])
            stage['status_median_seconds'] = statistics.median(latencies)
            stage['status_nearest_rank_p95_seconds'] = latencies[-1]
            # This is a 12-sample empirical endpoint measurement, not an API throughput claim.
            report['stages'].append(stage)
            print(json.dumps({k: v for k, v in stage.items() if k != 'samples'}), flush=True)
            if count != 16:
                clean()
        before = worker()
        before_restarts = before['status']['containerStatuses'][0]['restartCount']
        cmd('exec', '-n', NS, before['metadata']['name'], '--', 'python', '-c', 'import os,signal; os.kill(1,signal.SIGTERM)', check=False)
        wait('graceful_worker_restart', lambda: worker() and worker()['status'].get('containerStatuses', [{}])[0].get('restartCount', 0) > before_restarts and regulating(status(), names, 47.5))
        previous = cmd('logs', '-n', NS, before['metadata']['name'], '--previous')
        records = [json.loads(line) for line in previous.splitlines() if line.startswith('{"runtime_lab_gpio"')]
        for obj in fans:
            pin = obj['spec']['hardware']['rpigpio']['pin']
            actions = [r for r in records if r.get('pin') == pin]
            if not any(r.get('runtime_lab_gpio') == 'duty' and r.get('duty') == 100 for r in actions) or not any(r.get('runtime_lab_gpio') == 'stop' for r in actions):
                raise RuntimeError('Missing graceful exit duty or driver close evidence')
        report['checks'].append({'name': 'graceful_exit_full_duty_and_driver_close', 'passed': True})
        # No hardware is connected. Stop only this lab operator, not the kind node.
        restore_operator = True
        cmd('scale', 'deployment', DEPLOY, '-n', NS, '--replicas=0')
        wait('operator_heartbeat_expires_all_fans_full_duty', lambda: expired(status(), names), timeout=210)
        cmd('scale', 'deployment', DEPLOY, '-n', NS, '--replicas=1')
        restore_operator = False
        wait('operator_recovery_all_crs_ready', lambda: all_ready(names), timeout=210)
        clean()
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        if restore_operator:
            cmd('scale', 'deployment', DEPLOY, '-n', NS, '--replicas=1')
        if not report['passed']:
            clean()
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__':
    main()
