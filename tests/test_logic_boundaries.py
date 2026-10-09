"""Public input contracts and real software behavior without test doubles."""
import runpy
import sys
from pathlib import Path

import pytest

from pifanctl.control import StepController
from pifanctl.enum import Drivers
from pifanctl.sources import LocalSource, make_resolver, parse_query_result
from pifanctl.topology.model import TopologyError, label_key, normalize
from test_topology import zone


def test_enum_public_representation():
    assert str(Drivers.RPIGPIO) == 'rpigpio'
    assert Drivers.list() == ['auto', 'rpigpio', 'sysfs', 'mock']


def test_step_controller_rejects_nonpositive_step_and_clamps_override():
    with pytest.raises(ValueError, match='positive'):
        StepController(50, 0)
    control = StepController(50, 5)
    assert control.force(101) == 100
    assert control.force(-1) == 0


def test_prometheus_discards_malformed_samples_without_losing_valid_peer():
    response = {'status': 'success', 'data': {'resultType': 'vector', 'result': [
        {'metric': {'node': 'pi-a'}, 'value': [100, 'not-a-number']},
        {'metric': {'node': 'pi-b'}, 'value': [100, '55']}]}}
    assert parse_query_result(response) == {'pi-b': 55}


def test_resolver_reads_real_thermal_file(tmp_path):
    sensor = tmp_path / 'thermal_zone0'
    sensor.mkdir()
    (sensor / 'temp').write_text('55000')
    reading = make_resolver(LocalSource(str(tmp_path)), None, 'pi-a')()
    assert (reading.value, reading.driver, reading.source) == (55, 'pi-a', 'local')


def test_label_key_rejects_non_string():
    assert label_key(42) is False


def test_selector_accepts_multiple_valid_requirements():
    z = zone(nodeSelector={'matchExpressions': [
        {'key': 'rack', 'operator': 'In', 'values': ['a']},
        {'key': 'maintenance', 'operator': 'DoesNotExist'}]})
    del z['spec']['nodeNames']
    assert normalize([z])[0]['spec']['nodeSelector'] == z['spec']['nodeSelector']


def test_prometheus_endpoint_rejects_zero_port():
    with pytest.raises(TopologyError, match='invalid prometheusURL'):
        normalize([zone(telemetry={'source': 'prometheus', 'prometheusURL': 'http://prometheus:0'})])


def test_script_entrypoint_exposes_real_cli_help(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['main.py', '--help'])
    with pytest.raises(SystemExit) as caught:
        runpy.run_path(str(Path(__file__).resolve().parents[1] / 'sources/main.py'), run_name='__main__')
    assert caught.value.code == 0
    assert 'topology' in capsys.readouterr().out


def test_fan_node_name_rejects_overlong_dns_segment():
    from test_topology import fan
    with pytest.raises(TopologyError, match='invalid fan nodeName'):
        normalize([fan(node='n' * 64)])


def test_host_lock_exit_is_idempotent(tmp_path):
    from pifanctl.topology.locks import HostLock
    lock = HostLock(tmp_path)
    with lock:
        assert lock.file is not None
    lock.__exit__()
    assert lock.file is None


def test_controller_without_optional_metrics_and_agent_without_sensors(tmp_path, caplog):
    import threading
    from pifanctl.control import CurveConfig, CurveController
    from pifanctl.drivers import MockDriver
    from pifanctl.metrics import AgentMetrics
    from pifanctl.service import run_agent, run_controller
    from pifanctl.sources import Reading
    stop = threading.Event()
    driver = MockDriver()
    def read():
        stop.set()
        return Reading(value=55, source='local', reason='cluster unavailable')
    run_controller(driver, CurveController(CurveConfig()), read, None, 0, 100, 100, stop, wants_cluster=True)
    assert driver.duty == 100
    stop.clear()
    stop.wait = lambda interval: stop.set()
    metrics = AgentMetrics('pi-a')
    run_agent(metrics, str(tmp_path), 0, stop)
    assert metrics.registry.get_sample_value('pifanctl_temperature_read_errors_total', {'node': 'pi-a'}) == 1
    assert 'No readable thermal zone' in caplog.text


def test_controller_metrics_are_served_by_real_http_endpoint():
    from urllib.request import urlopen
    from pifanctl import metrics
    value = metrics.ControllerMetrics('pi-a')
    value.set_info('sysfs', 'curve')
    value.observe(45, 55, 'local')
    # serve has no return value; capture the actual server to close it after
    # asserting a real network scrape, rather than leaving a daemon behind.
    real_start = metrics.start_http_server
    servers = []
    def start(*args, **kwargs):
        server, thread = real_start(*args, **kwargs)
        servers.append((server, thread))
        return server, thread
    from unittest.mock import patch
    with patch.object(metrics, 'start_http_server', start):
        metrics.serve(value.registry, 0, '127.0.0.1')
    server, thread = servers[0]
    try:
        with urlopen(f'http://127.0.0.1:{server.server_port}/metrics', timeout=2) as response:
            text = response.read().decode()
        assert 'pifanctl_fan_duty_percent{node="pi-a"} 45.0' in text
        assert 'driver="sysfs"' in text
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_prometheus_endpoint_rejects_nonnumeric_port():
    with pytest.raises(TopologyError, match='invalid prometheusURL'):
        normalize([zone(telemetry={'source': 'prometheus', 'prometheusURL': 'http://prometheus:invalid'})])


def test_failsafe_without_optional_metrics():
    import threading
    from pifanctl.control import CurveConfig, CurveController
    from pifanctl.drivers import MockDriver
    from pifanctl.service import run_controller
    from pifanctl.sources import Reading
    stop = threading.Event()
    driver = MockDriver()
    def read():
        stop.set()
        return Reading(value=None, source='failsafe')
    run_controller(driver, CurveController(CurveConfig()), read, None, 0, 100, 100, stop)
    assert driver.duty == 100


def test_worker_plan_rejects_inconsistent_actuator_uids():
    from pifanctl.topology.planner import worker_plan
    value = {'fans': {'fan-a': {'nodeName': 'pi-a', 'nodeUID': 'original'},
                      'fan-b': {'nodeName': 'pi-a', 'nodeUID': 'replacement'}}}
    with pytest.raises(TopologyError, match='inconsistent identity'):
        worker_plan(value, 'pi-a')
