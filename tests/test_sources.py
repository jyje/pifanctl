import json

import pytest

from pifanctl.sources import (
    LocalSource,
    PrometheusSource,
    Reading,
    parse_query_result,
    resolve,
)
from pifanctl.thermal import TemperatureUnavailable


def vector(*values):
    return {"status": "success", "data": {"resultType": "vector", "result": [
        {"metric": {}, "value": [1700000000, str(v)]} for v in values]}}


class FakeSource:
    def __init__(self, value=None, error=None):
        self.value, self.error = value, error

    def read(self):
        if self.error:
            raise TemperatureUnavailable(self.error)
        return self.value


def test_parse_vector_takes_the_maximum():
    assert parse_query_result(vector(48.2, 70.5, 52.1)) == 70.5


def test_parse_scalar():
    payload = {"status": "success", "data": {"resultType": "scalar", "result": [1700000000, "61.5"]}}
    assert parse_query_result(payload) == 61.5


@pytest.mark.parametrize("payload", [
    {"status": "error", "error": "bad query"},
    {"status": "success", "data": {"resultType": "vector", "result": []}},
    {"status": "success", "data": {"resultType": "vector", "result": [{"value": [0, "NaN"]}]}},
    {"status": "success", "data": {"resultType": "matrix", "result": []}},
])
def test_parse_rejects_unusable_results(payload):
    with pytest.raises(TemperatureUnavailable):
        parse_query_result(payload)


def test_cluster_value_wins_when_hotter():
    reading = resolve(FakeSource(50), FakeSource(72))
    assert (reading.value, reading.source) == (72, "prometheus")


def test_local_value_is_never_ignored():
    reading = resolve(FakeSource(80), FakeSource(60))
    assert (reading.value, reading.source) == (80, "prometheus")


def test_falls_back_to_local_when_prometheus_is_down():
    reading = resolve(FakeSource(55), FakeSource(error="connection refused"))
    assert (reading.value, reading.source) == (55, "local")
    assert "connection refused" in reading.reason


def test_cluster_value_is_used_when_local_is_unreadable():
    reading = resolve(FakeSource(error="no zone"), FakeSource(66))
    assert (reading.value, reading.source) == (66, "prometheus")


def test_failsafe_when_nothing_is_readable():
    reading = resolve(FakeSource(error="no zone"), FakeSource(error="timeout"))
    assert reading.value is None and reading.source == "failsafe"
    assert "timeout" in reading.reason and "no zone" in reading.reason


def test_local_only_mode():
    assert resolve(FakeSource(44)).source == "local"
    assert resolve(FakeSource(error="no zone")).source == "failsafe"


def test_prometheus_source_requires_a_url():
    with pytest.raises(ValueError):
        PrometheusSource("")


def test_prometheus_source_queries_the_http_api(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return json.dumps(vector(41, 59)).encode()

    def fake_urlopen(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return Response()

    monkeypatch.setattr("pifanctl.sources.urllib.request.urlopen", fake_urlopen)
    value = PrometheusSource("http://prom:9090/", "max(x)", timeout=2).read()
    assert value == 59
    assert seen["url"] == "http://prom:9090/api/v1/query?query=max%28x%29"
    assert seen["timeout"] == 2


def test_prometheus_source_wraps_network_errors(monkeypatch):
    def boom(url, timeout):
        raise OSError("unreachable")

    monkeypatch.setattr("pifanctl.sources.urllib.request.urlopen", boom)
    with pytest.raises(TemperatureUnavailable):
        PrometheusSource("http://prom:9090").read()


def test_local_source_reads_the_hottest_zone(tmp_path):
    for i, milli in enumerate((40000, 63000)):
        zone = tmp_path / f"thermal_zone{i}"
        zone.mkdir()
        (zone / "temp").write_text(str(milli))
    assert LocalSource(str(tmp_path)).read() == 63
