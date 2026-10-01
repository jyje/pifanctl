import pytest
from typer.testing import CliRunner

import pifanctl.router as router
from main import app
from pifanctl.enum import Algorithms, Drivers, Sources

runner = CliRunner()


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
    assert "temp_low" in result.output
    assert captured == []


def test_prometheus_source_needs_a_url():
    result = runner.invoke(app, ["start", "--driver", "mock", "--source", "prometheus"])
    assert result.exit_code == 2
    assert "--prometheus-url" in result.output


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
