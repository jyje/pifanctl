import json
from urllib.error import URLError

import pytest

from pifanctl.metrics import AgentMetrics
from pifanctl.thermal import TemperatureUnavailable, Zone
from pifanctl.topology import telemetry as t
from pifanctl.topology.planner import plan
from test_topology import fan, zone


def payload(value='62', node='pi-a'):
    return {'status': 'success', 'data': {'resultType': 'vector', 'result': [
        {'metric': {'node': node, 'zone': 'thermal_zone0', 'type': 'cpu'}, 'value': [100, value]}]}}


def test_freshness_metric(monkeypatch):
    monkeypatch.setattr('pifanctl.metrics.time.time', lambda: 123)
    metrics = AgentMetrics('pi-a'); metrics.observe([Zone('thermal_zone0', 'cpu', 62)])
    assert metrics.registry.get_sample_value('pifanctl_temperature_observed_timestamp_seconds',
        {'node': 'pi-a', 'zone': 'thermal_zone0', 'type': 'cpu'}) == 123
    metrics.observe([])
    assert not metrics.observed.collect()[0].samples


@pytest.mark.parametrize('bad', [None, {}, {'status': 'error', 'data': {}},
    {'status': 'success', 'data': {'resultType': 'matrix'}}])
def test_bad_vector(bad):
    with pytest.raises(TemperatureUnavailable): t.vector(bad)


@pytest.mark.parametrize('bad', ['NaN', 'Inf', 'bad', None])
def test_bad_sample(bad):
    assert t.vector(payload(bad)) == {}


def test_malformed_sample():
    p = payload(); p['data']['result'] = [None, {}, {'metric': {}, 'value': []}]
    assert t.vector(p) == {}


@pytest.mark.parametrize('age,missing,ok', [(10, False, True), (40, False, False),
    (-10, False, False), (10, True, False)])
def test_complete_readings(monkeypatch, age, missing, ok):
    values = t.vector(payload())
    stamps = {} if missing else {k: 100 - age for k in values}
    queries = []
    def query(url, expr):
        queries.append(expr)
        return stamps if 'timestamp' in expr else values
    monkeypatch.setattr(t, 'query', query)
    spec = {'source': 'prometheus', 'prometheusURL': 'http://p', 'maxSampleAgeSeconds': 30}
    if ok: assert t.read_members(spec, ['pi-a'], 55, now=100) == {'pi-a': 62}
    else:
        with pytest.raises(TemperatureUnavailable): t.read_members(spec, ['pi-a'], 55, now=100)
    assert len(queries) == 2
    with pytest.raises(TemperatureUnavailable): t.read_members(spec, ['pi-a', 'pi-b'], 55, now=100)
    with pytest.raises(TemperatureUnavailable): t.read_members(spec, [], 55)


def test_local_floor_and_issues(monkeypatch):
    f = plan([fan(), zone(telemetry={'source': 'local'})])['fans']['fan-a']
    assert t.fan_reading(f, 80)[0] == 80
    f['issues'] = ['MissingNode']
    with pytest.raises(TemperatureUnavailable): t.fan_reading(f, 80)
    f['issues'] = []; f['zones'][0]['issues'] = ['EmptySelection']
    with pytest.raises(TemperatureUnavailable): t.fan_reading(f, 80)


def test_http_query(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, limit): return json.dumps(payload()).encode()
    calls = []
    monkeypatch.setattr(t.urllib.request, 'urlopen', lambda url, **kw: calls.append((url, kw)) or Response())
    assert t.query('http://p', 'expression')
    assert '/api/v1/query?query=expression' in calls[0][0]
    def fail(*args, **kwargs): raise URLError('offline')
    monkeypatch.setattr(t.urllib.request, 'urlopen', fail)
    with pytest.raises(TemperatureUnavailable): t.query('http://p', 'expression')


def test_latency_counts_toward_sample_age(monkeypatch):
    clock = [100]
    values = t.vector(payload())
    def query(url, expression):
        clock[0] += 20
        return {k: 100 for k in values} if 'timestamp' in expression else values
    monkeypatch.setattr(t, 'query', query)
    monkeypatch.setattr(t.time, 'time', lambda: clock[0])
    with pytest.raises(TemperatureUnavailable, match='Stale'):
        t.read_members({'source': 'prometheus', 'prometheusURL': 'http://p', 'maxSampleAgeSeconds': 30}, ['pi-a'], 55)


def test_member_observations_distinguish_fresh_stale_and_missing(monkeypatch):
    series = {(('node', 'pi-a'),): 62.0, (('node', 'pi-b'),): 70.0, (('node', 'pi-c'),): 50.0}
    stamps = {(('node', 'pi-a'),): 95, (('node', 'pi-b'),): 10}
    queries = []
    def query(url, expr):
        queries.append(expr)
        return stamps if 'timestamp' in expr else series
    monkeypatch.setattr(t, 'query', query)
    spec = {'source': 'prometheus', 'prometheusURL': 'http://p', 'maxSampleAgeSeconds': 30}
    seen = t.observe_members(spec, ['pi-a', 'pi-b', 'pi-c', 'pi-d'], 55, now=100)
    assert len(queries) == 2
    assert seen['pi-a'] == {'nodeName': 'pi-a', 'ready': True, 'reason': 'Fresh', 'temperatureCelsius': 62.0, 'observedTime': 95}
    assert seen['pi-b']['reason'] == 'Stale' and not seen['pi-b']['ready'] and seen['pi-b']['observedTime'] == 10
    assert seen['pi-c'] == {'nodeName': 'pi-c', 'ready': False, 'reason': 'Missing'}
    assert seen['pi-d']['reason'] == 'Missing'
    with pytest.raises(TemperatureUnavailable, match='pi-b,pi-c,pi-d'):
        t.read_members(spec, ['pi-a', 'pi-b', 'pi-c', 'pi-d'], 55, now=100)


def test_fan_reading_reports_members_before_failing(monkeypatch):
    f = plan([fan(), zone(telemetry={'source': 'local'})])['fans']['fan-a']
    seen = {}
    assert t.fan_reading(f, 80, now=5, observations=seen)[0] == 80
    assert seen[f['zones'][0]['name']][0]['observedTime'] == 5
    f['zones'][0]['telemetry'] = {'source': 'prometheus', 'prometheusURL': 'http://p', 'maxSampleAgeSeconds': 30}
    monkeypatch.setattr(t, 'query', lambda url, expr: {})
    seen = {}
    with pytest.raises(TemperatureUnavailable): t.fan_reading(f, 80, now=5, observations=seen)
    assert {o['reason'] for o in seen[f['zones'][0]['name']]} == {'Missing'}
