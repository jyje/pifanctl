from copy import deepcopy
import json
from pathlib import Path
import re
import sys

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_gitops_lifecycle import application, synced_healthy


def test_gitops_fixture_uses_immutable_source_and_supported_retirement():
    original = [{'apiVersion': 'pifanctl.jyje.online/v1', 'kind': 'Fan', 'metadata': {'name': 'a'}}]
    app = application('a' * 40, original)
    source = app['spec']['source']
    assert source['targetRevision'] == 'a' * 40
    assert source['repoURL'] == 'https://github.com/jyje/pifanctl'
    assert source['helm']['valuesObject']['image']['repository'] == 'pifanctl-runtime-lab'
    assert source['helm']['valuesObject']['agent']['mode'] == 'reuse'
    assert app['metadata']['finalizers'] == ['resources-finalizer.argocd.argoproj.io/background']
    assert 'PrunePropagationPolicy=background' in app['spec']['syncPolicy']['syncOptions']
    assert 'PruneLast=true' in app['spec']['syncPolicy']['syncOptions']
    original[0]['metadata']['name'] = 'changed'
    assert source['helm']['valuesObject']['extraResources'][0]['metadata']['name'] == 'a'


@pytest.mark.parametrize('revision', ['main', 'a' * 7, 'g' * 40, 'a' * 41])
def test_gitops_fixture_rejects_moving_or_invalid_revisions(revision):
    with pytest.raises(ValueError, match='immutable'):
        application(revision, [])


def test_gitops_probe_requires_sync_health_operation_and_no_errors():
    assert not synced_healthy({})
    source = application('a' * 40, [])['spec']['source']
    obj = {'spec': {'source': deepcopy(source)},
           'status': {'sync': {'status': 'Synced', 'revision': 'a' * 40,
                               'comparedTo': {'source': deepcopy(source)}},
                      'health': {'status': 'Healthy'},
                      'operationState': {'phase': 'Succeeded', 'syncResult': {
                          'source': deepcopy(source), 'revision': 'a' * 40}}}}
    assert synced_healthy(obj)
    for key, value in [('sync', 'OutOfSync'), ('health', 'Progressing'), ('operationState', 'Running')]:
        invalid = deepcopy(obj)
        invalid['status'][key]['phase' if key == 'operationState' else 'status'] = value
        assert not synced_healthy(invalid)
    obj['status']['conditions'] = [{'type': 'ComparisonError'}]
    assert not synced_healthy(obj)


def test_gitops_probe_rejects_stale_success_after_values_change():
    source = application('a' * 40, [])['spec']['source']
    obj = {'spec': {'source': deepcopy(source)},
           'status': {'sync': {'status': 'Synced', 'revision': 'a' * 40,
                               'comparedTo': {'source': deepcopy(source)}},
                      'health': {'status': 'Healthy'},
                      'operationState': {'phase': 'Succeeded', 'syncResult': {
                          'source': deepcopy(source), 'revision': 'a' * 40}}}}
    assert synced_healthy(obj)
    obj['spec']['source']['helm']['valuesObject']['extraResources'] = [{'kind': 'Fan'}]
    assert not synced_healthy(obj)
    obj['status']['sync']['comparedTo']['source'] = deepcopy(obj['spec']['source'])
    assert not synced_healthy(obj)
    obj['status']['operationState']['syncResult']['source'] = deepcopy(obj['spec']['source'])
    assert synced_healthy(obj)
    obj['status']['operationState']['syncResult']['revision'] = 'b' * 40
    assert not synced_healthy(obj)


def test_documented_argocd_example_pins_chart_and_valid_v1_instances():
    from pifanctl.topology.model import normalize
    root = Path(__file__).resolve().parents[1]
    obj = yaml.safe_load((root / 'design/v1/examples/argocd.yaml').read_text())
    assert re.fullmatch(r'operator-chart-v\d+\.\d+\.\d+(?:-[a-z0-9.]+)?',
                        obj['spec']['source']['targetRevision'])
    options = obj['spec']['syncPolicy']['syncOptions']
    assert 'PrunePropagationPolicy=background' in options and 'PruneLast=true' in options
    resources = normalize(obj['spec']['source']['helm']['valuesObject']['extraResources'])
    assert {o['kind'] for o in resources} == {'Fan', 'CoolingZone'}
    assert all(o['apiVersion'] == 'pifanctl.jyje.online/v1' for o in resources)
    zone = next(o for o in resources if o['kind'] == 'CoolingZone')
    assert zone['spec']['nodeNames'] == ['pi-01', 'pi-02', 'pi-03', 'pi-04']


def test_observed_stale_application_does_not_pass_release_check():
    path = Path(__file__).resolve().parent / 'fixtures/argocd-stale-success.json'
    obj = json.loads(path.read_text())
    assert obj['status']['sync']['status'] == 'Synced'
    assert obj['status']['health']['status'] == 'Healthy'
    assert obj['status']['operationState']['phase'] == 'Succeeded'
    assert obj['spec']['source'] != obj['status']['sync']['comparedTo']['source']
    assert not synced_healthy(obj)
