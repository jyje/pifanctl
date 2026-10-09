import copy
import struct
import sys
import types

import pytest
from prometheus_client import generate_latest

from pifanctl.topology import tachometer as t
from pifanctl.topology.model import TopologyError, normalize, digest
from pifanctl.topology.planner import plan, worker_plan
from pifanctl.topology.worker import Worker, validate_plan
from test_topology import fan, zone


def feedback(pin=23, pull='up'):
    return {'tachometer': {'gpio': {'pin': pin, 'pull': pull}, 'pulsesPerRevolution': 2, 'sampleSeconds': 5}}


def desired(fb=None):
    return worker_plan(plan([fan(feedback=fb or feedback()), zone(telemetry={'source': 'local'})]), 'pi-a')


def test_optional_feedback_defaults_and_old_values():
    old = normalize([fan()])[0]['spec']
    assert 'feedback' not in old
    assert old['hardware']['rpigpio']['frequencyHz'] == 1000
    spec = normalize([fan(feedback={'tachometer': {'gpio': {'pin': 23}}})])[0]['spec']
    assert spec['feedback'] == feedback(pull='off')


@pytest.mark.parametrize('change', [
    {'tachometer': {'gpio': {'pin': 18}}},
    {'tachometer': {'gpio': {'pin': 28}}},
    {'tachometer': {'gpio': {'pin': 23, 'pull': '5v'}}},
    {'tachometer': {'gpio': {'pin': 23}, 'pulsesPerRevolution': 0}},
    {'tachometer': {'gpio': {'pin': 23}, 'sampleSeconds': 0}},
    {'tachometer': {}}, {},
])
def test_feedback_validation(change):
    with pytest.raises(TopologyError): normalize([fan(feedback=change)])


def test_sysfs_feedback_not_supported():
    with pytest.raises(TopologyError):
        normalize([fan(hardware={'sysfs': {'chip': 0, 'channel': 0}}, feedback=feedback())])


@pytest.mark.parametrize('second', [fan('fan-b', hardware={'rpigpio': {'pin': 23}}), fan('fan-b', hardware={'rpigpio': {'pin': 12}}, feedback=feedback())])
def test_input_output_and_input_input_conflicts(second):
    p = plan([fan(feedback=feedback()), second, zone()])
    assert all('HardwareConflict' in f['issues'] for f in p['fans'].values())
    raw = copy.deepcopy(worker_plan(p, 'pi-a'))
    raw['fans']['fan-a']['issues'].remove('HardwareConflict')
    raw['hash'] = digest({k: v for k, v in raw.items() if k != 'hash'})
    with pytest.raises(TopologyError): validate_plan(raw, 'pi-a')
    x = Worker('pi-a', mock=True); x.apply(worker_plan(p, 'pi-a'))
    assert not x.drivers and not x.tachometers


def test_window_rpm_zero_warmup_and_stale():
    clock = [0.0]
    w = t.PulseWindow(feedback()['tachometer'], lambda: clock[0])
    assert w.snapshot()['reason'] == 'WarmingUp'
    clock[0] = 5
    w.update([(i / 100, i) for i in range(1, 501)])
    assert w.snapshot()['rpm'] == 3000
    assert w.snapshot()['pulseCount'] == 500
    clock[0] = 8
    assert w.snapshot()['reason'] == 'CollectorStale' and 'rpm' not in w.snapshot()
    clock[0] = 11; w.update()
    assert w.snapshot()['rpm'] == 0 and w.snapshot()['reason'] == 'NoPulses'


@pytest.mark.parametrize('events,reason', [([(1, 2)], 'EventSequenceGap'), ([(float('nan'), 1)], 'InvalidEventClock'), ([(10, 1)], 'InvalidEventClock'), ([(-1, 1)], 'InvalidEventClock'), ([(0.9, 1), (0.8, 2)], 'InvalidEventClock')])
def test_invalid_events_do_not_publish_rpm(events, reason):
    clock = [0]
    w = t.PulseWindow(feedback()['tachometer'], lambda: clock[0])
    clock[0] = 1; w.update(events)
    assert w.snapshot()['reason'] == reason and 'rpm' not in w.snapshot()


def test_signal_overflow_and_sequence_wrap():
    clock = [0]
    w = t.PulseWindow(feedback()['tachometer'], lambda: clock[0])
    clock[0] = 1; w.sequence = 2**32 - 1; w.update([(0.5, 0)])
    assert not w.error
    w.update([(0.6, i) for i in range(1, 10002)])
    assert w.error == 'SignalOverflow' and not w.edges


class Sensor:
    def __init__(self, config): self.closed = False
    def snapshot(self): return {'ready': True, 'reason': '', 'rpm': 1200, 'observedTime': 100, 'sampleSeconds': 5, 'pulseCount': 200}
    def close(self): self.closed = True


def test_worker_feedback_metrics_reload_remove(monkeypatch):
    x = Worker('pi-a', mock=True, tachometer_factory=Sensor)
    monkeypatch.setattr(x.local, 'read', lambda: 55)
    x.apply(desired()); old = x.tachometers['fan-a']
    state = x.cycle(now=100)['fans']['fan-a']
    assert state['ready'] and state['feedback']['tachometer']['rpm'] == 1200
    assert b'pifanctl_worker_fan_rpm{' in generate_latest(x.registry)
    x.apply(desired()); assert x.tachometers['fan-a'] is old
    x.apply(desired(feedback(pull='off'))); assert old.closed
    removed = fan(); x.apply(worker_plan(plan([removed, zone(telemetry={'source': 'local'})]), 'pi-a'))
    assert not x.tachometers and 'tachometer' not in x.cycle(now=105)['fans']['fan-a']['feedback']
    assert b'pifanctl_worker_fan_rpm{' not in generate_latest(x.registry)
    x.apply(desired()); current = x.tachometers['fan-a']
    x.apply(worker_plan(plan([]), 'pi-a')); assert current.closed
    x.close()


def test_feedback_failure_does_not_change_pwm(monkeypatch):
    def fail(config): raise OSError('busy')
    x = Worker('pi-a', mock=True, tachometer_factory=fail)
    monkeypatch.setattr(x.local, 'read', lambda: 55)
    x.apply(desired()); state = x.cycle(now=100)['fans']['fan-a']
    assert state['ready'] and state['dutyPercent'] == 95
    assert state['feedback']['tachometer']['reason'] == 'Unavailable'
    x.close()


def test_snapshot_failure_and_stale_metric_removal(monkeypatch):
    x = Worker('pi-a', mock=True, tachometer_factory=Sensor)
    monkeypatch.setattr(x.local, 'read', lambda: 55)
    x.apply(desired()); x.cycle(now=100)
    monkeypatch.setattr(x.tachometers['fan-a'], 'snapshot', lambda: (_ for _ in ()).throw(OSError()))
    assert x.cycle(now=105)['fans']['fan-a']['feedback']['tachometer']['reason'] == 'CollectorError'
    assert b'pifanctl_worker_fan_rpm{' not in generate_latest(x.registry)
    x.close()


def test_mock_feedback_never_opens_gpio(monkeypatch):
    monkeypatch.setattr(t, 'request_input', lambda config: pytest.fail('mock touched GPIO'))
    x = Worker('pi-a', mock=True); monkeypatch.setattr(x.local, 'read', lambda: 55)
    x.apply(desired())
    assert x.cycle()['fans']['fan-a']['feedback']['tachometer']['reason'] == 'MockInput'
    x.close()


def fake_gpio(monkeypatch, function=1):
    gpio = types.ModuleType('RPi.GPIO'); gpio.IN = 1; gpio.BCM = 11
    gpio.setmode = lambda mode: None; gpio.gpio_function = lambda pin: function
    monkeypatch.setitem(sys.modules, 'RPi', types.ModuleType('RPi'))
    monkeypatch.setitem(sys.modules, 'RPi.GPIO', gpio)


def test_gpio_v2_request_abi_exclusive_input_and_bias(monkeypatch):
    fake_gpio(monkeypatch)
    monkeypatch.setattr(t.Path, 'read_text', lambda self: 'Raspberry Pi 4 Model B')
    monkeypatch.setattr(t.glob, 'glob', lambda pattern: ['chip'])
    monkeypatch.setattr(t.os, 'open', lambda *args: 10)
    closed = []; monkeypatch.setattr(t.os, 'close', closed.append)
    monkeypatch.setattr(t.os, 'set_blocking', lambda fd, flag: None)
    def ioctl(fd, operation, buffer, mutate):
        if operation == 0x8044b401:
            buffer[:] = struct.pack('=32s32sI', b'gpiochip0', b'pinctrl-bcm2711', 58)
        else:
            assert operation == 0xc250b407 and len(buffer) == 592
            # Independent ctypes layout follows Linux uapi gpio.h field order.
            import ctypes as c
            class Config(c.Structure):
                _fields_ = [('flags', c.c_uint64), ('num_attrs', c.c_uint32),
                            ('padding', c.c_uint32 * 5), ('attrs', c.c_uint64 * 30)]
            class Request(c.Structure):
                _fields_ = [('offsets', c.c_uint32 * 64), ('consumer', c.c_char * 32),
                            ('config', Config), ('num_lines', c.c_uint32),
                            ('event_buffer_size', c.c_uint32), ('padding', c.c_uint32 * 5),
                            ('fd', c.c_int32)]
            request = Request.from_buffer_copy(buffer)
            assert c.sizeof(request) == 592
            assert request.offsets[0] == 23 and request.config.flags == 4 | 32 | 256
            assert request.config.num_attrs == 0 and request.num_lines == 1
            assert request.event_buffer_size == 128 and not any(request.config.padding)
            assert struct.unpack_from('=I', buffer, 0)[0] == 23
            assert struct.unpack_from('=Q', buffer, 288)[0] == 4 | 32 | 256
            assert struct.unpack_from('=II', buffer, 560) == (1, 128)
            struct.pack_into('=i', buffer, 588, 11)
    monkeypatch.setattr(t.fcntl, 'ioctl', ioctl)
    assert t.request_input(feedback()['tachometer']) == 11 and closed == [10]


def test_gpio_refuses_non_pi4_and_existing_output(monkeypatch):
    monkeypatch.setattr(t.Path, 'read_text', lambda self: 'Raspberry Pi 5')
    with pytest.raises(OSError, match='Pi 4'): t.request_input(feedback()['tachometer'])
    fake_gpio(monkeypatch, function=0)
    monkeypatch.setattr(t.Path, 'read_text', lambda self: 'Raspberry Pi 4')
    with pytest.raises(OSError, match='output'): t.request_input(feedback()['tachometer'])


@pytest.mark.parametrize('pull,flag', [('off', 1024), ('down', 512)])
def test_gpio_bias_and_release_on_failure(monkeypatch, pull, flag):
    fake_gpio(monkeypatch)
    monkeypatch.setattr(t.Path, 'read_text', lambda self: 'Raspberry Pi 4')
    monkeypatch.setattr(t.glob, 'glob', lambda pattern: ['chip'])
    monkeypatch.setattr(t.os, 'open', lambda *args: 10)
    closed = []; monkeypatch.setattr(t.os, 'close', closed.append)
    def ioctl(fd, operation, buffer, mutate):
        if operation == 0x8044b401: buffer[:] = struct.pack('=32s32sI', b'chip', b'pinctrl-bcm2711', 58)
        else:
            assert struct.unpack_from('=Q', buffer, 288)[0] == 4 | 32 | flag
            raise OSError('busy')
    monkeypatch.setattr(t.fcntl, 'ioctl', ioctl)
    with pytest.raises(OSError, match='busy'): t.request_input(feedback(pull=pull)['tachometer'])
    assert closed == [10]


def test_missing_controller(monkeypatch):
    fake_gpio(monkeypatch)
    monkeypatch.setattr(t.Path, 'read_text', lambda self: 'Raspberry Pi 4')
    monkeypatch.setattr(t.glob, 'glob', lambda pattern: ['wrong-chip'])
    monkeypatch.setattr(t.os, 'open', lambda *args: 10)
    closed = []; monkeypatch.setattr(t.os, 'close', closed.append)
    def ioctl(fd, operation, buffer, mutate): buffer[:] = struct.pack('=32s32sI', b'chip', b'other', 28)
    monkeypatch.setattr(t.fcntl, 'ioctl', ioctl)
    with pytest.raises(OSError, match='not found'): t.request_input(feedback()['tachometer'])
    assert closed == [10]


def test_nonblocking_failure_closes_request(monkeypatch):
    fake_gpio(monkeypatch)
    monkeypatch.setattr(t.Path, 'read_text', lambda self: 'Raspberry Pi 4')
    monkeypatch.setattr(t.glob, 'glob', lambda pattern: ['chip'])
    monkeypatch.setattr(t.os, 'open', lambda *args: 10)
    closed = []; monkeypatch.setattr(t.os, 'close', closed.append)
    def ioctl(fd, operation, buffer, mutate):
        if operation == 0x8044b401: buffer[:] = struct.pack('=32s32sI', b'chip', b'pinctrl-bcm2711', 58)
        else: struct.pack_into('=i', buffer, 588, 11)
    monkeypatch.setattr(t.fcntl, 'ioctl', ioctl)
    monkeypatch.setattr(t.os, 'set_blocking', lambda *a: (_ for _ in ()).throw(OSError('flags')))
    with pytest.raises(OSError): t.request_input(feedback()['tachometer'])
    assert closed == [11, 10]


def test_reader_decodes_kernel_events_and_closes(monkeypatch):
    class Thread:
        def __init__(self, **kwargs): self.target = kwargs['target']
        def start(self): pass
        def join(self, **kwargs): pass
        def is_alive(self): return False
    monkeypatch.setattr(t, 'request_input', lambda config: 11)
    monkeypatch.setattr(t.threading, 'Thread', Thread)
    sensor = t.GpioTachometer(feedback()['tachometer'])
    now = sensor.window.clock()
    def read(fd, size):
        sensor.stop.set()
        return struct.pack('=QIIII6I', int(now*1e9), 2, 23, 1, 1, *([0]*6))
    monkeypatch.setattr(t.select, 'select', lambda *args: ([11], [], []))
    monkeypatch.setattr(t.os, 'read', read)
    sensor._read()
    assert sensor.window.sequence == 1
    assert sensor.snapshot()['reason'] == 'WarmingUp'
    closed = []; monkeypatch.setattr(t.os, 'close', closed.append)
    sensor.close(); assert closed == [11]


@pytest.mark.parametrize('data', [b'', b'x', struct.pack('=QIIII6I', 0, 1, 23, 1, 1, *([0]*6))])
def test_reader_errors_are_observable(monkeypatch, data):
    import threading
    from gpio_reader_support import DeferredReaderThread
    monkeypatch.setattr(t, 'request_input', lambda config: 11)
    monkeypatch.setattr(t.threading, 'Thread', DeferredReaderThread)
    sensor = t.GpioTachometer(feedback()['tachometer'])
    monkeypatch.setattr(t.select, 'select', lambda *args: ([11], [], []))
    monkeypatch.setattr(t.os, 'read', lambda *args: data)
    sensor._read()
    assert sensor.snapshot()['reason'] == 'CollectorError'


def test_idle_reader_progress_and_start_failure(monkeypatch):
    import threading
    from gpio_reader_support import DeferredReaderThread
    monkeypatch.setattr(t, 'request_input', lambda config: 11)
    monkeypatch.setattr(t.threading, 'Thread', DeferredReaderThread)
    sensor = t.GpioTachometer(feedback()['tachometer'])
    def idle(*args): sensor.stop.set(); return ([], [], [])
    monkeypatch.setattr(t.select, 'select', idle)
    sensor._read(); assert not sensor.window.error
    monkeypatch.setattr(t, 'request_input', lambda config: 11)
    monkeypatch.setattr(t.threading.Thread, 'start', lambda self: (_ for _ in ()).throw(RuntimeError('start')))
    closed = []; monkeypatch.setattr(t.os, 'close', closed.append)
    with pytest.raises(RuntimeError): t.GpioTachometer(feedback()['tachometer'])
    assert closed == [11]


def test_close_refuses_to_release_a_running_reader(monkeypatch):
    from gpio_reader_support import DeferredReaderThread
    class StalledReaderThread(DeferredReaderThread):
        def is_alive(self): return True
    monkeypatch.setattr(t, 'request_input', lambda config: 11)
    monkeypatch.setattr(t.threading, 'Thread', StalledReaderThread)
    sensor = t.GpioTachometer(feedback()['tachometer'])
    with pytest.raises(RuntimeError, match='did not stop'): sensor.close()


def test_feedback_close_error_still_requests_failsafe(monkeypatch):
    x = Worker('pi-a', mock=True, tachometer_factory=Sensor)
    x.apply(desired()); driver = x.drivers['fan-a']
    duties = []; closed = []
    monkeypatch.setattr(driver, 'set_duty', duties.append)
    monkeypatch.setattr(driver, 'close', lambda: closed.append(True))
    monkeypatch.setattr(x.tachometers['fan-a'], 'close', lambda: (_ for _ in ()).throw(OSError('close')))
    with pytest.raises(OSError, match='close'): x.close()
    assert duties == [100] and closed == [True]


def test_reload_requires_old_input_identity_release():
    x = Worker('pi-a', mock=True, tachometer_factory=Sensor)
    x.apply(desired())
    new = plan([fan('fan-b', hardware={'rpigpio': {'pin': 23}}), zone(fanRefs=['fan-b'])])
    with pytest.raises(TopologyError, match='release the previous'): x.apply(worker_plan(new, 'pi-a'))
    x.close()
