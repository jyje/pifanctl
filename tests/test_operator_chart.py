import json
import re
import subprocess
from pathlib import Path

import yaml
import pytest
from typer.testing import CliRunner

from pifanctl.topology.model import SCHEMAS
from pifanctl.topology.operator import app as operator_app
from pifanctl.topology.operator import worker_deployment


CHART = Path('charts/pifanctl-operator')


def render(*args):
    result = subprocess.run(['helm', 'template', 'test', str(CHART), '-n', 'system', '--include-crds', *args], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return [o for o in yaml.safe_load_all(result.stdout) if o]


def test_default_operator_chart():
    objects = render(); d = next(o for o in objects if o['kind'] == 'Deployment')
    pod = d['spec']['template']['spec']; c = pod['containers'][0]
    assert d['spec']['replicas'] == 1
    assert d['spec']['strategy'] == {'type': 'Recreate'}
    assert pod['securityContext']['runAsNonRoot']
    assert 'volumes' not in pod
    chart = yaml.safe_load((CHART / 'Chart.yaml').read_text())
    assert c['image'] == f"ghcr.io/jyje/pifanctl:v{chart['appVersion']}"
    assert c['readinessProbe']['httpGet']['path'] == '/readyz'
    assert len([o for o in objects if o['kind'] == 'CustomResourceDefinition']) == 2
    assert any(o['kind'] == 'NetworkPolicy' for o in objects)
    assert not any(o.get('kind') in {'Fan', 'CoolingZone'} for o in objects)
    role = next(o for o in objects if o['kind'] == 'Role' and o['metadata']['name'] == 'test-operator')
    assert not any('configmaps/finalizers' in r['resources'] for r in role['rules'])


def test_extra_resources_render_fan_and_zone_custom_resources():
    values = Path('tests/fixtures/operator-extra-resources.yaml')
    objects = render('-f', str(values))
    fan = next(o for o in objects if o.get('kind') == 'Fan')
    zone = next(o for o in objects if o.get('kind') == 'CoolingZone')
    assert fan['metadata']['name'] == 'rack-fan-01'
    assert zone['metadata']['name'] == 'rack-a'
    assert zone['spec']['fanRefs'] == ['rack-fan-01']
    crd_index = max(i for i, o in enumerate(objects) if o['kind'] == 'CustomResourceDefinition')
    assert crd_index < min(i for i, o in enumerate(objects) if o.get('kind') in {'Fan', 'CoolingZone'})


def test_extra_resources_require_kubernetes_resource_envelopes():
    result = subprocess.run(
        ['helm', 'template', 'test', str(CHART), '--set-json', 'extraResources=[{"kind":"Fan"}]'],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_operator_cli_does_not_offer_configmap_topology_mode():
    result = CliRunner().invoke(operator_app, ['--help'])
    assert result.exit_code == 0
    assert '--configmap' not in result.output


def test_agent_monitor_and_security():
    objects = render('--set', 'serviceMonitor.enabled=true')
    assert any(o['kind'] == 'ServiceMonitor' for o in objects)
    pod = next(o for o in objects if o['kind'] == 'DaemonSet')['spec']['template']['spec']
    assert not pod['automountServiceAccountToken']
    assert all(m['readOnly'] for m in pod['containers'][0]['volumeMounts'])


@pytest.mark.parametrize('values', ['operatorId=Bad', 'replicas=0', 'input.mode=configMap', 'agent.mode=wrong'])
def test_invalid_chart(values):
    r = subprocess.run(['helm', 'template', 't', str(CHART), '--set', values], capture_output=True, text=True)
    assert r.returncode != 0


def test_packaged_schema_crd_parity():
    def strip(value):
        if isinstance(value, dict): return {k: strip(v) for k, v in value.items() if not k.startswith('x-kubernetes-') and k != 'additionalProperties'}
        if isinstance(value, list): return [strip(v) for v in value]
        return value
    for f in (CHART / 'crds').glob('*.yaml'):
        assert f.read_bytes() == Path('design/v1/crds', f.name).read_bytes()
        crd = yaml.safe_load(f.read_text()); kind = crd['spec']['names']['kind']
        spec = strip(crd['spec']['versions'][0]['schema']['openAPIV3Schema']['properties']['spec'])
        model = strip(SCHEMAS[kind]); model.pop('oneOf', None)
        if kind == 'Fan': model['properties']['hardware'].pop('oneOf')
        assert model == spec


def test_curve_default_supplies_cel_operands():
    # The API server validates the default object itself before nested defaults.
    # CEL expressions use these fields directly, so an empty default is invalid.
    for folder in (CHART / 'crds', Path('design/v1/crds')):
        crd = yaml.safe_load((folder / 'fans.yaml').read_text())
        curve = crd['spec']['versions'][0]['schema']['openAPIV3Schema']['properties']['spec']['properties']['control']['properties']['curve']
        assert curve['default'] == {key: prop['default'] for key, prop in curve['properties'].items()}
        assert curve['default'] == SCHEMAS['Fan']['properties']['control']['properties']['curve']['default']


def test_topology_helm_matches_file():
    from pifanctl.topology.model import parse
    from pifanctl.topology.planner import plan
    output = subprocess.check_output(['helm', 'template', 't', 'design/v1/helm', '-f', 'design/v1/examples/helm-values.yaml'], text=True)
    items = parse(output)
    cm_output = subprocess.check_output(['helm', 'template', 't', 'design/v1/helm', '-f', 'design/v1/examples/helm-values.yaml', '--set', 'mode=configMap'], text=True)
    cm = yaml.safe_load(cm_output)
    assert items == parse(cm['data']['topology.yaml'])


def test_worker_generated_resource_is_valid_shape(tmp_path):
    owner = {'apiVersion': 'pifanctl.jyje.online/v1alpha1', 'kind': 'Fan', 'name': 'fan-a', 'uid': 'uid', 'controller': True, 'blockOwnerDeletion': True}
    d = worker_deployment('system', 'operator', 'pi-a', 'node-uid', 'pi-host', 'config', 'image:v1', owner)
    assert all(v['hostPath']['path'] in ['/sys', '/dev', '/var/lock/pifanctl'] for v in d['spec']['template']['spec']['volumes'] if 'hostPath' in v)


def test_cluster_event_rbac_is_limited_to_default():
    objects = render()
    role = next(o for o in objects if o['kind'] == 'Role' and o['metadata'].get('namespace') == 'default')
    assert role['rules'] == [{'apiGroups': [''], 'resources': ['events'], 'verbs': ['create']}]
    binding = next(o for o in objects if o['kind'] == 'RoleBinding' and o['metadata'].get('namespace') == 'default')
    assert binding['subjects'][0]['namespace'] == 'system'


@pytest.mark.parametrize('agent_mode', ['managed', 'reuse'])
def test_worker_metrics_remain_visible_when_unready(agent_mode):
    objects = render('--set', f'serviceMonitor.enabled=true,agent.mode={agent_mode},operatorId=rack,serviceMonitor.labels.release=prometheus')
    service = next(o for o in objects if o['kind'] == 'Service' and o['metadata']['name'] == 'test-operator-worker')
    assert service['spec']['publishNotReadyAddresses'] is True
    assert service['spec']['selector'] == {'pifanctl.jyje.online/operator': 'rack', 'app.kubernetes.io/component': 'worker'}
    assert service['spec']['ports'] == [{'name': 'metrics', 'port': 9103, 'targetPort': 'status'}]
    monitor = next(o for o in objects if o['kind'] == 'ServiceMonitor' and o['metadata']['name'] == 'test-operator-worker')
    assert monitor['metadata']['labels']['release'] == 'prometheus'
    assert monitor['spec']['endpoints'][0] == {'port': 'metrics', 'interval': '10s'}
    selector = monitor['spec']['selector']['matchLabels']
    assert all(service['metadata']['labels'][key] == value for key, value in selector.items())
    owner = {'apiVersion': 'pifanctl.jyje.online/v1alpha1', 'kind': 'Fan', 'name': 'fan-a', 'uid': 'uid'}
    worker = worker_deployment('system', 'rack', 'pi-a', 'uid', 'host', 'plan', 'image:tag', owner)
    assert all(worker['spec']['template']['metadata']['labels'][key] == value for key, value in service['spec']['selector'].items())


def test_worker_scrape_is_opt_in():
    assert not any(o['kind'] == 'ServiceMonitor' for o in render())


def test_primary_readmes_install_only_operator_chart():
    for path in (Path("README.md"), Path("README-ko.md")):
        text = path.read_text()
        assert "helm upgrade --install pifanctl charts/pifanctl-operator" in text
        assert "python main.py start" not in text
        assert "pifanctl start --" not in text
        assert "oci://ghcr.io/jyje/charts/pifanctl --" not in text
        assert "extraResources" in text and "CoolingZone" in text
        assert len(re.findall(r"!\[.*?\]\(docs/v1/figures/", text)) == 8


def test_stable_and_alpha_crd_versions_have_identical_contracts():
    for filename in ('fans.yaml', 'coolingzones.yaml'):
        crd = yaml.safe_load((CHART / 'crds' / filename).read_text())
        assert crd == yaml.safe_load((Path('design/v1/crds') / filename).read_text())
        versions = crd['spec']['versions']
        assert [(v['name'], v['served'], v['storage']) for v in versions] == [('v1', True, True), ('v1alpha1', True, False)]
        assert crd['spec']['conversion'] == {'strategy': 'None'}
        assert {k: v for k, v in versions[0].items() if k not in {'name', 'storage'}} == {k: v for k, v in versions[1].items() if k not in {'name', 'storage'}}


def test_argocd_retains_shared_crds():
    crds = [obj for obj in render() if obj['kind'] == 'CustomResourceDefinition']
    assert len(crds) == 2
    for obj in crds:
        options = set(obj['metadata']['annotations']['argocd.argoproj.io/sync-options'].split(','))
        assert options == {'Prune=false', 'Delete=false'}


def test_worker_mounts_lock_at_direct_path_and_preserves_host_lock():
    owner = {'apiVersion': 'pifanctl.jyje.online/v1', 'kind': 'Fan', 'name': 'a', 'uid': 'uid'}
    d = worker_deployment('ns', 'operator', 'pi-a', 'node-uid', 'pi-a', 'config', 'image', owner)
    pod = d['spec']['template']['spec']
    container = pod['containers'][0]
    lock = next(m for m in container['volumeMounts'] if m['name'] == 'locks')
    assert lock['mountPath'] == '/run/lock/pifanctl'
    assert container['command'][-2:] == ['--lock-dir', '/run/lock/pifanctl']
    volume = next(v for v in pod['volumes'] if v['name'] == 'locks')
    assert volume['hostPath'] == {'path': '/var/lock/pifanctl', 'type': 'DirectoryOrCreate'}


def test_optional_tachometer_values_preserve_existing_topology():
    old = render('-f', 'tests/fixtures/operator-extra-resources.yaml')
    new = render('-f', 'tests/fixtures/operator-tachometer-values.yaml')
    old_fan = next(o for o in old if o.get('kind') == 'Fan')
    new_fan = next(o for o in new if o.get('kind') == 'Fan')
    feedback = new_fan['spec'].pop('feedback')
    assert feedback == {'tachometer': {'gpio': {'pin': 23, 'pull': 'up'},
                                      'pulsesPerRevolution': 2, 'sampleSeconds': 5}}
    assert new_fan == old_fan
    assert next(o for o in old if o.get('kind') == 'CoolingZone') == next(o for o in new if o.get('kind') == 'CoolingZone')


def test_supported_chart_follows_application_version():
    from pifanctl import __version__
    chart = yaml.safe_load((CHART / 'Chart.yaml').read_text())
    assert chart['version'] == chart['appVersion'] == __version__
