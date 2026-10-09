"""Worker safety contracts exercised through files and validated plans."""
import json
import threading
from unittest.mock import Mock

import pytest

from pifanctl.topology import worker as w
from pifanctl.topology.model import TopologyError, digest
from pifanctl.topology.planner import plan, worker_plan
from test_topology import fan, zone
from test_topology_worker import desired


def signed(value):
    value['hash'] = digest({k: v for k, v in value.items() if k != 'hash'})
    return value


@pytest.mark.parametrize('issues', [None, []])
def test_unresolved_zone_requires_explicit_health_reason(issues):
    value = desired()
    z = value['fans']['fan-a']['zones'][0]
    z.update(members=[], issues=issues)
    with pytest.raises(TopologyError, match='zone health'):
        w.validate_plan(signed(value), 'pi-a')


def test_mixed_driver_conflict_cannot_be_hidden():
    value = worker_plan(plan([fan(), fan('fan-b', hardware={'sysfs': {'chip': 0, 'channel': 2}})]), 'pi-a')
    value['fans']['fan-a']['issues'].remove('MixedHardwareDrivers')
    with pytest.raises(TopologyError, match='unreported hardware conflict'):
        w.validate_plan(signed(value), 'pi-a')


def test_missing_thermal_sensor_demands_failsafe(tmp_path):
    worker = w.Worker('pi-a', thermal_path=str(tmp_path), mock=True)
    worker.apply(desired())
    try:
        state = worker.cycle(now=100)['fans']['fan-a']
        assert state['reason'] == 'LocalSensorUnavailable'
        assert state['dutyPercent'] == 100 and not state['ready']
    finally:
        worker.close()


def test_shutdown_attempts_every_driver_after_write_and_close_failures():
    # GPIO faults cannot be produced on a hardware-free runner. Substitute
    # only the driver boundary, leaving shutdown ordering/error handling real.
    driver = Mock()
    worker = w.Worker('pi-a', driver_factory=lambda *a: driver)
    worker.apply(desired())
    write_error = OSError('GPIO write failed')
    driver.set_duty.side_effect = write_error
    driver.close.side_effect = OSError('GPIO close failed')
    worker.trip('ControlLoopStalled')
    assert worker.snapshot()['reason'] == 'ControlLoopStalled'
    with pytest.raises(OSError) as caught:
        worker.close()
    assert caught.value is write_error
    driver.close.assert_called_once()
    assert not worker.drivers


@pytest.mark.parametrize('mode', ['unchanged', 'oversized', 'expired-heartbeat'])
def test_run_reads_files_and_reports_safety_state(tmp_path, monkeypatch, mode):
    thermal = tmp_path / 'thermal_zone0'
    thermal.mkdir()
    (thermal / 'temp').write_text('55000')
    value = desired()
    path = tmp_path / 'plan.json'
    path.write_text(json.dumps(value) if mode != 'oversized' else ' ' * 900001)
    heartbeat = tmp_path / 'heartbeat.json'
    heartbeat.write_text(json.dumps({'time': 0, 'healthy': True, 'planHash': value['hash'], 'nodeUID': ''}))
    stop = threading.Event()
    states = []
    original = w.Worker.cycle
    def cycle(worker, *args):
        state = original(worker, *args)
        states.append(state)
        if len(states) == 2:
            stop.set()
        return state
    # Observe real cycles; stop after two iterations rather than waiting for
    # the configured refresh interval. Actual file loading/control stays real.
    monkeypatch.setattr(w.Worker, 'cycle', cycle)
    monkeypatch.setattr(stop, 'wait', lambda interval: None)
    w.run(path, 'pi-a', thermal_path=str(tmp_path), lock_dir=tmp_path / 'locks',
          heartbeat_path=heartbeat if mode == 'expired-heartbeat' else None,
          port=0, mock=True, stop=stop)
    assert len(states) == 2
    if mode == 'unchanged':
        assert all(state['ready'] for state in states)
        assert states[0]['appliedTopologyHash'] == states[1]['appliedTopologyHash'] == value['hash']
    else:
        expected = 'PlanInvalid' if mode == 'oversized' else 'OperatorHeartbeatExpired'
        assert all(not state['ready'] and state['reason'].startswith(expected) for state in states)


def test_plan_rejects_nonobject_zone():
    value = desired()
    value['fans']['fan-a']['zones'] = ['rack']
    with pytest.raises(TopologyError, match='zone must be an object'):
        w.validate_plan(signed(value), 'pi-a')


def test_empty_plan_is_valid_and_healthy_watchdog_does_not_trip():
    empty = worker_plan(plan([]), 'pi-a')
    assert w.validate_plan(empty, 'pi-a') == empty
    worker = w.Worker('pi-a', mock=True)
    worker.apply(empty)
    w.check_watchdog(worker, monotonic_now=worker.progress + 1)
    assert not worker.safety_error
    worker.close()


def test_run_missing_file_is_reported(tmp_path, monkeypatch):
    stop = threading.Event()
    states = []
    original = w.Worker.cycle
    def cycle(worker, *args):
        states.append(original(worker, *args))
        stop.set()
        return states[-1]
    monkeypatch.setattr(w.Worker, 'cycle', cycle)
    w.run(tmp_path / 'missing', 'pi-a', mock=True, port=0,
          lock_dir=tmp_path / 'locks', stop=stop)
    assert states[0]['reason'].startswith('PlanInvalid')
    assert not states[0]['ready']


def test_plan_fan_cannot_target_a_different_actuator():
    value = desired()
    value['fans']['fan-a']['nodeName'] = 'pi-b'
    with pytest.raises(TopologyError, match='does not belong'):
        w.validate_plan(signed(value), 'pi-a')
