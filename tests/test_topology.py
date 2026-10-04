import copy
from pathlib import Path

import pytest
import yaml

from pifanctl.topology.model import API, TopologyError, bundle, digest, matches, normalize, parse
from pifanctl.topology.planner import plan, worker_plan


def fan(name='fan-a', node='pi-a', **spec):
    return {'apiVersion': API, 'kind': 'Fan', 'metadata': {'name': name},
            'spec': {'nodeName': node, 'hardware': {'rpigpio': {'pin': 18}}, **spec}}


def zone(name='rack', refs=None, nodes=None, **spec):
    return {'apiVersion': API, 'kind': 'CoolingZone', 'metadata': {'name': name},
            'spec': {'nodeNames': nodes or ['pi-a'], 'fanRefs': refs or ['fan-a'],
                     'telemetry': {'source': 'prometheus', 'prometheusURL': 'http://prometheus:9090'}, **spec}}


def node(name='pi-a', labels=None, ready='True', uid='uid-a'):
    return {'metadata': {'name': name, 'labels': labels or {}, 'uid': uid},
            'status': {'conditions': [{'type': 'Ready', 'status': ready}]}}


def test_defaults_roundtrip_and_purity():
    raw = [fan(), zone()]; original = copy.deepcopy(raw)
    items = normalize(raw)
    assert raw == original
    assert items[1]['spec']['control']['curve']['dutyDownStep'] == 5
    assert parse(yaml.safe_dump(bundle(items))) == items
    assert plan(items) == plan(list(reversed(items)))
    assert digest({'b': 1, 'a': 2}) == digest({'a': 2, 'b': 1})
    assert worker_plan(plan(items), 'pi-a')['nodeUID'] == ''
    assert plan([])['fans'] == {}


@pytest.mark.parametrize('text', ['', 'null', '[]', '12', 'a: 1\na: 2', 'a: &a [*a]',
    'kind: List\napiVersion: v1\nitems: {}', 'kind: ConfigMap', 'x' * 900001, 'foo: ['])
def test_bad_yaml(text):
    with pytest.raises(TopologyError): parse(text)


@pytest.mark.parametrize('change', [
    lambda f: f.update(apiVersion='bad'), lambda f: f.update(kind='Member'),
    lambda f: f['metadata'].update(name='Bad'), lambda f: f['metadata'].update(namespace='x'),
    lambda f: f['spec'].update(unknown=1), lambda f: f['spec'].update(nodeName='bad..name'),
    lambda f: f['spec'].update(hardware={}), lambda f: f['spec']['hardware'].update(sysfs={'chip': 0, 'channel': 2}),
    lambda f: f['spec'].update(control={'curve': {'temperatureLow': 80}}),
    lambda f: f['spec'].update(control={'curve': {'dutyDownStep': 0}}),
    lambda f: f['spec'].update(control={'curve': {'dutyIdle': 40}}),
    lambda f: f['spec'].update(control={'curve': {'temperatureLow': float('nan')}}),
])
def test_bad_fans(change):
    f = fan(); change(f)
    with pytest.raises(TopologyError): normalize([f])


@pytest.mark.parametrize('spec', [
    {'nodeSelector': {'matchLabels': {'rack': 'a'}}}, {'fanRefs': ['fan-a', 'fan-a']},
    {'nodeNames': ['pi-a', 'pi-a']}, {'fanRefs': ['Bad']}, {'nodeNames': ['Bad']},
    {'telemetry': {'source': 'local', 'prometheusURL': 'http://x'}},
    {'telemetry': {'source': 'local'}, 'nodeNames': ['pi-a', 'pi-b']},
    {'telemetry': {'source': 'prometheus', 'prometheusURL': 'http://user:pass@x'}},
    {'telemetry': {'source': 'prometheus', 'prometheusURL': 'ftp://x'}},
])
def test_bad_zones(spec):
    with pytest.raises(TopologyError): normalize([zone(**spec)])


@pytest.mark.parametrize('selector', [ {}, {'matchLabels': {'a/b/c': 'x'}},
    {'matchLabels': {'rack': '$'}}, {'matchExpressions': [{'key': 'a', 'operator': 'In'}]},
    {'matchExpressions': [{'key': 'a', 'operator': 'Exists', 'values': ['x']}]},
    {'matchExpressions': [{'key': 'a', 'operator': 'In', 'values': ['x', 'x']}]},
])
def test_invalid_selector(selector):
    z = zone(); del z['spec']['nodeNames']; z['spec']['nodeSelector'] = selector
    with pytest.raises(TopologyError): normalize([z])


def test_selector_and_node_lifecycle():
    z = zone(); del z['spec']['nodeNames']; z['spec']['nodeSelector'] = {'matchLabels': {'rack': 'a'}}
    with pytest.raises(TopologyError): plan([fan(), z])
    p = plan([fan(), z], [node(labels={'rack': 'a'}, ready='False')])
    assert p['zones']['rack']['members'] == ['pi-a']
    assert p['zones']['rack']['issues'] == ['NodeNotReady']
    assert worker_plan(p, 'pi-a')['nodeUID'] == 'uid-a'
    missing = plan([fan(), z], [])
    assert 'MissingWorkerNode' in missing['fans']['fan-a']['issues']
    assert missing['zones']['rack']['issues'] == ['EmptySelection']
    for op, values, labels, expected in [('In', ['x'], {'a': 'x'}, True), ('In', ['x'], {}, False),
        ('NotIn', ['x'], {}, True), ('NotIn', ['x'], {'a': 'x'}, False),
        ('Exists', [], {}, False), ('DoesNotExist', [], {}, True), ('DoesNotExist', [], {'a': ''}, False)]:
        assert matches({'matchExpressions': [{'key': 'a', 'operator': op, 'values': values}]}, labels) == expected


def test_relationships_and_conflicts():
    p = plan([fan(), fan('fan-b'), zone(refs=['fan-a', 'absent'], nodes=['pi-b'])], [node()])
    assert 'HardwareConflict' in p['fans']['fan-a']['issues']
    assert 'NoCoolingZone' in p['fans']['fan-b']['issues']
    assert p['zones']['rack']['issues'] == ['MissingFan', 'MissingNode']
    p = plan([fan(), fan('sys', hardware={'sysfs': {'chip': 0, 'channel': 2}})])
    assert all('MixedHardwareDrivers' in f['issues'] for f in p['fans'].values())
    p = plan([fan(), zone(telemetry={'source': 'local'}, nodes=['pi-b'])])
    assert 'InvalidLocalPlacement' in p['zones']['rack']['issues']
    p = plan([fan(), zone(), zone('other', telemetry={'source': 'local'})])
    assert 'TelemetryConflict' in p['fans']['fan-a']['issues']
    f = fan(); f['metadata']['deletionTimestamp'] = 'now'
    z = zone(); z['metadata']['deletionTimestamp'] = 'now'
    p = plan([f, z]); assert 'DeletingFan' in p['fans']['fan-a']['issues']
    assert p['zones']['rack']['issues'] == ['DeletingZone']


def test_duplicates_limits_and_recursive_input():
    for items in [[fan(), fan()], [None], [fan()] * 2049, {}]:
        with pytest.raises(TopologyError): normalize(items)
    recursive = []; recursive.append(recursive)
    with pytest.raises(TopologyError): normalize(recursive)


def test_examples():
    for path in Path('design/v1/examples').glob('*.yaml'):
        if path.stem == 'helm-values': continue
        text = path.read_text()
        doc = yaml.safe_load(text)
        if doc.get('kind') == 'ConfigMap': text = doc['data']['topology.yaml']
        items = parse(text)
        assert items
        if all('nodeSelector' not in o['spec'] for o in items): assert plan(items)['hash']


def test_deleted_selector_member_and_replaced_node_stay_unsafe():
    z = zone(); del z['spec']['nodeNames']; z['spec']['nodeSelector'] = {'matchLabels': {'rack': 'a'}}
    nodes = [node(labels={'rack': 'a'}), node('pi-b', {'rack': 'a'}, uid='uid-b')]
    initial = plan([fan(), z], nodes)
    missing = plan([fan(), z], nodes[:1], initial['zones'])
    assert missing['zones']['rack']['members'] == ['pi-a', 'pi-b']
    assert 'MissingNode' in missing['zones']['rack']['issues']
    nodes[1]['metadata']['uid'] = 'new-b'
    changed = plan([fan(), z], nodes, missing['zones'])
    assert 'NodeReplaced' in changed['zones']['rack']['issues']
    assert changed['zones']['rack']['memberUIDs']['pi-b'] == 'uid-b'
    z['metadata']['uid'] = 'reviewed-zone-replacement'
    assert not plan([fan(), z], nodes, changed['zones'])['zones']['rack']['issues']
