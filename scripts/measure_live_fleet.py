#!/usr/bin/env python3
"""Read-only process, real Prometheus and API measurements for the active four-member rack."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from urllib.parse import quote

from collect_live_thermal import validate_sample
from measure_lab_resources import PROCESS, api_totals
from verify_gitops_lifecycle import synced_healthy


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    if args.report.exists():
        raise SystemExit('Refuse to overwrite evidence')
    os.umask(0o077)
    prefix = ['kubectl', '--context', 'microk8s']
    report = {'started_at_utc': datetime.now(timezone.utc).isoformat(), 'read_only': True,
              'visibility': 'public_anonymous_measurements', 'passed': False, 'samples': [],
              'latency_scope': 'kubectl command, Kubernetes proxy and remote endpoint combined',
              'supported_capacity_contract_changed': False}
    def cmd(*parts):
        return subprocess.check_output(prefix + list(parts), text=True, timeout=25)
    def get(*parts):
        return json.loads(cmd('get', *parts, '-o', 'json'))
    try:
        app = get('application', 'pifanctl-v1-staging', '-n', 'argocd')
        if not synced_healthy(app):
            raise RuntimeError('Require source-matched healthy GitOps')
        namespace = app['spec']['destination']['namespace']
        fan = get('fan', 'r4spi-rack-fan')
        zone = get('coolingzone', 'r4spi-rack')
        members = zone['spec']['nodeNames']
        if len(members) != 4 or len(zone['spec']['fanRefs']) != 1:
            raise RuntimeError('Require the reviewed four-member single-fan topology')
        components = {}
        for component in ('operator', 'worker'):
            pods = get('pods', '-n', namespace, '-l', 'app.kubernetes.io/component='+component)['items']
            if len(pods) != 1 or not all(c['ready'] for c in pods[0]['status']['containerStatuses']):
                raise RuntimeError('Require exactly one Ready '+component)
            components[component] = pods[0]
        report['fleet'] = {'operator_pods': 1, 'worker_pods': 1, 'fans': 1, 'member_nodes': 4}
        report['images'] = {k: v['spec']['containers'][0]['image'] for k,v in components.items()}
        aliases = {name: 'node-'+chr(97+i) for i,name in enumerate(sorted(members))}
        selector = '{node=~"'+'|'.join(sorted(members))+'"}'
        prom = '/api/v1/namespaces/observability/services/http:prometheus-kube-prometheus-prometheus:9090/proxy/api/v1/query?query='
        def query(expression):
            started = time.monotonic()
            result = json.loads(cmd('get', '--raw='+prom+quote(expression, safe='')))
            elapsed = time.monotonic()-started
            if result.get('status') != 'success':
                raise RuntimeError('Real Prometheus query failed')
            return result['data']['result'], elapsed
        api_start = api_totals(cmd('get', '--raw=/metrics'))
        started = time.monotonic()
        for _ in range(12):
            current_app = get('application', 'pifanctl-v1-staging', '-n', 'argocd')
            if current_app['spec'] != app['spec'] or not synced_healthy(current_app):
                raise RuntimeError('GitOps source or health changed')
            for kind, obj in (('fan',fan),('coolingzone',zone)):
                current = get(kind, obj['metadata']['name'])
                if current['spec'] != obj['spec'] or current['metadata']['uid'] != obj['metadata']['uid']:
                    raise RuntimeError('Topology identity changed')
            for component, pod in components.items():
                current = get('pod', pod['metadata']['name'], '-n', namespace)
                if (current['metadata']['uid'] != pod['metadata']['uid']
                        or current['status']['containerStatuses'][0]['containerID'] != pod['status']['containerStatuses'][0]['containerID']
                        or not all(c['ready'] for c in current['status']['containerStatuses'])):
                    raise RuntimeError('Runtime Pod identity/readiness changed')
            start = time.monotonic()
            state = json.loads(cmd('get', '--raw=/api/v1/namespaces/'+namespace+'/pods/'+components['worker']['metadata']['name']+':9103/proxy/status'))
            latency = time.monotonic()-start
            values, query_seconds = query('max by(node)(pifanctl_temperature_celsius'+selector+')')
            clocks, clock_seconds = query('min by(node)(pifanctl_temperature_observed_timestamp_seconds'+selector+')')
            temperatures, observed, duty, age = validate_sample(values, clocks, members, state, fan['metadata']['name'], time.time())
            processes = {k:json.loads(cmd('exec','-n',namespace,v['metadata']['name'],'--','python','-c',PROCESS)) for k,v in components.items()}
            temperatures, observed, duty, age = validate_sample(values, clocks, members, state, fan['metadata']['name'], time.time())
            report['samples'].append({'at_utc': datetime.now(timezone.utc).isoformat(), 'status_seconds':latency,
                'temperature_query_seconds': query_seconds, 'clock_query_seconds': clock_seconds,
                'member_temperatures': {aliases[k]:v for k,v in temperatures.items()},
                'maximum_source_age_seconds':time.time()-min(observed.values()), 'worker_heartbeat_age_seconds':age,
                'requested_duty_percent':duty, 'processes': processes})
            time.sleep(5)
        report['elapsed_seconds'] = time.monotonic()-started
        report['cr_api_requests_including_operator_and_observer'] = api_totals(cmd('get','--raw=/metrics'))-api_start
        for component in components:
            first,last = report['samples'][0]['processes'][component],report['samples'][-1]['processes'][component]
            if last['cpu_seconds'] < first['cpu_seconds'] or last['monotonic_seconds'] <= first['monotonic_seconds']:
                raise RuntimeError('Process counter reset during observation')
            report[component] = {'average_vcpu':(last['cpu_seconds']-first['cpu_seconds'])/(last['monotonic_seconds']-first['monotonic_seconds']),
                'maximum_sampled_rss_bytes':max(s['processes'][component]['rss_bytes'] for s in report['samples'])}
        for key in ('status_seconds','temperature_query_seconds','clock_query_seconds'):
            values = sorted(s[key] for s in report['samples'])
            report[key] = {'median': statistics.median(values),'nearest_rank_p95':values[-1]}
        report['passed'] = True
    except Exception as error:
        # Keep raw diagnostic strings private; successful projections contain no IDs.
        report['error'] = str(error)
        raise
    finally:
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        args.report.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='samples'},indent=2))


if __name__ == '__main__':
    main()
