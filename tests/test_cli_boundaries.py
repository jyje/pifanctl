"""CLI behavior with real parsing and planning; substitute only cluster IO."""
import yaml
from typer.testing import CliRunner

from main import app
from pifanctl.topology import cli
from pifanctl.topology.kube import APIError
from pifanctl.topology.model import bundle
from test_topology import fan, zone, node


def test_watch_timeout_relists_before_next_watch(monkeypatch):
    class API:
        reads = 0
        watches = 0
        def get(self, path):
            self.reads += 1
            return {'metadata': {'resourceVersion': str(self.reads)}, 'items': []}
        def events(self, kind, rv):
            self.watches += 1
            if self.watches == 1:
                return iter([])  # Normal bounded watch timeout, not an error.
            assert rv == '2'
            raise APIError(403, 'Forbidden')
    api = API()
    monkeypatch.setattr(cli, 'api', lambda ctx: api)
    result = CliRunner().invoke(app, ['fan', 'watch'])
    assert result.exit_code == 2 and 'Forbidden' in result.output
    assert api.reads == 2 and api.watches == 2


def test_live_local_development_reloads_through_real_planner(tmp_path, monkeypatch):
    import threading
    from pifanctl.topology import worker
    path = tmp_path / 'topology.yaml'
    path.write_text(yaml.safe_dump(bundle([fan(), zone(telemetry={'source': 'local'})])))
    thermal = tmp_path / 'thermal_zone0'
    thermal.mkdir()
    (thermal / 'temp').write_text('55000')
    class API:
        def items(self, path): return [node()]
    monkeypatch.setattr(cli, 'api', lambda ctx: API())
    stop = threading.Event()
    real_run = cli.run
    real_cycle = worker.Worker.cycle
    states = []
    def cycle(instance, *args):
        state = real_cycle(instance, *args)
        states.append(state)
        stop.set()
        return state
    monkeypatch.setattr(worker.Worker, 'cycle', cycle)
    monkeypatch.setattr(cli, 'run', lambda *args, **kwargs: real_run(*args, **kwargs, stop=stop))
    result = CliRunner().invoke(app, ['worker', 'run', '--file', str(path), '--live', '--mock',
        '--node', 'pi-a', '--thermal-path', str(tmp_path), '--lock-dir', str(tmp_path / 'locks'), '--port', '0'])
    assert result.exit_code == 0, result.output
    assert states[0]['nodeUID'] == 'uid-a' and states[0]['ready']


def test_local_yaml_rejects_operator_heartbeat_before_runtime(tmp_path):
    path = tmp_path / 'topology.yaml'
    path.write_text(yaml.safe_dump(bundle([fan(), zone(telemetry={'source': 'local'})])))
    result = CliRunner().invoke(app, ['worker', 'run', '--file', str(path), '--mock',
        '--node', 'pi-a', '--heartbeat-file', str(tmp_path / 'heartbeat.json')])
    assert result.exit_code == 2 and 'local YAML does not use operator heartbeat' in result.output
