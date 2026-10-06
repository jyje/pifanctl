#!/usr/bin/env python3
"""Observe a live candidate or rollback without changing the fan or workloads."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import quote

from verify_gitops_lifecycle import synced_healthy
from verify_live_storage_migration import worker_ready


def telemetry(values, clocks, expected, now):
    temperatures = {r['metric']['node']: float(r['value'][1]) for r in values}
    observed = {r['metric']['node']: float(r['value'][1]) for r in clocks}
    if set(temperatures) != set(expected) or set(observed) != set(expected):
        raise RuntimeError('Member temperature/source-clock inventory mismatch')
    if any(not 0 <= now - stamp <= 30 for stamp in observed.values()):
        raise RuntimeError('A member source sample is stale or future-dated')
    if any(not -20 <= value < 65 for value in temperatures.values()):
        raise RuntimeError('Member temperature exceeds the observation guardrail')
    return temperatures, observed


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--context', required=True)
    p.add_argument('--application', required=True)
    p.add_argument('--revision', required=True)
    p.add_argument('--image', required=True)
    p.add_argument('--digest', required=True)
    p.add_argument('--baseline', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    p.add_argument('--duration', type=int, default=120)
    p.add_argument('--prometheus-namespace', default='observability')
    p.add_argument('--prometheus-service', default='prometheus-kube-prometheus-prometheus')
    args = p.parse_args()
    if args.context != 'microk8s' or args.duration < 60:
        raise SystemExit('Use explicit microk8s context and at least 60 seconds')
    # kubectl request-timeout becomes a query argument on the Pod proxy and
    # changes the worker's exact /status path. Bound the subprocess instead.
    prefix = ['kubectl', '--context', args.context]

    def cmd(*parts):
        return json.loads(subprocess.check_output(prefix + list(parts), text=True, timeout=30))

    def get(*parts):
        return cmd('get', *parts, '-o', 'json')

    baseline = json.loads(args.baseline.read_text())
    original = {o['kind']: o for values in baseline['resources'].values() for o in values}
    expected = original['CoolingZone']['spec']['nodeNames']
    ns = baseline['application']['spec']['destination']['namespace']
    prom = ('/api/v1/namespaces/' + args.prometheus_namespace + '/services/http:'
            + args.prometheus_service + ':9090/proxy/api/v1/query?query=')
    selector = '{node=~"' + '|'.join(expected) + '"}'
    report = {'passed': False, 'context': args.context, 'expected_image': args.image,
              'expected_digest': args.digest, 'minimum_hold_seconds': args.duration,
              'started_at_utc': datetime.now(timezone.utc).isoformat(), 'samples': []}
    deadline, hold = time.monotonic() + 240 + args.duration, None
    try:
        while time.monotonic() < deadline:
            app = get('application', args.application, '-n', 'argocd')
            operator = get('deployment', args.application + '-operator', '-n', ns)
            workers = get('pods', '-n', ns, '-l', 'app.kubernetes.io/component=worker')['items']
            controllers = get('pods', '-n', ns, '-l', 'app.kubernetes.io/component=controller')['items']
            if len(workers) > 1 or controllers:
                raise RuntimeError('Multiple worker Pods or a legacy controller exists')
            crs = get('fans,coolingzones')['items']
            if len(crs) != len(original):
                raise RuntimeError('Custom resource inventory changed')
            for obj in crs:
                old = original[obj['kind']]
                if obj['metadata']['uid'] != old['metadata']['uid'] or obj['spec'] != old['spec']:
                    raise RuntimeError('Custom resource identity or topology changed')
            matched = app['spec']['source']['targetRevision'] == args.revision and synced_healthy(app)
            ready = len(workers) == 1 and worker_ready(workers[0]) and matched
            ready = ready and operator.get('status', {}).get('availableReplicas') == 1
            ready = ready and operator['spec']['template']['spec']['containers'][0]['image'] == args.image
            ready = ready and len(workers) == 1 and workers[0]['spec']['containers'][0]['image'] == args.image
            ready = ready and all(any(c.get('type') == 'Ready' and c.get('status') == 'True'
                                     for c in o.get('status', {}).get('conditions', [])) for o in crs)
            if not ready:
                if hold is not None:
                    raise RuntimeError('Readiness/source synchronization lost during hold')
                time.sleep(5)
                continue
            worker = workers[0]
            container = worker['spec']['containers'][0]
            state = worker['status']['containerStatuses'][0]
            if container['image'] != args.image or not state['imageID'].endswith('@' + args.digest):
                raise RuntimeError('Worker image identity mismatch')
            if worker['spec'].get('automountServiceAccountToken') is not False:
                raise RuntimeError('Worker unexpectedly has service account credentials')
            locks = next(v for v in worker['spec']['volumes'] if v['name'] == 'locks')
            if locks.get('hostPath', {}).get('path') != '/var/lock/pifanctl':
                raise RuntimeError('Shared host lock identity changed')
            pod = worker['metadata']['name']
            direct = cmd('get', '--raw=/api/v1/namespaces/' + ns + '/pods/' + pod + ':9103/proxy/status')
            now = time.time()
            if not direct.get('ready') or not 0 <= now - direct['heartbeatTime'] <= 15:
                raise RuntimeError('Direct worker is unhealthy or stale')
            if direct['nodeUID'] != original['Fan']['status']['nodeUID'] or direct['nodeName'] != original['Fan']['spec']['nodeName']:
                raise RuntimeError('Actuator Node identity changed')
            if direct['appliedTopologyHash'] != original['Fan']['status']['appliedTopologyHash']:
                raise RuntimeError('Worker plan hash changed')
            values = cmd('get', '--raw=' + prom + quote('max by(node)(pifanctl_temperature_celsius' + selector + ')', safe=''))
            clocks = cmd('get', '--raw=' + prom + quote('min by(node)(timestamp(pifanctl_temperature_celsius' + selector + '))', safe=''))
            temperatures, stamps = telemetry(values['data']['result'], clocks['data']['result'], expected, time.time())
            hold = hold if hold is not None else time.monotonic()
            report['samples'].append({'observed_at_utc': datetime.now(timezone.utc).isoformat(),
                                      'hold_seconds': time.monotonic() - hold, 'application': app,
                                      'operator': operator, 'resources': crs, 'worker': worker, 'worker_report': direct,
                                      'member_temperatures': temperatures, 'member_source_times': stamps})
            print(json.dumps({'hold_seconds': round(time.monotonic() - hold, 1),
                              'max_temperature': max(temperatures.values()), 'worker': pod}), flush=True)
            if time.monotonic() - hold >= args.duration:
                report['passed'] = True
                break
            time.sleep(5)
        if not report['passed']:
            raise RuntimeError('Source-aware healthy runtime hold timed out')
    except Exception as error:
        report['error'] = str(error)
        raise
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
