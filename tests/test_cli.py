import re

import pytest
from typer.testing import CliRunner

import pifanctl.router as router
from main import app

runner = CliRunner()


def plain(result) -> str:
    """
    Output as bare text. Under CI, rich adds colour codes and draws error
    messages in a box that can wrap in the middle of an option name, so tests
    compare with the colours, box characters and whitespace removed.
    """
    text = re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    return re.sub(r"[│╭╮╰╯─\s]", "", text)


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


def test_agent_serves_metrics_and_runs_until_stopped(monkeypatch):
    seen = {}
    monkeypatch.setattr(router, "serve", lambda registry, port: seen.update(port=port))
    monkeypatch.setattr(router, "run_agent", lambda metrics, path, interval, stop: seen.update(
        node=metrics.node, interval=interval))
    result = runner.invoke(app, ["agent", "--node", "node-a", "--interval", "2", "--metrics-port", "9100"])
    assert result.exit_code == 0, result.output
    assert seen == {"port": 9100, "node": "node-a", "interval": 2.0}


@pytest.mark.parametrize("args", [["start"], ["start", "--driver", "mock"], ["start", "--driver", "rpigpio"]])
def test_standalone_control_is_not_a_v1_command(args, monkeypatch):
    from pifanctl import drivers
    def forbidden(*args, **kwargs):
        pytest.fail("unsupported standalone command must never open a hardware driver")
    monkeypatch.setattr(drivers, "create_driver", forbidden)
    result = runner.invoke(app, args)
    assert result.exit_code == 2
    assert "Nosuchcommand'start'" in plain(result)


def test_root_help_describes_crd_control():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "FanandCoolingZoneCRs" in plain(result)
    assert "mock-only" in result.output
    assert "Startfancontrol" not in plain(result)
    for command in ["topology", "fan", "zone", "worker", "operator", "agent", "status"]:
        assert command in result.output


def test_image_probe_requires_a_driver_error(monkeypatch, capsys):
    from pifanctl import hardware_smoke
    from pifanctl.drivers import DriverError
    def unavailable(*args):
        raise DriverError("no GPIO device")
    monkeypatch.setattr(hardware_smoke, "create_driver", unavailable)
    hardware_smoke.verify_unavailable_gpio()
    assert "Expected hardware refusal: no GPIO device" in capsys.readouterr().out


def test_image_probe_rejects_unexpected_access_and_unrelated_errors(monkeypatch):
    from pifanctl import hardware_smoke
    closed = []
    class UnexpectedDriver:
        def close(self): closed.append(True)
    monkeypatch.setattr(hardware_smoke, "create_driver", lambda *args: UnexpectedDriver())
    with pytest.raises(RuntimeError, match="unexpectedly provides GPIO"):
        hardware_smoke.verify_unavailable_gpio()
    assert closed == [True]
    def broken_import(*args): raise ImportError("broken image")
    monkeypatch.setattr(hardware_smoke, "create_driver", broken_import)
    with pytest.raises(ImportError, match="broken image"):
        hardware_smoke.verify_unavailable_gpio()


def test_workflows_probe_the_driver_without_standalone_cli():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for path in [".github/workflows/ci.yaml", ".github/workflows/_build-image.yaml"]:
        text = (root / path).read_text()
        assert "python -m pifanctl.hardware_smoke" in text
        assert "python main.py start" not in text


def test_image_probe_module_entrypoint(monkeypatch, capsys):
    import runpy
    from pifanctl import drivers, hardware_smoke
    from pifanctl.drivers import DriverError
    def unavailable(*args): raise DriverError("no mounted GPIO")
    monkeypatch.setattr(drivers, "create_driver", unavailable)
    runpy.run_path(hardware_smoke.__file__, run_name="__main__")
    assert "Expected hardware refusal: no mounted GPIO" in capsys.readouterr().out
