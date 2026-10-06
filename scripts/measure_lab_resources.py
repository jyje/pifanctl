#!/usr/bin/env python3
"""Read-only bounded process and CR API measurements in the owned kind lab."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

PROCESS = ('import json,os,pathlib,time; '
           's=pathlib.Path("/proc/1/stat").read_text().rsplit(")",1)[1].split(); '
           'print(json.dumps({"cpu_seconds":(int(s[11])+int(s[12]))/os.sysconf("SC_CLK_TCK"),'
           '"rss_bytes":int(s[21])*os.sysconf("SC_PAGE_SIZE"),"monotonic_seconds":time.monotonic()}))')


def api_totals(text):
    total = 0
    for line in text.splitlines():
        if line.startswith('apiserver_request_total{') and 'group="pifanctl.jyje.online"' in line:
            total += float(line.rsplit(' ', 1)[1])
    return total


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    if args.report.exists():
        raise SystemExit('Refuse to overwrite evidence')
    prefix = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    def cmd(*parts):
        return subprocess.check_output(prefix + list(parts), text=True, timeout=20)
    def get(*parts):
        return json.loads(cmd('get', *parts, '-o', 'json'))
    if cmd('config', 'current-context').strip() != 'kind-pifanctl-release':
        raise SystemExit('Require the explicitly owned kind lab')
    ns = 'pifanctl-release'
    pods = get('pods', '-n', ns)['items']
    by_component = {p['metadata']['labels'].get('app.kubernetes.io/component'): p for p in pods
                    if p['status'].get('phase') == 'Running'}
    if set(by_component) != {'operator', 'worker'}:
        raise SystemExit('Require one operator and one worker')
    if any(not p['spec']['containers'][0]['image'].startswith('pifanctl-runtime-lab:') for p in pods):
        raise SystemExit('Require explicitly simulated images')
    identifiers = {k: v['metadata']['uid'] for k, v in by_component.items()}
    samples = []
    api_start = api_totals(cmd('get', '--raw=/metrics'))
    started = time.monotonic()
    for _ in range(6):
        topology = get('fans,coolingzones')['items']
        current = get('pods', '-n', ns)['items']
        current_ids = {p['metadata']['labels'].get('app.kubernetes.io/component'): p['metadata']['uid'] for p in current}
        if current_ids != identifiers:
            raise RuntimeError('Pod identity changed during resource observation')
        processes = {k: json.loads(cmd('exec', '-n', ns, v['metadata']['name'], '--', 'python', '-c', PROCESS))
                     for k, v in by_component.items()}
        samples.append({'at_utc': datetime.now(timezone.utc).isoformat(),
                        'fans': sum(o['kind'] == 'Fan' for o in topology),
                        'zones': sum(o['kind'] == 'CoolingZone' for o in topology),
                        'all_crs_ready': all(any(c['type']=='Ready' and c['status']=='True' for c in o.get('status', {}).get('conditions', [])) for o in topology),
                        'processes': processes})
        time.sleep(5)
    api_end = api_totals(cmd('get', '--raw=/metrics'))
    result = {'visibility': 'public_lab_measurements', 'simulated_io': True,
              'scope': 'one actuator/member node, sixteen simulated fans and sixty-four local zones',
              'samples': samples, 'elapsed_seconds': time.monotonic()-started,
              'cr_api_requests_including_operator_and_observer': api_end-api_start,
              'counts_exclude_core_API_and_prometheus_queries': True,
              'passed': all(s['fans']==16 and s['zones']==64 and s['all_crs_ready'] for s in samples)}
    for component in ('operator', 'worker'):
        first, last = samples[0]['processes'][component], samples[-1]['processes'][component]
        result[component] = {'average_vcpu': (last['cpu_seconds']-first['cpu_seconds'])/(last['monotonic_seconds']-first['monotonic_seconds']),
                             'maximum_sampled_rss_bytes': max(s['processes'][component]['rss_bytes'] for s in samples)}
    args.report.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='samples'}, indent=2))
    if not result['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
