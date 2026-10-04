import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner
from kubernetes.client.exceptions import ApiException

from main import app
from pifanctl.topology import cli
from pifanctl.topology.kube import APIError, Kube, resource
from pifanctl.topology.model import bundle, normalize
from test_topology import fan, zone, node

runner = CliRunner()


@pytest.fixture
def file(tmp_path):
    p = tmp_path / 'topology.yaml'
    p.write_text(yaml.safe_dump(bundle(normalize([fan(), zone(telemetry={'source': 'local'})]))))
    return p


class FakeClient:
    def __init__(self): self.calls = []; self.fail = None
    def call_api(self, path, method, **kwargs):
        self.calls.append((path, method, kwargs))
        if self.fail:
            error = ApiException(status=self.fail, reason='test'); error.body = 'PRIVATE'; raise error
        return kwargs.get('body') or {'items': []}


def test_adapter():
    client = FakeClient(); k = Kube(client=client)
    k.get('/api/v1/nodes'); k.patch('/some', {'x': 1}); k.apply(fan(), True)
    path, method, args = client.calls[-1]
    assert path == resource('Fan', 'fan-a') and method == 'PATCH'
    assert dict(args['query_params']) == {'fieldManager': 'pifanctl-cli', 'force': 'false', 'dryRun': 'All'}
    assert args['header_params']['Content-Type'] == 'application/apply-patch+yaml'
    assert args['_request_timeout'] == (3, 10)
    client.fail = 404; assert k.optional('/missing') is None
    client.fail = 403
    with pytest.raises(APIError, match='403') as e: k.optional('/denied')
    assert 'PRIVATE' not in str(e.value)


def test_auth_selection(monkeypatch):
    from kubernetes import config, client
    calls = []
    monkeypatch.setattr(config, 'new_client_from_config', lambda **kw: calls.append(kw) or FakeClient())
    monkeypatch.setattr(config, 'load_incluster_config', lambda: calls.append('incluster'))
    monkeypatch.setattr(client, 'ApiClient', FakeClient)
    Kube('path', 'context'); assert calls[-1] == {'config_file': 'path', 'context': 'context'}
    monkeypatch.setenv('KUBERNETES_SERVICE_HOST', 'fake')
    Kube(); assert calls[-1] == 'incluster'


def test_offline_commands(file):
    for command in ['validate', 'render', 'plan']:
        result = runner.invoke(app, ['topology', command, str(file)])
        assert result.exit_code == 0, result.output
    assert runner.invoke(app, ['topology', 'plan', str(file), '--node', 'pi-a']).exit_code == 0
    file.write_text('bad')
    result = runner.invoke(app, ['topology', 'validate', str(file)])
    assert result.exit_code == 2 and 'object' in result.output


def test_cluster_commands(file, monkeypatch):
    class Fake:
        def __init__(self, kubeconfig, context):
            assert (kubeconfig, context) == ('config', 'lab')
        def items(self, path): return [node()]
        def get(self, path): return {'kind': 'List', 'metadata': {'resourceVersion': '1'}, 'items': []}
        def apply(self, item, dry_run): assert dry_run; return item
    monkeypatch.setattr(cli, 'Kube', Fake)
    root = ['--kubeconfig', 'config', '--context', 'lab']
    for args in [['topology', 'apply', str(file), '--dry-run'], ['topology', 'validate', str(file), '--live'],
        ['fan', 'list'], ['zone', 'describe', 'rack'], ['fan', 'watch', '--once']]:
        result = runner.invoke(app, root + args); assert result.exit_code == 0, result.output


def test_worker_local_and_identity(file, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, 'run', lambda path, *args, **kwargs: calls.append((kwargs['loader'](Path(path).read_text()), args)))
    result = runner.invoke(app, ['worker', 'run', '--file', str(file), '--node', 'pi-a', '--mock'])
    assert result.exit_code == 0, result.output
    assert calls[0][0]['fans']['fan-a']['nodeName'] == 'pi-a'
    result = runner.invoke(app, ['worker', 'run', '--file', str(file), '--node', 'remote'])
    assert result.exit_code == 2 and 'host' in result.output
    assert runner.invoke(app, ['worker', 'run', '--plan-file', str(file)]).exit_code == 2
    assert runner.invoke(app, ['worker', 'run', '--mock']).exit_code == 2
    assert runner.invoke(app, ['worker', 'run', '--file', str(file), '--node', 'empty', '--mock']).exit_code == 2


def test_dangling_reference(file):
    file.write_text(yaml.safe_dump(bundle([zone()])))
    result = runner.invoke(app, ['topology', 'validate', str(file)])
    assert result.exit_code == 2 and 'MissingFan' in result.output


def test_watch_recovery(monkeypatch):
    class Fake:
        def __init__(self, *args): self.count = 0
        def get(self, path): return {'metadata': {'resourceVersion': '1'}, 'items': []}
        def events(self, kind, rv):
            self.count += 1
            if self.count == 1: yield {'type': 'ERROR', 'object': {'code': 410}}
            elif self.count == 2: raise APIError(410, 'Expired')
            else: raise KeyboardInterrupt()
    monkeypatch.setattr(cli, 'Kube', Fake)
    assert runner.invoke(app, ['fan', 'watch']).exit_code != 0


def test_watch_wrapper_and_auth_transport_errors(monkeypatch):
    from kubernetes import config, client, watch
    from kubernetes.config.config_exception import ConfigException
    from urllib3.exceptions import HTTPError
    calls = []
    class Stream:
        def stream(self, method, *args, **kwargs):
            calls.append((args, kwargs)); yield {'type': 'ADDED'}
        def stop(self): calls.append('stopped')
    monkeypatch.setattr(watch, 'Watch', Stream)
    monkeypatch.setattr(client, 'CoreV1Api', lambda c: type('Core', (), {'list_node': None})())
    monkeypatch.setattr(client, 'CustomObjectsApi', lambda c: type('Custom', (), {'list_cluster_custom_object': None})())
    k = Kube(client=FakeClient())
    assert list(k.events('Node')) == [{'type': 'ADDED'}]
    assert list(k.events('Fan', '42')) == [{'type': 'ADDED'}]
    assert calls[-2][1]['resource_version'] == '42' and calls[-1] == 'stopped'
    def auth_fail(**kwargs): raise ConfigException('PRIVATE')
    monkeypatch.setattr(config, 'new_client_from_config', auth_fail)
    with pytest.raises(APIError, match='credentials'): Kube('path')
    def transport_fail(*args, **kwargs): raise HTTPError('PRIVATE')
    monkeypatch.setattr(k.client, 'call_api', transport_fail)
    with pytest.raises(APIError, match='transport'): k.get('/api/v1/nodes')
