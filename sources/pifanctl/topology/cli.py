"""Topology commands share the operator planner and portable YAML schema."""
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import typer
import yaml

from pifanctl.metrics import resolve_node_name
from pifanctl.topology.kube import APIError, Kube, resource
from pifanctl.topology.model import TopologyError, bundle, load
from pifanctl.topology.planner import plan, worker_plan
from pifanctl.topology.worker import run

topology = typer.Typer(help='Validate, plan and apply Fan/CoolingZone YAML')
worker = typer.Typer(help='Drive only this host, never remote hardware')
fan = typer.Typer(help='Inspect physical fan resources')
zone = typer.Typer(help='Inspect cooling zone resources')


def api(ctx):
    options = ctx.find_root().obj or {}
    return Kube(options.get('kubeconfig'), options.get('context'))


def emit(value):
    typer.echo(yaml.safe_dump(value, sort_keys=False).rstrip())


def checked(path, kube=None):
    items = load(path)
    p = plan(items, kube.items('/api/v1/nodes') if kube else None)
    # Resolution problems are inspectable plans; invalid static relationships
    # cannot be applied by this convenience CLI.
    bad = {'HardwareConflict', 'MixedHardwareDrivers', 'MissingFan', 'InvalidLocalPlacement', 'TelemetryConflict'}
    issues = {i for group in ('fans', 'zones') for obj in p[group].values() for i in obj['issues']}
    if issues & bad: raise TopologyError(','.join(sorted(issues & bad)))
    return items, p


@topology.command('validate')
def validate(file: Path, live: bool = False, ctx: typer.Context = None):
    items, _ = checked(file, api(ctx) if live else None)
    typer.echo(f'Valid: {len(items)} resources')


@topology.command('render')
def render(file: Path):
    emit(bundle(load(file)))


@topology.command('plan')
def show_plan(file: Path, live: bool = False, node: Optional[str] = None, ctx: typer.Context = None):
    _, p = checked(file, api(ctx) if live else None)
    emit(worker_plan(p, node) if node else p)


@topology.command('apply')
def apply(file: Path, dry_run: bool = False, ctx: typer.Context = None):
    kube = api(ctx); items, _ = checked(file, kube)
    for item in bundle(items)['items']:
        result = kube.apply(item, dry_run)
        typer.echo(f"{result['kind']}/{result['metadata']['name']} " + ('validated (server dry-run)' if dry_run else 'applied'))


def inspect_group(group, kind):
    @group.command('list')
    def list_resources(ctx: typer.Context):
        emit(api(ctx).get(resource(kind)))

    @group.command('describe')
    def describe(resource_name: str, ctx: typer.Context):
        emit(api(ctx).get(resource(kind, resource_name)))

    @group.command('watch')
    def watch_resources(ctx: typer.Context, once: bool = False):
        kube = api(ctx)
        snapshot = kube.get(resource(kind)); emit(snapshot)
        if once: return
        rv = snapshot.get('metadata', {}).get('resourceVersion', '')
        while True:
            try:
                for event in kube.events(kind, rv):
                    emit(event)
                    obj = event.get('object', {})
                    if event.get('type') == 'ERROR':
                        if obj.get('code') == 410: break
                        raise APIError(obj.get('code', 500), obj.get('reason', 'WatchError'))
                    rv = obj.get('metadata', {}).get('resourceVersion', rv)
                # Relist covers expired history and the bounded watch timeout.
                snapshot = kube.get(resource(kind)); emit(snapshot)
                rv = snapshot.get('metadata', {}).get('resourceVersion', '')
            except APIError as error:
                if error.status != 410: raise
                rv = ''


inspect_group(fan, 'Fan')
inspect_group(zone, 'CoolingZone')


@worker.command('run')
def run_worker(ctx: typer.Context, node: Optional[str] = None, uid: str = '',
               file: Optional[Path] = None, plan_file: Optional[Path] = None,
               heartbeat_file: Optional[Path] = None, live: bool = False,
               thermal_path: str = '/sys/class/thermal', lock_dir: str = '/var/lock/pifanctl',
               port: int = 9103, mock: bool = False):
    identity = resolve_node_name()
    node = node or identity
    if not mock and node != identity:
        raise TopologyError('--node must equal NODE_NAME or this host name; set NODE_NAME only on the actuator host')
    if bool(file) == bool(plan_file):
        raise TopologyError('provide exactly one of --file or --plan-file')
    if plan_file:
        if not heartbeat_file or not uid:
            raise TopologyError('operator plan requires --heartbeat-file and --uid')
        run(plan_file, node, uid, thermal_path, lock_dir, heartbeat_file, port, mock)
    else:
        if heartbeat_file: raise TopologyError('local YAML does not use operator heartbeat')
        _, p = checked(file, api(ctx) if live else None)
        desired = worker_plan(p, node)
        if not desired['fans']: raise TopologyError('no fan assigned to this host')
        with tempfile.TemporaryDirectory(prefix='pifanctl-plan-') as directory:
            path = Path(directory) / 'plan.json'; path.write_text(json.dumps(desired))
            run(path, node, desired['nodeUID'], thermal_path, lock_dir, None, port, mock)


def register(app):
    app.add_typer(topology, name='topology')
    app.add_typer(fan, name='fan')
    app.add_typer(zone, name='zone')
    app.add_typer(worker, name='worker')
    from pifanctl.topology.operator import app as operator_app
    app.add_typer(operator_app, name='operator')
