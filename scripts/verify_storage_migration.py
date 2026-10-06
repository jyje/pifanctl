#!/usr/bin/env python3
"""Exercise CRD storage promotion and rollback in the isolated release cluster."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

GROUP = 'pifanctl.jyje.online'
KINDS = ('fans', 'coolingzones')
ROOT = Path(__file__).resolve().parents[1]


def identity(obj):
    m = obj['metadata']
    return {'spec': obj['spec'], 'metadata': {k: m.get(k) for k in
            ('name', 'uid', 'generation', 'finalizers', 'annotations', 'labels', 'ownerReferences')}}


def rewrite(kubectl, version, inventory):
    rewritten = []
    for plural, objects in inventory.items():
        for original in objects:
            path = f'/apis/{GROUP}/{version}/{plural}/{original["metadata"]["name"]}'
            for attempt in range(4):
                current = json.loads(kubectl('get', '--raw=' + path).stdout)
                if identity(current) != identity(original):
                    raise RuntimeError('resource identity/spec changed during migration')
                result = kubectl('replace', '--raw=' + path, '-f', '-', body=current, check=False)
                if result.returncode and 'Conflict' in result.stderr and attempt < 3:
                    continue
                if result.returncode:
                    raise RuntimeError('resource rewrite failed: ' + result.stderr)
                written = json.loads(result.stdout)
                if identity(written) != identity(current) or written.get('status') != current.get('status'):
                    raise RuntimeError('rewrite changed identity, spec, or status')
                rewritten.append((plural, original['metadata']['name']))
                break
    # Only clear storedVersions after every resource was rewritten and the
    # complete inventory is unchanged. Never use a status patch as migration.
    for plural, objects in inventory.items():
        live = json.loads(kubectl('get', '--raw=' + f'/apis/{GROUP}/{version}/{plural}').stdout)['items']
        if {o['metadata']['uid'] for o in live} != {o['metadata']['uid'] for o in objects}:
            raise RuntimeError('resource inventory changed during migration')
        kubectl('patch', 'crd', plural + '.' + GROUP, '--subresource=status', '--type=merge',
                '-p', json.dumps({'status': {'storedVersions': [version]}}))
    return rewritten


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--kubeconfig', type=Path, required=True)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    prefix = ['kubectl', '--kubeconfig', str(args.kubeconfig)]
    def kubectl(*parts, body=None, check=True):
        r = subprocess.run(prefix + list(parts), input=json.dumps(body) if body is not None else None,
                           text=True, capture_output=True, timeout=30)
        if check and r.returncode: raise RuntimeError(r.stderr)
        return r
    context = kubectl('config', 'current-context').stdout.strip()
    if context != 'kind-pifanctl-release':
        raise SystemExit('Refusing storage experiments outside kind-pifanctl-release')
    args.archive.mkdir(parents=True, exist_ok=False)
    report = {'context': context, 'started_at_utc': datetime.now(timezone.utc).isoformat(), 'passed': False, 'checks': []}
    originals, inventory = {}, {}
    for plural in KINDS:
        originals[plural] = json.loads(kubectl('get', 'crd', plural + '.' + GROUP, '-o', 'json').stdout)
        if originals[plural]['status']['storedVersions'] != ['v1alpha1']:
            raise RuntimeError('experiment requires the original alpha-only storage baseline')
        inventory[plural] = json.loads(kubectl('get', '--raw=' + f'/apis/{GROUP}/v1alpha1/{plural}').stdout)['items']
    (args.archive / 'baseline.json').write_text(json.dumps({'crds': originals, 'resources': inventory}, indent=2)+'\n')
    def record(name, detail): report['checks'].append({'name': name, 'passed': True, 'details': detail})
    promoted = False
    try:
        kubectl('apply', '-f', str(ROOT / 'charts/pifanctl-operator/crds'))
        promoted = True
        kubectl('wait', '--for=condition=Established', *['crd/' + k + '.' + GROUP for k in KINDS], '--timeout=30s')
        for plural, objects in inventory.items():
            for original in objects:
                name = original['metadata']['name']
                for version in ('v1', 'v1alpha1'):
                    obj = json.loads(kubectl('get', '--raw=' + f'/apis/{GROUP}/{version}/{plural}/{name}').stdout)
                    assert identity(obj) == identity(original), 'API conversion changed identity/spec'
                    assert obj.get('status') == original.get('status'), 'API conversion changed status'
                    assert obj['apiVersion'] == GROUP + '/' + version
        record('dual_version_identity_status', 'Both API endpoints preserve every archived resource identity, spec and status')
        written = rewrite(kubectl, 'v1', inventory)
        record('v1_storage_rewrite', {'resources': written, 'storedVersions': 'v1'})
        for plural in KINDS:
            crd = json.loads(kubectl('get', 'crd', plural + '.' + GROUP, '-o', 'json').stdout)
            assert crd['status']['storedVersions'] == ['v1']
        record('stored_version_verified', 'All storedVersions fields contain only v1 after complete successful rewrites')
    finally:
        if promoted:
            # Keep both versions served while rewriting back to alpha.
            for plural, original in originals.items():
                current = json.loads(kubectl('get', 'crd', plural + '.' + GROUP, '-o', 'json').stdout)
                for version in current['spec']['versions']:
                    version['storage'] = version['name'] == 'v1alpha1'
                kubectl('replace', '-f', '-', body=current)
            rewritten = rewrite(kubectl, 'v1alpha1', inventory)
            for plural, original in originals.items():
                current = json.loads(kubectl('get', 'crd', plural + '.' + GROUP, '-o', 'json').stdout)
                current['spec'] = deepcopy(original['spec'])
                current['metadata']['annotations'] = deepcopy(original['metadata'].get('annotations', {}))
                kubectl('replace', '-f', '-', body=current)
                restored_crd = json.loads(kubectl('get', 'crd', plural + '.' + GROUP, '-o', 'json').stdout)
                assert restored_crd['spec'] == original['spec']
                assert restored_crd['status']['storedVersions'] == ['v1alpha1']
                for obj in inventory[plural]:
                    restored = json.loads(kubectl('get', '--raw=' + f'/apis/{GROUP}/v1alpha1/{plural}/{obj["metadata"]["name"]}').stdout)
                    assert identity(restored) == identity(obj)
            record('alpha_storage_rollback', {'resources': rewritten, 'restored_crd_specs': True})
        args.report.write_text(json.dumps(report, indent=2)+'\n')
    report['passed'] = True
    report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({'passed': True, 'checks': len(report['checks']), 'archive': str(args.archive)}))


if __name__ == '__main__': main()
