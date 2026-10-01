import threading

import pytest

from pifanctl.control import CurveConfig, CurveController
from pifanctl.drivers import MockDriver
from pifanctl.metrics import AgentMetrics, ControllerMetrics
from pifanctl.service import format_nodes, run_agent, run_controller
from pifanctl.sources import Reading
from pifanctl.thermal import Zone


class Script:
    """Feeds readings, then asks the loop to stop."""
    def __init__(self, stop, readings):
        self.stop, self.readings = stop, list(readings)

    def __call__(self):
        reading = self.readings.pop(0)
        if not self.readings:
            self.stop.set()
        return reading


@pytest.fixture
def curve():
    return CurveController(CurveConfig())


def run(curve, readings, **kwargs):
    stop = threading.Event()
    driver = MockDriver()
    applied = []
    original = driver.set_duty
    driver.set_duty = lambda d: (applied.append(d), original(d))[1]
    metrics = ControllerMetrics("node-a")
    run_controller(
        driver=driver, controller=curve, read=Script(stop, readings), metrics=metrics,
        interval=0, failsafe_duty=100, exit_duty=100, stop=stop, **kwargs,
    )
    return applied, metrics


def sample(metrics, name, **labels):
    return metrics.registry.get_sample_value(name, {"node": "node-a", **labels})


def test_exit_leaves_the_fan_at_full_speed(curve):
    applied, _ = run(curve, [Reading(value=40, source="local")])
    assert applied == [0, 100]


def test_failsafe_when_no_temperature(curve):
    applied, metrics = run(curve, [Reading(value=None, source="failsafe", reason="no sensor")])
    assert applied[0] == 100
    assert sample(metrics, "pifanctl_control_fallbacks_total", to="failsafe") == 1
    assert sample(metrics, "pifanctl_control_source", source="failsafe") == 1


def test_fallback_to_local_is_counted_in_cluster_mode(curve):
    _, metrics = run(curve, [Reading(value=55, source="local", reason="prometheus: down")], wants_cluster=True)
    assert sample(metrics, "pifanctl_control_fallbacks_total", to="local") == 1


def test_local_mode_is_not_a_fallback(curve):
    _, metrics = run(curve, [Reading(value=55, source="local")], wants_cluster=False)
    assert sample(metrics, "pifanctl_control_fallbacks_total", to="local") is None


def test_controller_metrics_report_the_decision(curve):
    _, metrics = run(curve, [Reading(value=70, source="prometheus")], wants_cluster=True)
    assert sample(metrics, "pifanctl_fan_duty_percent") == 100
    assert sample(metrics, "pifanctl_control_temperature_celsius") == 70
    assert sample(metrics, "pifanctl_control_source", source="prometheus") == 1
    assert sample(metrics, "pifanctl_control_source", source="local") == 0


def test_driver_is_closed_even_when_the_loop_crashes(curve):
    stop = threading.Event()
    driver = MockDriver()
    closed = []
    driver.close = lambda: closed.append(True)

    def boom():
        raise RuntimeError("sensor bus on fire")

    with pytest.raises(RuntimeError):
        run_controller(driver=driver, controller=curve, read=boom, metrics=None,
                       interval=0, failsafe_duty=100, exit_duty=100, stop=stop)
    assert driver.duty == 100 and closed == [True]


def test_agent_publishes_one_series_per_zone(tmp_path):
    for i, milli in enumerate((48000, 52500)):
        zone = tmp_path / f"thermal_zone{i}"
        zone.mkdir()
        (zone / "temp").write_text(str(milli))
        (zone / "type").write_text(f"zone-{i}")
    stop = threading.Event()
    metrics = AgentMetrics("node-a")
    real_wait = stop.wait
    stop.wait = lambda interval: stop.set()
    run_agent(metrics, str(tmp_path), 0, stop)
    get = lambda n, **l: metrics.registry.get_sample_value(n, {"node": "node-a", **l})
    assert get("pifanctl_temperature_celsius", zone="thermal_zone1", type="zone-1") == 52.5
    assert get("pifanctl_node_temperature_max_celsius") == 52.5


def test_agent_drops_stale_values_and_counts_errors():
    metrics = AgentMetrics("node-a")
    metrics.observe([Zone("thermal_zone0", "cpu", 50.0)])
    metrics.observe([])
    get = lambda n, **l: metrics.registry.get_sample_value(n, {"node": "node-a", **l})
    assert get("pifanctl_node_temperature_max_celsius") is None
    assert get("pifanctl_temperature_celsius", zone="thermal_zone0", type="cpu") is None
    assert get("pifanctl_temperature_read_errors_total") == 1


NODES = {"raspi-40": 49.2, "raspi-41": 52.1, "raspi-50": 51.8, "raspi-51": 70.5}


def test_log_names_the_followed_node_and_every_node(caplog):
    caplog.set_level("INFO")
    reading = Reading(value=70.5, source="prometheus", nodes=NODES, driver="raspi-51")
    run(CurveController(CurveConfig()), [reading], wants_cluster=True)
    line = next(r.getMessage() for r in caplog.records if "Following" in r.getMessage())
    assert "Temperature: 70.5°C" in line
    assert "Following: raspi-51" in line
    assert "Nodes: raspi-51=70.5* raspi-41=52.1 raspi-50=51.8 raspi-40=49.2" in line


def test_format_nodes_lists_hottest_first_and_marks_the_followed_one():
    reading = Reading(value=52.1, source="prometheus", nodes={"a": 50.0, "b": 52.1, "c": 52.1}, driver="b")
    assert format_nodes(reading) == "b=52.1* c=52.1 a=50.0"


def test_a_node_that_stops_reporting_is_warned_about_once(caplog):
    caplog.set_level("WARNING")
    full = Reading(value=70.5, source="prometheus", nodes=NODES, driver="raspi-51")
    gone = Reading(value=52.1, source="prometheus", nodes={k: v for k, v in NODES.items() if k != "raspi-51"},
                   driver="raspi-41")
    run(CurveController(CurveConfig()), [full, gone, gone, gone], wants_cluster=True)
    warnings = [r.getMessage() for r in caplog.records if "stopped reporting" in r.getMessage()]
    assert warnings == ["Node 'raspi-51' stopped reporting and is not part of the maximum"]


def test_only_the_followed_node_is_exported(curve):
    _, metrics = run(curve, [Reading(value=70.5, source="prometheus", nodes=NODES, driver="raspi-51")],
                     wants_cluster=True)
    assert sample(metrics, "pifanctl_control_followed_node", followed="raspi-51") == 1
    assert sample(metrics, "pifanctl_control_followed_node", followed="raspi-40") is None


def test_signals_ask_the_loop_to_stop():
    import os
    import signal

    from pifanctl.service import install_stop_handlers

    stop = threading.Event()
    previous = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    try:
        install_stop_handlers(stop)
        os.kill(os.getpid(), signal.SIGTERM)
        assert stop.wait(1)
        stop.clear()
        os.kill(os.getpid(), signal.SIGINT)
        assert stop.wait(1)
    finally:
        for number, handler in previous.items():
            signal.signal(number, handler)


def test_node_name_prefers_the_flag_then_the_environment(monkeypatch):
    from pifanctl.metrics import resolve_node_name

    monkeypatch.setenv("NODE_NAME", "from-env")
    assert resolve_node_name("from-flag") == "from-flag"
    assert resolve_node_name() == "from-env"
    monkeypatch.delenv("NODE_NAME")
    assert resolve_node_name()  # falls back to the hostname
