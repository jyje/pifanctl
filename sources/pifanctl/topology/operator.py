"""Topology reconciliation without hardware privileges or remote GPIO calls."""
import copy
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.request import urlopen

import typer

from pifanctl import __version__
from pifanctl.service import install_stop_handlers
from pifanctl.topology.kube import APIError, Kube, name, resource
from pifanctl.topology.model import API, TopologyError, parse, digest
from pifanctl.topology.planner import plan, worker_plan

log = logging.getLogger(__name__)
OWNER = 'pifanctl.jyje.online/operator'
FINALIZER = 'pifanctl.jyje.online/release'
app = typer.Typer(help='Reconcile topology into node-bound worker plans')


def timestamp(now):
    return datetime.fromtimestamp(now, timezone.utc).isoformat().replace('+00:00', 'Z')


def seconds(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()


class Lease:
    def __init__(self, kube, namespace, lease_name, holder=None):
        self.kube, self.holder = kube, holder or str(uuid.uuid4())
        self.path = f'/apis/coordination.k8s.io/v1/namespaces/{name(namespace)}/leases'
        self.name = lease_name

    def acquire(self, now=None):
        now = time.time() if now is None else now
        path = self.path + '/' + name(self.name)
        old = self.kube.optional(path)
        if old:
            spec = old.get('spec', {})
            if spec.get('holderIdentity') != self.holder:
                try: expired = now - seconds(spec.get('renewTime', spec.get('acquireTime', ''))) > spec.get('leaseDurationSeconds', 30)
                except (ValueError, TypeError): expired = False
                if not expired: return False
        body = {'apiVersion': 'coordination.k8s.io/v1', 'kind': 'Lease',
                'metadata': {'name': self.name}, 'spec': {'holderIdentity': self.holder,
                'leaseDurationSeconds': 30, 'renewTime': timestamp(now)}}
        if old: body['metadata']['resourceVersion'] = old['metadata']['resourceVersion']
        try:
            result = self.kube.request('PUT' if old else 'POST', path if old else self.path, body)
            return result['spec']['holderIdentity'] == self.holder
        except APIError as error:
            if error.status == 409: return False
            raise


def worker_name(node):
    return 'pifanctl-worker-' + hashlib.sha256(node.encode()).hexdigest()[:16]


def worker_deployment(namespace, operator_id, node, uid, hostname, config, image, owner):
    worker = worker_name(node)
    labels = {OWNER: operator_id, 'pifanctl.jyje.online/node': worker,
              'app.kubernetes.io/component': 'worker'}
    return {'apiVersion': 'apps/v1', 'kind': 'Deployment',
        'metadata': {'name': worker, 'namespace': namespace, 'labels': labels,
                     'annotations': {OWNER: operator_id}, 'ownerReferences': [owner]},
        'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'},
            'selector': {'matchLabels': {'pifanctl.jyje.online/node': worker}},
            'template': {'metadata': {'labels': labels}, 'spec': {
                'automountServiceAccountToken': False, 'terminationGracePeriodSeconds': 30,
                'affinity': {'nodeAffinity': {'requiredDuringSchedulingIgnoredDuringExecution': {'nodeSelectorTerms': [
                    {'matchExpressions': [{'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': [hostname]}],
                     'matchFields': [{'key': 'metadata.name', 'operator': 'In', 'values': [node]}]}]}}},
                'tolerations': [{'operator': 'Exists'}],
                'containers': [{'name': 'worker', 'image': image, 'imagePullPolicy': 'IfNotPresent',
                    'command': ['python', 'main.py', 'worker', 'run', '--node', node, '--uid', uid,
                                '--plan-file', '/etc/pifanctl/plan.json', '--heartbeat-file', '/etc/pifanctl/heartbeat.json'],
                    'env': [{'name': 'NODE_NAME', 'valueFrom': {'fieldRef': {'fieldPath': 'spec.nodeName'}}}],
                    'ports': [{'name': 'status', 'containerPort': 9103}],
                    'livenessProbe': {'httpGet': {'path': '/healthz', 'port': 'status'}, 'initialDelaySeconds': 10},
                    'readinessProbe': {'httpGet': {'path': '/readyz', 'port': 'status'}},
                    'resources': {'requests': {'cpu': '20m', 'memory': '64Mi'}, 'limits': {'memory': '256Mi'}},
                    'securityContext': {'runAsUser': 0, 'privileged': True, 'readOnlyRootFilesystem': True},
                    'volumeMounts': [{'name': 'config', 'mountPath': '/etc/pifanctl', 'readOnly': True},
                        {'name': 'sys', 'mountPath': '/sys'}, {'name': 'dev', 'mountPath': '/dev'},
                        {'name': 'locks', 'mountPath': '/var/lock/pifanctl'}]}],
                'volumes': [{'name': 'config', 'configMap': {'name': config}},
                    {'name': 'sys', 'hostPath': {'path': '/sys', 'type': 'Directory'}},
                    {'name': 'dev', 'hostPath': {'path': '/dev', 'type': 'Directory'}},
                    {'name': 'locks', 'hostPath': {'path': '/var/lock/pifanctl', 'type': 'DirectoryOrCreate'}}]}}}}


class Operator:
    def __init__(self, kube, namespace='pifanctl', operator_id='pifanctl', input_configmap=None,
                 image=None, report_reader=None):
        self.kube, self.namespace, self.id = kube, namespace, operator_id
        self.input_configmap = input_configmap
        self.image = image or f'ghcr.io/jyje/pifanctl:v{__version__}'
        self.core = f'/api/v1/namespaces/{name(namespace)}'
        self.apps = f'/apis/apps/v1/namespaces/{name(namespace)}'
        self.lease = Lease(kube, namespace, operator_id)
        self.report_reader = report_reader or self.read_report
        self.last_status, self.events = {}, {}
        self.ready = False

    def owner(self, item):
        m = item['metadata']
        return {'apiVersion': item['apiVersion'], 'kind': item['kind'], 'name': m['name'],
                'uid': m['uid'], 'controller': True, 'blockOwnerDeletion': True}

    def protect(self, item, path):
        m = item['metadata']; annotations = m.get('annotations', {})
        if annotations.get(OWNER) not in (None, self.id):
            raise TopologyError(f"{item['kind']}/{m['name']} belongs to another operator")
        if FINALIZER not in m.get('finalizers', []) or annotations.get(OWNER) != self.id:
            if m.get('deletionTimestamp'): raise TopologyError('cannot adopt a deleting resource')
            self.kube.patch(path, {'metadata': {'resourceVersion': m['resourceVersion'],
                'annotations': {OWNER: self.id}, 'finalizers': m.get('finalizers', []) + ([] if FINALIZER in m.get('finalizers', []) else [FINALIZER])}})

    def managed(self, collection, desired):
        path = collection + '/' + name(desired['metadata']['name'])
        old = self.kube.optional(path)
        if old:
            m = old['metadata']
            if m.get('annotations', {}).get(OWNER) != self.id:
                raise TopologyError(f"refusing to adopt {desired['kind']}/{m['name']}")
            if m.get('deletionTimestamp'): raise TopologyError('managed workload is deleting')
            # Preserve foreign annotations and avoid no-op API writes.
            desired = copy.deepcopy(desired)
            desired['metadata']['annotations'] = {**m.get('annotations', {}), **desired['metadata'].get('annotations', {})}
            if all(old.get(k) == v for k, v in desired.items() if k != 'metadata') and all(m.get(k) == v for k, v in desired['metadata'].items()):
                return old
            return self.kube.patch(path, desired)
        return self.kube.request('POST', collection, desired)

    def read_report(self, worker, now):
        pods = self.kube.items(self.core + '/pods?labelSelector=pifanctl.jyje.online%2Fnode%3D' + worker)
        pods = [p for p in pods if not p['metadata'].get('deletionTimestamp') and p.get('status', {}).get('podIP')]
        if len(pods) != 1: return None
        import ipaddress
        address = ipaddress.ip_address(pods[0]['status']['podIP'])
        host = f'[{address}]' if address.version == 6 else str(address)
        try:
            with urlopen(f'http://{host}:9103/status', timeout=2) as response:
                result = json.loads(response.read(512_000))
            if not -5 <= now - float(result['heartbeatTime']) <= 90: return None
            return result
        except (OSError, ValueError, KeyError, TypeError): return None

    def snapshot(self):
        source = None
        if self.input_configmap:
            source = self.kube.get(self.core + '/configmaps/' + name(self.input_configmap))
            items = parse(source.get('data', {}).get('topology.yaml', ''))
        else:
            items = self.kube.items(resource('Fan')) + self.kube.items(resource('CoolingZone'))
        return items, source, self.kube.items('/api/v1/nodes')

    def reconcile(self, now=None):
        now = time.time() if now is None else now
        self.ready = False
        if not self.lease.acquire(now): return False
        items, source, nodes = self.snapshot()
        for item in ([source] if source else items):
            path = self.core + '/configmaps/' + name(item['metadata']['name']) if source else resource(item['kind'], item['metadata']['name'])
            self.protect(item, path)
        # Planner sees deleting resources for conflicts, but workers receive a
        # plan with deletion targets removed before finalizer acknowledgement.
        full = plan(items, nodes)
        desired_items = [] if source and source['metadata'].get('deletionTimestamp') else [i for i in items if not i['metadata'].get('deletionTimestamp')]
        topology = plan(desired_items, nodes)
        for f, value in topology['fans'].items():
            value['issues'] = sorted(set(value['issues']) | set(full['fans'][f]['issues']))
        node_map = {n['metadata']['name']: n for n in nodes}
        configs = self.kube.items(self.core + '/configmaps')
        configs = {c['metadata'].get('labels', {}).get('pifanctl.jyje.online/nodeName'): c for c in configs
                   if c['metadata'].get('annotations', {}).get(OWNER) == self.id and 'plan.json' in c.get('data', {})}
        active = {f['nodeName'] for f in topology['fans'].values()}
        owners = {n: source or sorted([i for i in desired_items if i['kind'] == 'Fan' and i['spec']['nodeName'] == n], key=lambda i: i['metadata']['name'])[0] for n in active}
        reports, plans = {}, {}
        for node in sorted(active | configs.keys()):
            old = configs.get(node)
            if node not in node_map:
                # No heartbeat on an absent actuator Node. Leave deletion pending.
                reports[node] = None
                continue
            desired = worker_plan(topology, node)
            desired['nodeUID'] = node_map[node]['metadata']['uid']
            desired['hash'] = digest({k: v for k, v in desired.items() if k != 'hash'})
            plans[node] = desired
            if node in owners:
                owner = self.owner(owners[node])
            elif old:
                owner = old['metadata']['ownerReferences'][0]
            else: continue
            worker = worker_name(node); config = worker + '-plan'
            cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': config, 'namespace': self.namespace,
                  'labels': {'pifanctl.jyje.online/nodeName': node}, 'annotations': {OWNER: self.id}, 'ownerReferences': [owner]},
                  'data': {'plan.json': json.dumps(desired, sort_keys=True),
                           'heartbeat.json': json.dumps({'time': now, 'healthy': True, 'planHash': desired['hash'], 'nodeUID': desired['nodeUID']})}}
            # Revalidate leadership immediately before each workload/heartbeat write.
            if not self.lease.acquire(): return False
            self.managed(self.core + '/configmaps', cm)
            hostname = node_map[node]['metadata'].get('labels', {}).get('kubernetes.io/hostname')
            if not hostname: raise TopologyError('actuator Node requires kubernetes.io/hostname label')
            deployment = worker_deployment(self.namespace, self.id, node, desired['nodeUID'], hostname, config, self.image, owner)
            self.managed(self.apps + '/deployments', deployment)
            report = self.report_reader(worker, now)
            if not report or report.get('nodeName') != node or report.get('nodeUID') != desired['nodeUID'] or report.get('appliedTopologyHash') != desired['hash']:
                report = None
            reports[node] = report
        self.observe(items, source, topology, plans, reports, now)
        self.ready = True
        return True

    def observe(self, items, source, topology, plans, reports, now):
        # Status/finalizer reconciliation is added in the next checklist stage.
        return None


def run_operator(operator, stop=None):
    stop = stop or threading.Event(); install_stop_handlers(stop)
    # API polling resync is the correctness path; watches only wake it sooner.
    wake = threading.Event()
    def watch_loop(kind):
        while not stop.is_set():
            try:
                for _ in operator.kube.events(kind):
                    wake.set()
                    if stop.is_set(): break
            except Exception:
                log.warning('Watch disconnected; periodic reconciliation continues')
                stop.wait(5)
    for kind in ('Node',) if operator.input_configmap else ('Node', 'Fan', 'CoolingZone'):
        threading.Thread(target=watch_loop, args=(kind,), daemon=True).start()
    while not stop.is_set():
        try: operator.reconcile()
        except Exception as error:
            operator.ready = False
            log.error('Reconciliation failed (%s); worker heartbeat will expire', type(error).__name__)
        wake.wait(5); wake.clear()


@app.command('run')
def command(ctx: typer.Context, namespace: str = 'pifanctl', operator_id: str = 'pifanctl',
            configmap: str = '', image: str = ''):
    from pifanctl.topology.cli import api
    run_operator(Operator(api(ctx), namespace, operator_id, configmap or None, image or None))
