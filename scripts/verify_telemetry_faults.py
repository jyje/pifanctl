#!/usr/bin/env python3
"""Real HTTP telemetry faults and abrupt worker restart with simulated GPIO in kind."""
import argparse
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path
import subprocess
import time

from verify_runtime_lifecycle import fan, ready, regulating


def run_simulator():
    import json
    import os
    import signal
    import sys
    from pathlib import Path
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import time
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            mode = Path('/fixture/mode').read_text().strip()
            value = time.time()-120 if mode == 'stale' else time.time()
            if 'observed_timestamp' not in self.path:
                value = 55
            result = [] if mode == 'missing' else [{'metric': {'node': os.environ['NODE_NAME']}, 'value': [time.time(), str(value)]}]
            payload = {'status': 'error'} if mode == 'malformed' else {'status': 'success', 'data': {'resultType': 'vector', 'result': result}}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())
        def log_message(self, *args):
            pass
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    ThreadingHTTPServer(('0.0.0.0', 9090), Handler).serve_forever()


def failed(status, reason):
    value = status.get('fans', {}).get('fault-fan', {})
    return (not status.get('ready') and not value.get('ready')
            and value.get('dutyPercent') == 100 and reason in value.get('reason', ''))



def checked_runtime_pid(inspection, pod):
    labels = inspection['status']['labels']
    image = inspection['status']['image']['image'].removeprefix('docker.io/library/')
    pid = int(inspection['info']['pid'])
    if (pod['spec']['nodeName'] != 'pifanctl-release-control-plane'
            or labels.get('io.kubernetes.pod.uid') != pod['metadata']['uid']
            or labels.get('io.kubernetes.pod.namespace') != 'pifanctl-release'
            or labels.get('io.kubernetes.container.name') != 'worker'
            or not image.startswith('pifanctl-runtime-lab:') or pid <= 1):
        raise ValueError('Refuse hard stop outside the exact simulated worker')
    return pid

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--restart-only', action='store_true')
    args = p.parse_args()
    if args.report.exists():
        raise SystemExit('Refuse to overwrite evidence')
    prefix = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    ns, deployment = 'pifanctl-release', 'pifanctl-release-operator'
    label = 'pifanctl.jyje.online/acceptance=telemetry-fault'
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'simulated_gpio': True,
              'simulated_temperature_HTTP_source': True, 'hardware_acceptance': False, 'restart_only': args.restart_only,
              'physical_network_partition_acceptance': False, 'checks': [], 'passed': False}
    def cmd(*parts, body=None, check=True):
        result = subprocess.run(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                                text=True, capture_output=True, timeout=35)
        if check and result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout
    def get(*parts):
        return json.loads(cmd('get', *parts, '-o', 'json'))
    if cmd('config', 'current-context').strip() != 'kind-pifanctl-release':
        raise SystemExit('Require the owned disposable kind lab')
    operator = get('deployment', deployment, '-n', ns)
    image = operator['spec']['template']['spec']['containers'][0]['image']
    if not image.startswith('pifanctl-runtime-lab:') or operator['spec']['replicas'] != 1 or get('fans,coolingzones')['items']:
        raise SystemExit('Require one simulated operator and empty topology')
    if get('pods,services,configmaps', '-n', ns, '-l', label)['items']:
        raise SystemExit('Inspect existing fixtures instead of replacing them')
    node = get('nodes')['items'][0]['metadata']['name']
    labels = {'pifanctl.jyje.online/acceptance': 'telemetry-fault'}
    def apply(obj):
        cmd('apply', '-f', '-', body=obj)
    def worker():
        pods = get('pods', '-n', ns, '-l', 'app.kubernetes.io/component=worker')['items']
        return pods[0] if len(pods) == 1 else None
    def status():
        pod = worker()
        if not pod:
            return {}
        raw = cmd('get', '--raw=/api/v1/namespaces/' + ns + '/pods/' + pod['metadata']['name'] + ':9103/proxy/status', check=False)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}
    def wait(name, predicate, timeout=180):
        start = time.monotonic()
        while time.monotonic()-start < timeout:
            state = status()
            if predicate(state):
                report['checks'].append({'name': name, 'passed': True, 'elapsed_seconds': time.monotonic()-start,
                                         'requested_duty_percent': state.get('fans', {}).get('fault-fan', {}).get('dutyPercent'),
                                         'reason': state.get('fans', {}).get('fault-fan', {}).get('reason')})
                print(json.dumps(report['checks'][-1]), flush=True)
                return
            time.sleep(2)
        raise RuntimeError(name + ': timed out')
    def mode(value):
        cmd('patch', 'configmap', 'fault-source', '-n', ns, '--type=merge', '-p', json.dumps({'data': {'mode': value}}))
    metadata = {'name': 'fault-source', 'namespace': ns, 'labels': labels}
    try:
        apply({'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': metadata, 'data': {'mode': 'fresh'}})
        apply({'apiVersion': 'v1', 'kind': 'Pod', 'metadata': metadata,
               'spec': {'automountServiceAccountToken': False, 'restartPolicy': 'Never', 'nodeName': node,
                        'terminationGracePeriodSeconds': 5,
                        'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001},
                        'containers': [{'name': 'source', 'image': image, 'imagePullPolicy': 'Never',
                                        'command': ['python', '-c', inspect.getsource(run_simulator)+'\nrun_simulator()'],
                                        'env': [{'name': 'NODE_NAME', 'value': node}],
                                        'resources': {'limits': {'memory': '64Mi', 'cpu': '100m'}},
                                        'securityContext': {'readOnlyRootFilesystem': True, 'allowPrivilegeEscalation': False,
                                                            'capabilities': {'drop': ['ALL']}},
                                        'volumeMounts': [{'name': 'fixture', 'mountPath': '/fixture', 'readOnly': True}]}],
                        'volumes': [{'name': 'fixture', 'configMap': {'name': 'fault-source'}}]}})
        apply({'apiVersion': 'v1', 'kind': 'Service', 'metadata': metadata,
               'spec': {'selector': labels, 'ports': [{'port': 9090, 'targetPort': 9090}]}})
        obj = fan(node, 'fault-fan', 18)
        obj['metadata']['labels'] = labels
        apply(obj)
        apply({'apiVersion': 'pifanctl.jyje.online/v1', 'kind': 'CoolingZone',
               'metadata': {'name': 'fault-zone', 'labels': labels},
               'spec': {'nodeNames': [node], 'fanRefs': ['fault-fan'],
                        'telemetry': {'source': 'prometheus', 'prometheusURL': 'http://fault-source.'+ns+':9090', 'maxSampleAgeSeconds': 5}}})
        wait('fresh_HTTP_source_regulates', lambda s: regulating(s, ['fault-fan'], 47.5))
        if not args.restart_only:
            for value, reason in [('stale', 'MissingOrStaleTemperature'), ('missing', 'MissingOrStaleTemperature'), ('malformed', 'invalid Prometheus response')]:
                mode(value)
                # Kubernetes projected ConfigMaps can take up to two minutes.
                wait(value + '_source_full_duty', lambda s: failed(s, reason))
                mode('fresh')
                wait(value + '_source_recovery', lambda s: regulating(s, ['fault-fan'], 47.5))
            cmd('patch', 'service', 'fault-source', '-n', ns, '--type=merge', '-p', json.dumps({'spec': {'selector': {'unreachable-fixture': 'true'}}}))
            wait('unreachable_HTTP_endpoint_full_duty', lambda s: failed(s, 'Prometheus query failed'))
            cmd('patch', 'service', 'fault-source', '-n', ns, '--type=json', '-p', json.dumps([{'op': 'replace', 'path': '/spec/selector', 'value': labels}]))
            wait('HTTP_endpoint_recovery', lambda s: regulating(s, ['fault-fan'], 47.5))
        before = worker()
        restarts = before['status']['containerStatuses'][0]['restartCount']
        # Signals from inside a PID namespace may not kill its PID 1.
        # Use the verified kind-node ancestor namespace, never a production host.
        container_id = before['status']['containerStatuses'][0]['containerID'].removeprefix('containerd://')
        import re
        if not re.fullmatch('[0-9a-f]{64}', container_id):
            raise ValueError('Invalid container runtime identity')
        inspection = json.loads(subprocess.check_output(['docker', 'exec', before['spec']['nodeName'], 'crictl', 'inspect', container_id], text=True, timeout=20))
        pid = checked_runtime_pid(inspection, before)
        current = worker()
        if current['metadata']['uid'] != before['metadata']['uid'] or current['status']['containerStatuses'][0]['containerID'] != before['status']['containerStatuses'][0]['containerID']:
            raise RuntimeError('Refuse to stop a replaced container')
        subprocess.run(['docker', 'exec', before['spec']['nodeName'], 'kill', '-KILL', str(pid)], check=True, timeout=20)
        report['abrupt_stop_method'] = 'SIGKILL from the verified kind-node ancestor PID namespace'
        wait('abrupt_worker_restart_recovers', lambda s: worker()['status'].get('containerStatuses', [{}])[0].get('restartCount', 0) > restarts and regulating(s, ['fault-fan'], 47.5))
        report['abrupt_restart_cannot_prove_electrical_safe_default'] = True
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        cmd('delete', 'coolingzones', '-l', label, '--wait=false')
        cmd('delete', 'fans', '-l', label, '--wait=false')
        try:
            wait('cooperative_worker_cleanup', lambda s: not worker() and not get('fans,coolingzones', '-l', label)['items'])
            cmd('delete', 'pod,service,configmap', '-l', label, '-n', ns, '--wait=true', '--timeout=30s')
            report['cleanup_verified'] = True
        except Exception as error:
            report.update(cleanup_verified=False, cleanup_error=str(error), passed=False)
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
