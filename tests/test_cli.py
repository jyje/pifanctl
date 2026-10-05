import re

import pytest
from typer.testing import CliRunner

import pifanctl.router as router
from main import app
from pifanctl.enum import Algorithms, Drivers, Sources

runner = CliRunner()


def plain(result) -> str:
    """
    Output as bare text. Under CI, rich adds colour codes and draws error
    messages in a box that can wrap in the middle of an option name, so tests
    compare with the colours, box characters and whitespace removed.
    """
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    return re.sub(r"[│╭╮╰╯─\s]", "", text)


@pytest.fixture
def captured(monkeypatch):
    """Replace the control loop so `start` returns right after parsing."""
    calls = []
    monkeypatch.setattr(router, "start", lambda **kwargs: calls.append(kwargs))
    return calls


def test_status_prints_every_zone(tmp_path):
    zone = tmp_path / "thermal_zone0"
    zone.mkdir()
    (zone / "temp").write_text("49173")
    (zone / "type").write_text("cpu-thermal")
    result = runner.invoke(app, ["status", "--thermal-path", str(tmp_path)])
    assert result.exit_code == 0
    assert "thermal_zone0 (cpu-thermal): 49.173 °C" in result.output
    assert "Current temperature: 49.173 °C" in result.output


def test_status_without_data(tmp_path):
    result = runner.invoke(app, ["status", "--thermal-path", str(tmp_path)])
    assert result.exit_code == 0
    assert "No temperature data available" in result.output


def test_start_defaults_are_accepted(captured):
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0, result.output
    (call,) = captured
    assert call["driver"] == Drivers.AUTO
    assert call["algorithm"] == Algorithms.CURVE
    assert call["source"] == Sources.LOCAL
    assert call["pin"] == 18
    assert call["pwm_refresh_interval"] == 5.0
    assert (call["curve"].temp_low, call["curve"].temp_high) == (50.0, 70.0)
    assert call["failsafe_duty"] == 100.0 and call["exit_duty"] == 100.0


def test_start_reads_the_environment(captured, monkeypatch):
    monkeypatch.setenv("SOURCE", "prometheus")
    monkeypatch.setenv("PROMETHEUS_URL", "http://prom:9090")
    monkeypatch.setenv("ALGORITHM", "step")
    monkeypatch.setenv("TARGET_TEMPERATURE", "55")
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0, result.output
    (call,) = captured
    assert call["source"] == Sources.PROMETHEUS
    assert call["prometheus_url"] == "http://prom:9090"
    assert call["algorithm"] == Algorithms.STEP
    assert call["target_temperature"] == 55.0


def test_invalid_curve_is_a_usage_error(captured):
    result = runner.invoke(app, ["start", "--temp-low", "80", "--temp-high", "60"])
    assert result.exit_code == 2
    assert "temp_low" in plain(result)
    assert captured == []


def test_prometheus_source_needs_a_url():
    result = runner.invoke(app, ["start", "--driver", "mock", "--source", "prometheus"])
    assert result.exit_code == 2
    assert "--prometheus-url" in plain(result)


def test_real_driver_failure_stops_the_process():
    # No RPi.GPIO in CI: asking for it must fail loudly rather than run a mock.
    result = runner.invoke(app, ["start", "--driver", "rpigpio"])
    assert result.exit_code == 2


def test_agent_defaults(monkeypatch):
    calls = []
    monkeypatch.setattr(router, "agent", lambda *args: calls.append(args))
    result = runner.invoke(app, ["agent"])
    assert result.exit_code == 0, result.output
    (args,) = calls
    assert args[2:4] == (5.0, 9101)


def test_version_prints_the_release_and_the_build():
    import pifanctl

    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip().startswith(f"{pifanctl.__version__} (")


def test_start_builds_the_cluster_controller(monkeypatch, tmp_path):
    """The wiring between the flags and the control loop, without running it."""
    captured = {}
    monkeypatch.setattr(router, "run_controller", lambda **kwargs: captured.update(kwargs))
    monkeypatch.setattr(router, "serve", lambda *args, **kwargs: captured.setdefault("served", args[1]))
    result = runner.invoke(app, [
        "start", "--driver", "mock", "--source", "prometheus",
        "--prometheus-url", "http://prom:9090", "--node", "node-a",
        "--metrics-port", "9999", "--failsafe-duty", "80", "--exit-duty", "70",
        "--thermal-path", str(tmp_path),
    ])
    assert result.exit_code == 0, result.output
    assert captured["wants_cluster"] is True
    assert (captured["failsafe_duty"], captured["exit_duty"]) == (80.0, 70.0)
    assert captured["served"] == 9999
    assert captured["controller"].__class__.__name__ == "CurveController"


def test_start_with_the_step_algorithm_and_no_metrics(monkeypatch):
    captured = {}
    monkeypatch.setattr(router, "run_controller", lambda **kwargs: captured.update(kwargs))
    result = runner.invoke(app, ["start", "--driver", "mock", "--algorithm", "step",
                                 "--metrics-port", "0", "--target-temperature", "55"])
    assert result.exit_code == 0, result.output
    assert captured["controller"].__class__.__name__ == "StepController"
    assert captured["controller"].target_temperature == 55.0
    assert captured["metrics"] is None
    assert captured["wants_cluster"] is False


def test_agent_serves_metrics_and_runs_until_stopped(monkeypatch):
    seen = {}
    monkeypatch.setattr(router, "serve", lambda registry, port: seen.update(port=port))
    monkeypatch.setattr(router, "run_agent", lambda metrics, path, interval, stop: seen.update(
        node=metrics.node, interval=interval))
    result = runner.invoke(app, ["agent", "--node", "node-a", "--interval", "2", "--metrics-port", "9100"])
    assert result.exit_code == 0, result.output
    assert seen == {"port": 9100, "node": "node-a", "interval": 2.0}


def test_start_passes_the_temperature_hysteresis(captured, monkeypatch):
    result = runner.invoke(app, ["start"])
    assert result.exit_code == 0, result.output
    assert captured[0]["curve"].temp_hysteresis == 5.0

    captured.clear()
    monkeypatch.setenv("TEMP_HYSTERESIS", "3")
    assert runner.invoke(app, ["start"]).exit_code == 0
    assert captured[0]["curve"].temp_hysteresis == 3.0

    captured.clear()
    assert runner.invoke(app, ["start", "--temp-hysteresis", "0"]).exit_code == 0
    assert captured[0]["curve"].temp_hysteresis == 0.0


def test_a_hysteresis_as_wide_as_the_curve_is_a_usage_error(captured):
    result = runner.invoke(app, ["start", "--temp-low", "50", "--temp-high", "60", "--temp-hysteresis", "10"])
    assert result.exit_code == 2
    assert "temp_hysteresis" in plain(result)
    assert captured == []
