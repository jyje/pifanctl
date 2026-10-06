import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_runtime_lifecycle import fan, ready, regulating, sensor_failsafe


def test_runtime_probe_rejects_incomplete_and_unhealthy_reports():
    assert not ready({'status': {'conditions': [{'type': 'Ready', 'status': 'False'}]}})
    assert ready({'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}})
    assert not regulating({'ready': True, 'fans': {}}, ['a'], 47.5)
    status = {'ready': True, 'fans': {'a': {'ready': True, 'dutyPercent': 47.5}}}
    assert regulating(status, ['a'], 47.5)
    assert not regulating(status, ['a', 'b'], 47.5)
    assert not sensor_failsafe({'ready': False, 'fans': {}}, ['a'])
    status = {'ready': False, 'fans': {'a': {'ready': False, 'dutyPercent': 100, 'reason': 'LocalSensorUnavailable'}}}
    assert sensor_failsafe(status, ['a'])
    assert not sensor_failsafe(status, ['a', 'b'])


def test_runtime_fixtures_use_real_crd_controls_and_distinct_channels():
    from pifanctl.topology.model import normalize
    objects = normalize([fan('pi-a', 'fan-a', 18), fan('pi-a', 'fan-b', 19)])
    assert [obj['spec']['hardware']['rpigpio']['pin'] for obj in objects] == [18, 19]
    assert all(obj['spec']['control']['failsafeDuty'] == 100 for obj in objects)


def test_simulated_io_cannot_activate_without_explicit_marker():
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'sources')}
    env.pop('PIFANCTL_RUNTIME_LAB', None)
    result = subprocess.run([sys.executable, str(ROOT / 'tests/runtime_lab/sitecustomize.py')], env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 79
    assert 'requires explicit' in result.stderr


def test_lab_adapter_emits_driver_calls_and_synthetic_temperature():
    script = '''import runpy
runpy.run_path("tests/runtime_lab/sitecustomize.py")
from pifanctl.drivers import RpiGpioDriver
from pifanctl.thermal import read_zones
pwm=RpiGpioDriver(18,1000,100)
pwm.set_duty(47.5)
pwm.close()
print(read_zones()[0].celsius)
'''
    env = {**os.environ, 'PYTHONPATH': str(ROOT / 'sources'), 'PIFANCTL_RUNTIME_LAB': '1'}
    result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    calls = [json.loads(line) for line in lines[:-1]]
    assert [c['runtime_lab_gpio'] for c in calls] == ['setup', 'start', 'duty', 'stop', 'output']
    assert calls[1]['duty'] == 100 and calls[2]['duty'] == 47.5
    assert calls[-1]['value'] == 1 and lines[-1] == '55.0'
