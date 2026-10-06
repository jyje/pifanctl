#!/usr/bin/env python3
"""Exercise unmodified runtime code with explicitly simulated I/O in kind."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

NS = 'pifanctl-release'
DEPLOY = 'pifanctl-release-operator'
GROUP = 'pifanctl.jyje.online'
FANS = ('lab-fan-a', 'lab-fan-b')
ZONE = 'lab-local-zone'


def fan(node, name, pin):
    return {'apiVersion': GROUP + '/v1', 'kind': 'Fan', 'metadata': {'name': name},
            'spec': {'nodeName': node, 'hardware': {'rpigpio': {'pin': pin, 'frequencyHz': 1000}},
                     'control': {'curve': {'temperatureLow': 50, 'temperatureHigh': 70,
                                         'dutyIdle': 0, 'dutyStart': 30, 'dutyMax': 100,
                                         'dutyDownStep': 100, 'temperatureHysteresis': 0},
                                 'refreshIntervalSeconds': 1, 'failsafeDuty': 100, 'exitDuty': 100}}}


def ready(obj):
    return any(c.get('type') == 'Ready' and c.get('status') == 'True'
               for c in obj.get('status', {}).get('conditions', []))


def regulating(status, names, duty):
    return status.get('ready') and set(status.get('fans', {})) == set(names) and all(
        value.get('ready') and abs(value['dutyPercent'] - duty) < 0.1
        for value in status['fans'].values())


def sensor_failsafe(status, names):
    fans = status.get('fans', {})
    return not status.get('ready') and set(fans) == set(names) and all(
        not value['ready'] and value['dutyPercent'] == 100 and value['reason'] == 'LocalSensorUnavailable'
        for value in fans.values())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--logs', type=Path, required=True)
    args = p.parse_args()
    prefix = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    def cmd(*parts, body=None, check=True):
        r = subprocess.run(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                           text=True, capture_output=True, timeout=35)
        if check and r.returncode: raise RuntimeError(r.stderr)
        return r
    def get(*parts): return json.loads(cmd('get', *parts, '-o', 'json').stdout)
    context = cmd('config', 'current-context').stdout.strip()
    if context != 'kind-pifanctl-release': raise SystemExit('Refusing runtime lab outside kind-pifanctl-release')
    operator = get('deployment', DEPLOY, '-n', NS)
    image = operator['spec']['template']['spec']['containers'][0]['image']
    if not image.startswith('pifanctl-runtime-lab:'): raise SystemExit('Operator must use an explicitly marked runtime-lab image')
    node = get('nodes')['items'][0]['metadata']['name']
    for kind, name in [('fan', n) for n in FANS] + [('coolingzone', ZONE)]:
        if cmd('get', kind, name, check=False).returncode == 0:
            raise SystemExit('Lab resource already exists; inspect it instead of restarting a trial')
    checks, samples, log_parts = [], [], []
    report = {'context': context, 'image': image, 'started_at_utc': datetime.now(timezone.utc).isoformat(),
              'simulated_io': True, 'hardware_acceptance': False, 'checks': checks, 'samples': samples, 'passed': False}
    worker_name = None
    def worker():
        pods = get('pods', '-n', NS, '-l', 'app.kubernetes.io/component=worker')['items']
        if len(pods) != 1: raise RuntimeError('Expected exactly one node-bound worker Pod')
        return pods[0]
    def snapshot():
        pod = worker(); ip = pod['status'].get('podIP')
        if not ip: raise RuntimeError('Worker has no Pod IP yet')
        code = 'import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://' + ip + ':9103/status",timeout=3))))'
        r = cmd('exec', '-n', NS, 'deploy/' + DEPLOY, '--', 'python', '-c', code)
        result = json.loads(r.stdout)
        samples.append({'at_utc': datetime.now(timezone.utc).isoformat(), 'pod_uid': pod['metadata']['uid'], 'status': result})
        return result
    def wait(name, probe, timeout=160):
        start, deadline, last_error = time.monotonic(), time.monotonic() + timeout, None
        while time.monotonic() < deadline:
            try:
                detail = probe()
                if detail:
                    checks.append({'name': name, 'passed': True, 'elapsed_seconds': round(time.monotonic()-start, 2)})
                    print(name + ': passed', flush=True)
                    return detail
            except (RuntimeError, KeyError, json.JSONDecodeError) as error: last_error = str(error)
            time.sleep(2)
        raise RuntimeError(name + ': timeout; ' + str(last_error))
    def apply(obj): cmd('apply', '-f', '-', body=obj)
    def capture_logs(label):
        r = cmd('logs', '-n', NS, worker()['metadata']['name'], check=False)
        log_parts.append('## ' + label + '\n' + r.stdout)
    def delete(kind, name): cmd('delete', kind, name, '--wait=false', check=False)
    def absent(kind, name):
        r = cmd('get', kind, name, check=False)
        return r.returncode != 0 and 'NotFound' in r.stderr
    zone = {'apiVersion': GROUP + '/v1', 'kind': 'CoolingZone', 'metadata': {'name': ZONE},
            'spec': {'fanRefs': [FANS[0]], 'nodeNames': [node], 'telemetry': {'source': 'local'}}}
    try:
        apply(fan(node, FANS[0], 18)); apply(zone)
        wait('one_fan_regulating', lambda: regulating(snapshot(), [FANS[0]], 47.5))
        first_pod = worker(); worker_name = first_pod['metadata']['name']
        wait('cr_status_ready', lambda: ready(get('fan', FANS[0])) and ready(get('coolingzone', ZONE)))
        assert first_pod['spec']['nodeName'] == node
        assert first_pod['spec']['automountServiceAccountToken'] is False
        assert snapshot()['nodeUID'] == get('node', node)['metadata']['uid']
        checks.append({'name': 'worker_node_uid_no_credentials', 'passed': True})
        apply(fan(node, FANS[1], 19)); zone['spec']['fanRefs'] = list(FANS); apply(zone)
        wait('two_fans_one_worker', lambda: regulating(snapshot(), FANS, 47.5))
        cm = get('configmaps', '-n', NS, '-l', 'pifanctl.jyje.online/node')['items'][0]['metadata']['name']
        def temperature(value): cmd('patch', 'configmap', cm, '-n', NS, '--type=merge', '-p', json.dumps({'data': {'lab-temperature-celsius': value}}))
        temperature('80')
        wait('hot_sensor_full_duty', lambda: regulating(snapshot(), FANS, 100))
        temperature('missing')
        wait('missing_sensor_failsafe', lambda: sensor_failsafe(snapshot(), FANS))
        temperature('55')
        wait('sensor_recovery', lambda: regulating(snapshot(), FANS, 47.5))
        capture_logs('before first fan retirement')
        zone['spec']['fanRefs'] = [FANS[1]]; apply(zone); delete('fan', FANS[0])
        wait('first_fan_finalizer_released', lambda: absent('fan', FANS[0]))
        wait('remaining_fan_regulates', lambda: regulating(snapshot(), [FANS[1]], 47.5))
        capture_logs('after first fan retirement')
        log_text = '\n'.join(log_parts)
        assert '"runtime_lab_gpio": "stop", "pin": 18' in log_text
        checks.append({'name': 'removed_driver_closed', 'passed': True})
        delete('coolingzone', ZONE)
        wait('zone_finalizer_released', lambda: absent('coolingzone', ZONE))
        wait('unassigned_fan_full_duty', lambda: snapshot()['fans'][FANS[1]]['dutyPercent'] == 100)
        capture_logs('before final fan retirement')
        delete('fan', FANS[1]); wait('last_fan_finalizer_released', lambda: absent('fan', FANS[1]))
        wait('worker_removed', lambda: not get('pods', '-n', NS, '-l', 'app.kubernetes.io/component=worker')['items'])
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        try: capture_logs('failure')
        except Exception: pass
        raise
    finally:
        # Keep the operator alive for cooperative finalization. Never force
        # finalizers off and never delete a stalled worker to fake acceptance.
        delete('coolingzone', ZONE)
        for name in FANS: delete('fan', name)
        args.logs.write_text('\n'.join(log_parts))
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2)+'\n')


if __name__ == '__main__': main()
