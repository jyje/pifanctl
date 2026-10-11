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


def test_optional_pwm_probe_extra_resources():
    from pifanctl.topology.model import normalize
    objects = render('-f', 'tests/fixtures/operator-pwm-probe-values.yaml')
    item = next(o for o in objects if o.get('kind') == 'Fan')
    cfg = normalize([item])[0]['spec']['feedback']
    assert cfg['pwm']['gpio'] == {'pin': 24, 'pull': 'off'}
    assert cfg['tachometer']['pulsesPerRevolution'] == 2


def worker_egress_policy(objects):
    return next((o for o in objects if o['kind'] == 'NetworkPolicy' and o['metadata']['name'].endswith('-worker-egress')), None)


def test_worker_egress_policy_is_opt_in():
    assert worker_egress_policy(render()) is None
    assert worker_egress_policy(render('--set', 'networkPolicy.enabled=false', '--set', 'networkPolicy.workerEgress.enabled=true')) is None


def test_worker_egress_allows_only_dns_and_prometheus():
    policy = worker_egress_policy(render('--set', 'networkPolicy.workerEgress.enabled=true',
                                         '--set', 'networkPolicy.workerEgress.prometheusPort=9091'))
    spec = policy['spec']
    assert spec['policyTypes'] == ['Egress'] and 'ingress' not in spec
    assert spec['podSelector']['matchLabels']['app.kubernetes.io/component'] == 'worker'
    dns, prometheus = spec['egress']
    assert {(p['protocol'], p['port']) for p in dns['ports']} == {('UDP', 53), ('TCP', 53)}
    assert dns['to'][0]['podSelector']['matchLabels'] == {'k8s-app': 'kube-dns'}
    assert prometheus['ports'] == [{'protocol': 'TCP', 'port': 9091}]
    assert prometheus['to'][0]['namespaceSelector']['matchLabels'] == {'kubernetes.io/metadata.name': 'observability'}
    assert all('ipBlock' not in peer for rule in spec['egress'] for peer in rule['to'])


@pytest.mark.parametrize('flag', [
    ['--set', 'networkPolicy.workerEgress.prometheusNamespaceSelector=null'],
    ['--set', 'networkPolicy.workerEgress.dnsPodSelector=null'],
    ['--set', 'networkPolicy.workerEgress.prometheusPort=abc'],
    ['--set', 'networkPolicy.workerEgress.prometheusPort=0'],
    ['--set-json', 'networkPolicy.workerEgress.prometheusPodSelector={"a":1}'],
])
def test_worker_egress_rejects_selectors_that_would_widen_access(flag):
    result = subprocess.run(['helm', 'template', 'test', str(CHART), '-n', 'system',
                             '--set', 'networkPolicy.workerEgress.enabled=true', *flag], capture_output=True, text=True)
    assert result.returncode != 0 and 'networkPolicy.workerEgress' in result.stderr


def roles(objects):
    return {(o['metadata'].get('namespace', 'system'), o['metadata']['name']): o for o in objects if o['kind'] == 'Role'}


def test_default_keeps_workers_in_the_release_namespace():
    objects = render()
    operator = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'test-operator')
    args = operator['spec']['template']['spec']['containers'][0]['args']
    assert args[args.index('--worker-namespace') + 1] == 'system'
    role = roles(objects)[('system', 'test-operator')]
    assert {'deployments', 'configmaps', 'pods'} <= {r for rule in role['rules'] for r in rule['resources']}
    assert not any(k[1].endswith('-workers') for k in roles(objects))


def test_separate_worker_namespace_splits_the_operator_role():
    objects = render('--set', 'workerNamespace=workers')
    operator = next(o for o in objects if o['kind'] == 'Deployment' and o['metadata']['name'] == 'test-operator')
    args = operator['spec']['template']['spec']['containers'][0]['args']
    assert args[args.index('--worker-namespace') + 1] == 'workers'
    own = {r for rule in roles(objects)[('system', 'test-operator')]['rules'] for r in rule['resources']}
    assert own == {'events', 'leases'}
    workers = roles(objects)[('workers', 'system-test-operator-workers')]
    assert {r for rule in workers['rules'] for r in rule['resources']} == {'deployments', 'pods', 'configmaps'}
    binding = next(o for o in objects if o['kind'] == 'RoleBinding' and o['metadata'].get('namespace') == 'workers')
    assert binding['subjects'][0]['namespace'] == 'system'
    for kind in ('Service', 'NetworkPolicy'):
        worker_objects = [o for o in objects if o['kind'] == kind and o['metadata']['name'].endswith('-worker')]
        assert worker_objects and all(o['metadata']['namespace'] == 'workers' for o in worker_objects)
    policy = next(o for o in objects if o['kind'] == 'NetworkPolicy' and o['metadata']['name'] == 'test-operator-worker')
    peer = policy['spec']['ingress'][0]['from'][0]
    assert peer['namespaceSelector']['matchLabels'] == {'kubernetes.io/metadata.name': 'system'}
    assert 'namespaceSelector' not in next(o for o in render() if o['kind'] == 'NetworkPolicy')['spec']['ingress'][0]['from'][0]


@pytest.mark.parametrize('bad', ['Workers', 'a_b', '-x', 'x' * 64])
def test_worker_namespace_must_be_a_dns_label(bad):
    result = subprocess.run(['helm', 'template', 'test', str(CHART), '-n', 'system', '--set', 'workerNamespace=' + bad],
                            capture_output=True, text=True)
    assert result.returncode != 0 and 'workerNamespace' in result.stderr


def test_agents_follow_the_hardware_namespace():
    # Agents mount hostPath, which both baseline and restricted Pod Security reject.
    # Keeping them with the workers leaves only the operator in the restricted namespace.
    for flags, expected in (([], 'system'), (['--set', 'workerNamespace=workers'], 'workers')):
        objects = render('--set', 'serviceMonitor.enabled=true', *flags)
        agent_objects = [o for o in objects if o['metadata']['name'] == 'test-operator-agent']
        assert {o['kind'] for o in agent_objects} == {'DaemonSet', 'Service', 'ServiceMonitor'}
        assert {o['metadata'].get('namespace', 'system') for o in agent_objects} == {expected}


def test_admission_policy_is_opt_in_and_bound_to_the_operator():
    assert not any(o['kind'].startswith('ValidatingAdmission') for o in render())
    objects = render('--set', 'workerNamespace=workers', '--set', 'workerAdmission.enabled=true')
    policy = next(o for o in objects if o['kind'] == 'ValidatingAdmissionPolicy')
    binding = next(o for o in objects if o['kind'] == 'ValidatingAdmissionPolicyBinding')
    assert policy['spec']['failurePolicy'] == 'Fail'
    assert policy['spec']['matchConditions'][0]['expression'] == 'request.userInfo.username == "system:serviceaccount:system:test-operator"'
    assert binding['spec']['validationActions'] == ['Deny']
    assert binding['spec']['matchResources']['namespaceSelector']['matchLabels'] == {'kubernetes.io/metadata.name': 'workers'}
    expressions = ' '.join(v['expression'] for v in policy['spec']['validations'])
    for required in ('hostNetwork', 'hostPID', 'hostIPC', "'/var/lock/pifanctl'", 'startsWith("ghcr.io/jyje/pifanctl:")', "command[3] == 'run'"):
        assert required in expressions
