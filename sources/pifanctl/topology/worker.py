import copy
import json
import logging
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from prometheus_client import CollectorRegistry, Gauge, generate_latest

from pifanctl.control import CurveConfig, CurveController
from pifanctl.drivers import create_driver
from pifanctl.enum import Drivers
from pifanctl.service import install_stop_handlers
from pifanctl.sources import LocalSource
from pifanctl.thermal import TemperatureUnavailable
from pifanctl.topology.locks import HostLock
from pifanctl.topology.model import API, TopologyError, UniqueLoader, digest, normalize, _plain
from pifanctl.topology.planner import plan as topology_plan
from pifanctl.topology.telemetry import fan_reading
import yaml

log = logging.getLogger(__name__)


def validate_plan(raw, node, uid=''):
    _plain(raw)
    if not isinstance(raw, dict) or raw.get('format') != 1 or raw.get('nodeName') != node:
        raise TopologyError('invalid worker plan or node identity')
    if uid and raw.get('nodeUID') != uid:
        raise TopologyError('worker Node UID changed')
    body = {k: v for k, v in raw.items() if k != 'hash'}
    if raw.get('hash') != digest(body):
        raise TopologyError('plan hash does not match its contents')
    if not isinstance(raw.get('fans'), dict) or not 10 <= raw.get('watchdogSeconds', 0) <= 600:
        raise TopologyError('invalid plan fan map or watchdog')
    resources = []
    for name, fan in raw['fans'].items():
        if not isinstance(fan, dict) or fan.get('name') != name:
            raise TopologyError('fan identity mismatch')
        normalize([{'apiVersion': API, 'kind': 'Fan', 'metadata': {'name': name},
                    'spec': {k: fan[k] for k in ('nodeName', 'hardware', 'control')}}])
        if fan['nodeName'] != node or not isinstance(fan.get('zones'), list) or not isinstance(fan.get('issues'), list):
            raise TopologyError('fan does not belong to this worker')
        for zone in fan['zones']:
            if not isinstance(zone, dict): raise TopologyError('zone must be an object')
            normalize([{'apiVersion': API, 'kind': 'CoolingZone', 'metadata': {'name': zone['name']},
                        'spec': {'nodeNames': zone['members'] or ['unresolved'], 'fanRefs': zone['fanRefs'], 'telemetry': zone['telemetry']}}])
            if not isinstance(zone.get('issues'), list) or (not zone['members'] and not zone['issues']):
                raise TopologyError('invalid zone health')
        resources.append({'apiVersion': API, 'kind': 'Fan', 'metadata': {'name': name},
                          'spec': {k: fan[k] for k in ('nodeName', 'hardware', 'control')}})
    checked = topology_plan(resources)
    for name, spec in checked['fans'].items():
        for issue in ('HardwareConflict', 'MixedHardwareDrivers'):
            if issue in spec['issues'] and issue not in raw['fans'][name]['issues']:
                raise TopologyError('unreported hardware conflict')
    return copy.deepcopy(raw)


class Worker:
    def __init__(self, node, uid='', thermal_path='/sys/class/thermal', mock=False, driver_factory=None):
        self.node, self.uid, self.mock = node, uid, mock
        self.local = LocalSource(thermal_path)
        self.driver_factory = driver_factory or create_driver
        self.plan = None
        self.drivers, self.controllers, self.specs = {}, {}, {}
        self.updated = {}
        self.released = set()
        self.report = {'nodeName': node, 'nodeUID': uid, 'appliedTopologyHash': '', 'fans': {}, 'releasedFans': [], 'heartbeatTime': 0, 'ready': False, 'reason': 'Starting'}
        self.mutex = threading.Lock()
        self.actuation = threading.RLock()
        self.safety_error = ''
        self.progress = time.monotonic()
        self.registry = CollectorRegistry()
        self.duty = Gauge('pifanctl_worker_fan_duty_percent', 'Requested fan duty', ['node', 'fan'], registry=self.registry)
        self.health = Gauge('pifanctl_worker_fan_ready', 'Fan regulation is healthy', ['node', 'fan'], registry=self.registry)
        self.zone_temp = Gauge('pifanctl_worker_zone_temperature_celsius', 'Complete zone maximum', ['node', 'zone'], registry=self.registry)

    def apply(self, raw):
        with self.actuation:
            return self._apply(raw)

    def _apply(self, raw):
        new = validate_plan(raw, self.node, self.uid)
        def claim(spec):
            family = next(iter(spec['hardware']))
            cfg = spec['hardware'][family]
            return (family, cfg.get('pin'), cfg.get('chip'), cfg.get('channel'))
        for name, spec in new['fans'].items():
            if any(old != name and claim(existing) == claim(spec) for old, existing in self.specs.items()):
                raise TopologyError('release the previous fan identity before reusing its channel')
        # Same identity may not change hardware inside a live process.
        for name, spec in new['fans'].items():
            if name in self.specs and spec['hardware'] != self.specs[name]['hardware']:
                raise TopologyError('hardware change requires acknowledged replacement')
        for name, spec in new['fans'].items():
            if name not in self.drivers:
                # Conflicting desired claims cannot initialize a second driver.
                if any(reason in spec['issues'] for reason in ('HardwareConflict', 'MixedHardwareDrivers', 'MissingWorkerNode')):
                    continue
                hw = spec['hardware']; family = next(iter(hw)); cfg = hw[family]
                driver = self.driver_factory(Drivers.MOCK if self.mock else Drivers(family), cfg.get('pin', 18), cfg['frequencyHz'], 100,
                                             cfg.get('chip', 0), cfg.get('channel', 2))
                self.drivers[name] = driver
                driver.set_duty(100)
                self.released.discard(name)
            c = spec['control']['curve']
            config = CurveConfig(c['temperatureLow'], c['temperatureHigh'], c['dutyIdle'], c['dutyStart'], c['dutyMax'], c['dutyDownStep'],
                                 c.get('temperatureHysteresis', 5.0))
            if name not in self.controllers or self.controllers[name].config != config:
                self.controllers[name] = CurveController(config, 100)
            self.specs[name] = spec
        for name in list(self.drivers):
            if name not in new['fans']:
                self.drivers[name].set_duty(100)
                self.drivers[name].close()
                del self.drivers[name]; del self.controllers[name]; del self.specs[name]
                self.updated.pop(name, None)
                self.duty.remove(self.node, name)
                self.health.remove(self.node, name)
                self.released.add(name)
        self.plan = new
        self.released = set(sorted(self.released)[-128:])

    def trip(self, reason):
        # Publish the latch before touching hardware so a late query cannot
        # undo the watchdog. Only the main loop may clear it after revalidation.
        self.safety_error = reason
        with self.actuation:
            self.safety_error = reason
            for name, driver in self.drivers.items():
                try:
                    driver.set_duty(100)
                    if name in self.controllers: self.controllers[name].force(100)
                except Exception:
                    log.error('Watchdog could not write full duty to %s', name)
                self.duty.labels(self.node, name).set(100)
                self.health.labels(self.node, name).set(0)
        with self.mutex:
            self.report['ready'] = False
            self.report['reason'] = reason
            for state in self.report['fans'].values():
                state.update(ready=False, reason=reason, dutyPercent=100)

    def cycle(self, healthy=True, reason='', now=None):
        sample_now = now
        now = time.time() if now is None else now
        result = {'nodeName': self.node, 'nodeUID': self.uid, 'appliedTopologyHash': self.plan['hash'] if self.plan else '',
                  'fans': {}, 'releasedFans': sorted(self.released), 'heartbeatTime': now, 'ready': bool(self.plan), 'reason': reason}
        self.zone_temp.clear()
        try:
            local = self.local.read()
            if not math.isfinite(local): raise TemperatureUnavailable('invalid local sensor')
        except (TemperatureUnavailable, OSError, ValueError):
            local = None
        for name, spec in (self.plan or {}).get('fans', {}).items():
            temperature, nodes, zone_values = None, {}, {}
            failure = self.safety_error or (reason if not healthy else '')
            try:
                if failure: raise TemperatureUnavailable(failure)
                if local is None: raise TemperatureUnavailable('LocalSensorUnavailable')
                temperature, zone_values, nodes = fan_reading(spec, local, sample_now)
            except (TemperatureUnavailable, OSError, ValueError) as error:
                failure = str(error)
            if name not in self.drivers:
                failure = 'HardwareUnavailable'
                duty = 100
            else:
                with self.actuation:
                    failure = self.safety_error or failure
                    control = self.controllers[name]
                    if failure:
                        duty = control.force(100)
                        self.updated.pop(name, None)
                    elif now - self.updated.get(name, float('-inf')) >= spec['control']['refreshIntervalSeconds']:
                        duty = control.update(temperature)
                        self.updated[name] = now
                    else:
                        # Rising temperature is always acted on immediately.
                        from pifanctl.control import curve_target
                        duty = control.force(max(control.duty, curve_target(temperature, control.config)))
                    self.drivers[name].set_duty(duty)
            result['fans'][name] = {'dutyPercent': duty, 'temperatureCelsius': temperature, 'ready': not bool(failure),
                                    'reason': failure, 'zones': zone_values, 'nodes': nodes}
            result['ready'] = result['ready'] and not failure
            self.duty.labels(self.node, name).set(duty)
            self.health.labels(self.node, name).set(0 if failure else 1)
            for zone, value in zone_values.items(): self.zone_temp.labels(self.node, zone).set(value)
        with self.mutex:
            if self.safety_error:
                result.update(ready=False, reason=self.safety_error)
                for state in result['fans'].values(): state.update(ready=False, reason=self.safety_error, dutyPercent=100)
            self.report = result
        self.progress = time.monotonic()
        return result

    def snapshot(self):
        with self.mutex: return copy.deepcopy(self.report)

    def close(self):
        with self.actuation:
            return self._close()

    def _close(self):
        errors = []
        for driver in self.drivers.values():
            try: driver.set_duty(100)
            except Exception as error: errors.append(error)
            finally:
                try: driver.close()
                except Exception as error: errors.append(error)
        self.drivers.clear()
        if errors: raise errors[0]


def serve(worker, port, address='0.0.0.0'):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            state = worker.snapshot()
            if self.path == '/metrics': data, code, content_type = generate_latest(worker.registry), 200, 'text/plain; version=0.0.4'
            elif self.path in ('/status', '/healthz', '/readyz'):
                code = 503 if self.path == '/readyz' and not state['ready'] else 200
                data, content_type = json.dumps(state).encode(), 'application/json'
            else: data, code, content_type = b'not found', 404, 'text/plain'
            self.send_response(code); self.send_header('Content-Type', content_type); self.end_headers(); self.wfile.write(data)
        def log_message(self, *args): pass
    server = ThreadingHTTPServer((address, port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def heartbeat_ok(path, plan, now=None):
    now = time.time() if now is None else now
    try:
        value = json.loads(Path(path).read_text())
        age = now - float(value['time'])
        return value.get('healthy') is True and value.get('planHash') == plan['hash'] and value.get('nodeUID', '') == plan['nodeUID'] and -5 <= age <= plan['watchdogSeconds']
    except (OSError, ValueError, KeyError, TypeError): return False


def check_watchdog(worker, heartbeat_path=None, now=None, monotonic_now=None):
    if not worker.plan: return
    monotonic_now = time.monotonic() if monotonic_now is None else monotonic_now
    if heartbeat_path and not heartbeat_ok(heartbeat_path, worker.plan, now):
        worker.trip('OperatorHeartbeatExpired')
    elif monotonic_now - worker.progress > worker.plan['watchdogSeconds']:
        worker.trip('ControlLoopStalled')


def watch_safety(worker, heartbeat_path, stop):
    while not stop.wait(1): check_watchdog(worker, heartbeat_path)


def run(plan_path, node, uid='', thermal_path='/sys/class/thermal', lock_dir='/var/lock/pifanctl',
        heartbeat_path=None, port=9103, mock=False, stop=None, loader=None):
    stop = stop or threading.Event()
    install_stop_handlers(stop)
    worker = Worker(node, uid, thermal_path, mock)
    server = None
    last, error = None, 'NoPlan'
    with HostLock(lock_dir):
        guard_stop = threading.Event()
        guard = threading.Thread(target=watch_safety, args=(worker, heartbeat_path, guard_stop), daemon=True)
        guard.start()
        try:
            if port: server = serve(worker, port)
            while not stop.is_set():
                try:
                    text = Path(plan_path).read_text()
                    if text != last:
                        if len(text.encode()) > 900_000: raise TopologyError('worker plan too large')
                        worker.apply(loader(text) if loader else yaml.load(text, Loader=UniqueLoader))
                        last = text
                    error = ''
                except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as failure:
                    error = 'PlanInvalid: ' + str(failure)
                    log.error(error)
                healthy = not error and worker.plan is not None
                if healthy and heartbeat_path and not heartbeat_ok(heartbeat_path, worker.plan):
                    healthy, error = False, 'OperatorHeartbeatExpired'
                if healthy:
                    with worker.actuation:
                        # Recheck after acquiring the actuation lock; a watchdog
                        # trip may have happened while a query/lock was pending.
                        fresh = not heartbeat_path or heartbeat_ok(heartbeat_path, worker.plan)
                        progressed = time.monotonic() - worker.progress <= worker.plan['watchdogSeconds']
                        if fresh and progressed: worker.safety_error = ''
                worker.cycle(healthy, error)
                intervals = [f['control']['refreshIntervalSeconds'] for f in (worker.plan or {}).get('fans', {}).values()]
                stop.wait(min(intervals, default=5))
        finally:
            guard_stop.set(); guard.join()
            try: worker.close()
            finally:
                if server: server.shutdown(); server.server_close()
