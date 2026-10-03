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
from prometheus_client import CollectorRegistry, Gauge

from pifanctl import __version__
from pifanctl.service import install_stop_handlers
from pifanctl.topology.kube import APIError, Kube, name, resource
from pifanctl.topology.model import API, MAX_BYTES, TopologyError, parse, digest
from pifanctl.topology.planner import plan, worker_plan

log = logging.getLogger(__name__)
OWNER = 'pifanctl.jyje.online/operator'
FINALIZER = 'pifanctl.jyje.online/release'
RELEASED = 'pifanctl.jyje.online/released-hash'
RELEASE_NODES = 'pifanctl.jyje.online/release-nodes'
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
        self.last_reconcile = 0
        self.registry = CollectorRegistry()
        self.health = Gauge('pifanctl_operator_ready', 'Leader completed reconciliation recently', registry=self.registry)

    def snapshot(self):
        ready = self.ready and time.time() - self.last_reconcile < 30
        self.health.set(1 if ready else 0)
        return {'ready': ready, 'lastReconcileTime': self.last_reconcile, 'operator': self.id}

    def patch(self, path, body):
        if not self.lease.acquire(): raise TopologyError('LeadershipLost')
        return self.kube.patch(path, body)

    def write(self, method, path, body):
        if not self.lease.acquire(): raise TopologyError('LeadershipLost')
        return self.kube.request(method, path, body)

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
            self.patch(path, {'metadata': {'resourceVersion': m['resourceVersion'],
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
            return self.patch(path, desired)
        return self.write('POST', collection, desired)

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
            result['podName'] = pods[0]['metadata']['name']
            return result
        except (OSError, ValueError, KeyError, TypeError): return None

    def topology_snapshot(self):
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
        items, source, nodes = self.topology_snapshot()
        for item in ([source] if source else items):
            path = self.core + '/configmaps/' + name(item['metadata']['name']) if source else resource(item['kind'], item['metadata']['name'])
            self.protect(item, path)
        configs = self.kube.items(self.core + '/configmaps')
        configs = {c['metadata'].get('annotations', {}).get('pifanctl.jyje.online/nodeName'): c for c in configs
                   if c['metadata'].get('annotations', {}).get(OWNER) == self.id and 'plan.json' in c.get('data', {})}
        previous = {}; self.prior_zones = {}
        for node, config in configs.items():
            prior = json.loads(config['data']['plan.json'])
            for f in prior.get('fans', {}).values():
                for zone in f['zones']:
                    self.prior_zones.setdefault(zone['name'], set()).add(node)
                    previous[zone['name']] = zone
        if source:
            for item in items:
                item['metadata']['uid'] = digest([source['metadata']['uid'], item['kind'], item['metadata']['name']])
        # Deleted Nodes remain missing members; Node UID changes are sticky
        # until a reviewed zone replacement or membership edit.
        full = plan(items, nodes, previous)
        desired_items = [] if source and source['metadata'].get('deletionTimestamp') else [i for i in items if not i['metadata'].get('deletionTimestamp')]
        topology = plan(desired_items, nodes, previous)
        for f, value in topology['fans'].items():
            value['issues'] = sorted(set(value['issues']) | set(full['fans'][f]['issues']))
        node_map = {n['metadata']['name']: n for n in nodes}
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
            plan_text = json.dumps(desired, sort_keys=True)
            if len(plan_text.encode()) > MAX_BYTES:
                raise TopologyError('worker plan exceeds 900 KB; split the actuator topology')
            cm = {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': config, 'namespace': self.namespace,
                  'labels': {'pifanctl.jyje.online/node': worker}, 'annotations': {OWNER: self.id, 'pifanctl.jyje.online/nodeName': node}, 'ownerReferences': [owner]},
                  'data': {'plan.json': plan_text,
                           'heartbeat.json': json.dumps({'time': now, 'healthy': True, 'planHash': desired['hash'], 'nodeUID': desired['nodeUID']})}}
            # Revalidate leadership immediately before each workload/heartbeat write.
            if not self.lease.acquire(): return False
            self.managed(self.core + '/configmaps', cm)
            if not desired['fans'] and old and old['metadata'].get('annotations', {}).get(RELEASED) == desired['hash']:
                reports[node] = {'nodeName': node, 'nodeUID': desired['nodeUID'], 'appliedTopologyHash': desired['hash'],
                                 'fans': {}, 'released': True, 'heartbeatTime': now}
                continue
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
        self.last_reconcile = now
        return True

    def observe(self, items, source, topology, plans, reports, now):
        statuses = {}
        for item in items:
            kind, m, spec = item['kind'], item['metadata'], item['spec']
            resource_name = m['name']; generation = m.get('generation', 1)
            status = {'observedGeneration': generation, 'topologyHash': topology['hash']}
            if kind == 'Fan':
                node = spec['nodeName']; desired = plans.get(node, {})
                report = reports.get(node) or {}; state = report.get('fans', {}).get(resource_name, {})
                resolved = topology['fans'].get(resource_name, {})
                issues = resolved.get('issues', [])
                ready = bool(state.get('ready')) and not issues
                reason = issues[0] if issues else ('Regulating' if ready else state.get('reason') or 'AwaitingWorker')
                status.update(nodeUID=desired.get('nodeUID', ''), topologyHash=desired.get('hash', ''),
                              appliedTopologyHash=report.get('appliedTopologyHash', ''),
                              zoneNames=[z['name'] for z in resolved.get('zones', [])],
                              workerPodName=report.get('podName', ''))
                if state:
                    status['dutyPercent'] = state['dutyPercent']
                    if state.get('temperatureCelsius') is not None: status['controlTemperatureCelsius'] = state['temperatureCelsius']
                if report: status['heartbeatTime'] = timestamp(report['heartbeatTime'])
            else:
                resolved = topology['zones'].get(resource_name, {})
                members, refs = resolved.get('members', []), spec['fanRefs']
                issues = resolved.get('issues', [])
                states = [reports.get(topology['fans'].get(f, {}).get('nodeName')) or {} for f in refs]
                ready = not issues and bool(states) and all(s.get('fans', {}).get(f, {}).get('ready') for f, s in zip(refs, states))
                reason = issues[0] if issues else ('Regulating' if ready else 'AwaitingWorker')
                observed_nodes = {n for s in states for f in s.get('fans', {}).values() for n in f.get('nodes', {})}
                status.update(resolvedNodeNames=members, missingNodeNames=sorted(set(members) - observed_nodes),
                              fanNames=refs, memberCount=len(members), fanCount=len(refs))
                values = [s['fans'][f]['zones'][resource_name] for f, s in zip(refs, states)
                          if resource_name in s.get('fans', {}).get(f, {}).get('zones', {})]
                if ready and values:
                    status['temperatureCelsius'] = max(values); status['temperatureObservedAt'] = timestamp(now)
            if m.get('deletionTimestamp') or source and source['metadata'].get('deletionTimestamp'):
                ready, reason = False, 'Releasing'
            previous = item.get('status', {}).get('conditions', [])
            condition = {'type': 'Ready', 'status': 'True' if ready else 'False', 'reason': reason.split(':')[0].split(',')[0][:128],
                         'message': reason, 'observedGeneration': generation, 'lastTransitionTime': timestamp(now)}
            for c in previous:
                if c.get('type') == 'Ready' and c.get('status') == condition['status']:
                    condition['lastTransitionTime'] = c['lastTransitionTime']
            status['conditions'] = [condition]; statuses[kind + '/' + resource_name] = status
            if not source: self.write_status(item, status, now)
        if source:
            owner = self.owner(source)
            signature = digest({k: [v['topologyHash'], v['conditions'][0]['status'], v['conditions'][0]['reason']] for k, v in statuses.items()})
            key = source['metadata']['uid']; last = self.last_status.get(key)
            if not last or now - last[0] >= 30 or last[1] != signature:
                status_name = 'pifanctl-status-' + digest(source['metadata']['name'])[:16]
                self.managed(self.core + '/configmaps', {'apiVersion': 'v1', 'kind': 'ConfigMap',
                'metadata': {'name': status_name, 'namespace': self.namespace,
                             'annotations': {OWNER: self.id}, 'ownerReferences': [owner]},
                'data': {'status.json': json.dumps(statuses, sort_keys=True)}})
                self.last_status[key] = (now, signature)
        # First acknowledge empty plans, then delete workloads. Persist the hash
        # so a restart cannot recreate an acknowledged, retiring worker.
        retired = set()
        for node, desired in plans.items():
            report = reports.get(node)
            if desired['fans'] or not report or report.get('fans'): continue
            worker = worker_name(node); path = self.core + '/configmaps/' + worker + '-plan'
            cm = self.kube.optional(path)
            if not cm: retired.add(node); continue
            if cm['metadata'].get('annotations', {}).get(RELEASED) != desired['hash']:
                self.patch(path, {'metadata': {'annotations': {RELEASED: desired['hash']}}})
            deployment = self.apps + '/deployments/' + worker
            old = self.kube.optional(deployment)
            if old:
                if old['metadata'].get('annotations', {}).get(OWNER) != self.id:
                    raise TopologyError('refusing to delete a foreign workload')
                self.write('DELETE', deployment, {'apiVersion': 'v1', 'kind': 'DeleteOptions',
                    'propagationPolicy': 'Foreground', 'preconditions': {'uid': old['metadata']['uid']}})
            pods = self.kube.items(self.core + '/pods?labelSelector=pifanctl.jyje.online%2Fnode%3D' + worker)
            if pods or self.kube.optional(deployment): continue
            # Keep this empty-plan acknowledgement until owner GC. It survives
            # restarts while another node is still unreachable during deletion.
            retired.add(node)
        targets = [source] if source else items
        for item in targets:
            m = item['metadata']
            if not m.get('deletionTimestamp') or FINALIZER not in m.get('finalizers', []): continue
            if source:
                affected = set(plans) | {f['spec']['nodeName'] for f in items if f['kind'] == 'Fan'}
            elif item['kind'] == 'Fan': affected = {item['spec']['nodeName']}
            else:
                # Prior plans are the authoritative set after a zone is removed.
                affected = {f['spec']['nodeName'] for f in items if f['kind'] == 'Fan' and f['metadata']['name'] in item['spec']['fanRefs']}
                affected |= self.prior_zones.get(m['name'], set())
            annotation = m.get('annotations', {}).get(RELEASE_NODES)
            if annotation:
                affected |= set(json.loads(annotation))
            path = self.core + '/configmaps/' + name(m['name']) if source else resource(item['kind'], m['name'])
            if annotation != json.dumps(sorted(affected)):
                self.patch(path, {'metadata': {'annotations': {RELEASE_NODES: json.dumps(sorted(affected))}}})
            acknowledged = True
            for node in affected:
                if node in retired: continue
                report = reports.get(node)
                if not report:
                    # No remaining owned plan or workload means this operator
                    # has no runtime claim there (e.g. an already deleted Fan).
                    cm_path = self.core + '/configmaps/' + worker_name(node) + '-plan'
                    deploy_path = self.apps + '/deployments/' + worker_name(node)
                    if node not in plans and self.kube.optional(cm_path) is None and self.kube.optional(deploy_path) is None:
                        continue
                    acknowledged = False; break
                if item['kind'] == 'Fan' and m['name'] in report.get('fans', {}):
                    acknowledged = False; break
            if acknowledged:
                fresh = self.kube.get(path)
                self.patch(path, {'metadata': {'resourceVersion': fresh['metadata']['resourceVersion'],
                    'finalizers': [f for f in fresh['metadata'].get('finalizers', []) if f != FINALIZER]}})

    def write_status(self, item, status, now):
        key = item['metadata']['uid']; condition = status['conditions'][0]
        signature = (condition['status'], condition['reason'], status['topologyHash'], status['observedGeneration'])
        last = self.last_status.get(key)
        if last and now - last[0] < 30 and last[1] == signature: return
        # Merge patch nulls clear old temperature/duty fields during failures.
        patch = {k: None for k in item.get('status', {}) if k not in status}; patch.update(status)
        self.patch(resource(item['kind'], item['metadata']['name']) + '/status', {'status': patch})
        self.last_status[key] = (now, signature)
        if not last or last[1][:2] != signature[:2]:
            self.event(item, condition, now)

    def event(self, item, condition, now):
        m = item['metadata']; key = (m['uid'], condition['reason'])
        if key in self.events and now - self.events[key] < 60: return
        event_name = 'pifanctl-' + digest([m['uid'], condition['reason'], now])[:24]
        self.write('POST', self.core + '/events', {'apiVersion': 'v1', 'kind': 'Event',
            'metadata': {'name': event_name, 'namespace': self.namespace},
            'involvedObject': {'apiVersion': API, 'kind': item['kind'], 'name': m['name'], 'uid': m['uid']},
            'reason': condition['reason'].split(':')[0][:128], 'message': condition['message'][:2048],
            'type': 'Normal' if condition['status'] == 'True' else 'Warning',
            'source': {'component': 'pifanctl-operator'}, 'firstTimestamp': timestamp(now), 'lastTimestamp': timestamp(now), 'count': 1})
        self.events[key] = now


def run_operator(operator, stop=None, port=9104):
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
    from pifanctl.topology.worker import serve
    server = serve(operator, port) if port else None
    try:
        while not stop.is_set():
            try: operator.reconcile()
            except Exception as error:
                operator.ready = False
                log.error('Reconciliation failed (%s); worker heartbeat will expire', type(error).__name__)
            if stop.is_set(): break
            wake.wait(5); wake.clear()
    finally:
        if server: server.shutdown(); server.server_close()


@app.command('run')
def command(ctx: typer.Context, namespace: str = 'pifanctl', operator_id: str = 'pifanctl',
            configmap: str = '', image: str = ''):
    from pifanctl.topology.cli import api
    run_operator(Operator(api(ctx), namespace, operator_id, configmap or None, image or None))
