import copy
import struct
import threading
import types

import pytest
from prometheus_client import generate_latest
from pifanctl.topology import pwm_probe as p
from pifanctl.topology.model import normalize, TopologyError, digest
from pifanctl.topology.planner import plan, worker_plan
from pifanctl.topology.worker import Worker, validate_plan
from test_topology import fan, zone


def feedback(pin=24):
    return {'pwm': {'gpio': {'pin': pin, 'pull': 'off'}, 'sampleSeconds': 1}}


def desired(fb=None):
    return worker_plan(plan([fan(feedback=fb or feedback()), zone(telemetry={'source': 'local'})]), 'pi-a')


def test_optional_defaults_and_validation():
    spec = normalize([fan(feedback={'pwm': {'gpio': {'pin': 24}}})])[0]['spec']
    assert spec['feedback'] == feedback()
    assert 'feedback' not in normalize([fan()])[0]['spec']
    for fb in ({}, {'pwm': {}}, feedback(18), feedback(28), {'pwm': {'gpio': {'pin': 24}, 'sampleSeconds': 6}},
               {**feedback(), 'tachometer': {'gpio': {'pin': 24}}}):
        with pytest.raises(TopologyError): normalize([fan(feedback=fb)])
    with pytest.raises(TopologyError): normalize([fan(hardware={'sysfs': {'chip': 0, 'channel': 0}}, feedback=feedback())])


def test_probe_claims_conflict_and_plan_tamper():
    raw = worker_plan(plan([fan(feedback=feedback()), fan('fan-b', hardware={'rpigpio': {'pin': 24}})]), 'pi-a')
    assert all('HardwareConflict' in f['issues'] for f in raw['fans'].values())
    raw['fans']['fan-a']['issues'].remove('HardwareConflict')
    raw['hash'] = digest({k: v for k, v in raw.items() if k != 'hash'})
    with pytest.raises(TopologyError): validate_plan(raw, 'pi-a')


def edges(hz=1000, duty=.25, n=1000):
    return [(i / hz + (duty / hz if j else 0), 2 * i + j + 1, j + 1)
            for i in range(n) for j in range(2)]


@pytest.mark.parametrize("hz,duty", [(1000, .25), (25000, .60)])
def test_measured_window_and_unknown_static(hz, duty):
    clock = [0.0]; w = p.PwmWindow(feedback()['pwm'], lambda: clock[0])
    assert w.snapshot()['reason'] == 'WarmingUp'
    clock[0] = 1; w.update(edges(hz, duty, hz))
    s = w.snapshot(); assert s['ready'] and s['frequencyHz'] == pytest.approx(hz)
    assert s['dutyPercent'] == pytest.approx(duty * 100) and s['cycleCount'] == hz - 1
    clock[0] = 4; assert w.snapshot()['reason'] == 'CollectorStale'
    w.update(); s = w.snapshot(); assert 'dutyPercent' not in s
    assert s['reason'] == 'InsufficientEdges'


@pytest.mark.parametrize('events,reason', [
    ([(.1, 2, 1)], 'EventSequenceGap'), ([(float('nan'), 1, 1)], 'InvalidEventClock'),
    ([(-1, 1, 1)], 'InvalidEventClock'), ([(2, 1, 1)], 'InvalidEventClock'),
    ([(.2, 1, 1), (.1, 2, 2)], 'InvalidEventClock'),
    ([(.1, 1, 1), (.2, 2, 1)], 'InvalidEdgeOrder'),
    ([(.1, 1, 1), (.2, 2, 2), (.3, 3, 2)], 'InvalidEdgeOrder'),
    ([(.1, 1, 3)], 'InvalidEdgeOrder')])
def test_invalid_windows_never_report_command_as_measurement(events, reason):
    clock = [0]; w = p.PwmWindow(feedback()['pwm'], lambda: clock[0]);clock[0] = 1
    w.update(events); s = w.snapshot(); assert s['reason'] == reason
    assert 'frequencyHz' not in s and 'dutyPercent' not in s


def test_sequence_wrap_and_leading_fall():
    clock = [0];w = p.PwmWindow(feedback()['pwm'], lambda: clock[0]);clock[0] = 1
    w.sequence = 2**32 - 1;w.update([(.1, 0, 2), (.2, 1, 1), (.3, 2, 2), (.4, 3, 1), (.5, 4, 2), (.6, 5, 1)])
    assert w.snapshot()['ready']


def test_signal_overflow_is_bounded():
    clock = [0];w = p.PwmWindow(feedback()['pwm'], lambda: clock[0]);clock[0] = 1
    w.cycles.extend([(.5, .001, .0005)] * 200001);w.update()
    assert w.snapshot()['reason'] == 'SignalOverflow' and not w.cycles


class Sensor:
    def __init__(self, cfg): self.closed = False
    def snapshot(self):
        return {'ready': True, 'reason': '', 'sampleSeconds': 1,
                'cycleCount': 1000, 'frequencyHz': 1000, 'dutyPercent': 25, 'observedTime': 100}
    def close(self): self.closed = True


def test_worker_measurement_remove_reload_and_not_configured(monkeypatch):
    x = Worker('pi-a', mock=True, pwm_probe_factory=Sensor);monkeypatch.setattr(x.local, 'read', lambda: 55)
    x.apply(desired());s = x.cycle(now=100)['fans']['fan-a'];assert s['feedback']['pwm']['dutyPercent'] == 25
    assert s['dutyPercent'] != 25
    assert b'pifanctl_worker_fan_pwm_frequency_hz{' in generate_latest(x.registry)
    sensor = x.pwm_probes['fan-a'];x.apply(desired());assert x.pwm_probes['fan-a'] is sensor
    x.apply(desired(feedback(25)));assert sensor.closed
    x.apply(worker_plan(plan([fan(), zone(telemetry={'source': 'local'})]), 'pi-a'))
    s = x.cycle(now=105)['fans']['fan-a']['feedback']['pwm'];assert s == p.unavailable('NotConfigured')
    assert b'pifanctl_worker_fan_pwm_frequency_hz{fan="fan-a",node="pi-a"} NaN' in generate_latest(x.registry)
    x.apply(desired());sensor=x.pwm_probes['fan-a'];x.apply(worker_plan(plan([]), 'pi-a'));assert sensor.closed
    x.close()


def test_mock_and_unavailable_do_not_alter_regulation(monkeypatch):
    monkeypatch.setattr(p, 'request_input', lambda *a, **kw: pytest.fail('mock touched GPIO'))
    x = Worker('pi-a', mock=True);monkeypatch.setattr(x.local, 'read', lambda: 55)
    x.apply(desired());s=x.cycle(now=100)['fans']['fan-a'];assert s['ready'] and s['feedback']['pwm']['reason']=='MockInput';x.close()
    def fail(cfg): raise OSError('busy')
    x=Worker('pi-a', mock=True, pwm_probe_factory=fail);monkeypatch.setattr(x.local,'read',lambda:55)
    x.apply(desired());s=x.cycle(now=100)['fans']['fan-a'];assert s['ready'] and s['feedback']['pwm']['reason']=='Unavailable';x.close()


def test_snapshot_error_clears_metrics_and_close_error_failsafe(monkeypatch):
    x=Worker('pi-a', mock=True, pwm_probe_factory=Sensor);monkeypatch.setattr(x.local,'read',lambda:55)
    x.apply(desired());x.cycle(now=100);sensor=x.pwm_probes['fan-a']
    monkeypatch.setattr(sensor,'snapshot',lambda: (_ for _ in ()).throw(OSError()))
    assert x.cycle(now=105)['fans']['fan-a']['feedback']['pwm']['reason']=='CollectorError'
    assert b'pifanctl_worker_fan_pwm_frequency_hz{fan="fan-a",node="pi-a"} NaN' in generate_latest(x.registry)
    duties=[];monkeypatch.setattr(x.drivers['fan-a'],'set_duty',duties.append)
    monkeypatch.setattr(sensor,'close',lambda: (_ for _ in ()).throw(OSError('close')))
    with pytest.raises(OSError):x.close()
    assert duties==[100]


def test_reader_decodes_both_edges_and_releases(monkeypatch):
    class Thread:
        def __init__(self, **kw):pass
        def start(self):pass
        def join(self, **kw):pass
        def is_alive(self):return False
    monkeypatch.setattr(p.threading,'Thread',Thread)
    calls=[];monkeypatch.setattr(p,'request_input',lambda cfg,**kw: calls.append(kw) or 11)
    sensor=p.GpioPwmProbe(feedback()['pwm']);now=sensor.window.clock()
    def read(*args):
        sensor.stop.set();return struct.pack('=QIIII6I',int(now*1e9),1,24,1,1,*([0]*6))
    monkeypatch.setattr(p.select,'select',lambda *a:([11],[],[]));monkeypatch.setattr(p.os,'read',read)
    sensor._read();assert sensor.window.sequence==1 and calls==[{'both_edges':True}]
    closed=[];monkeypatch.setattr(p.os,'close',closed.append);sensor.close();assert closed==[11]


@pytest.mark.parametrize('data',[b'',b'x',struct.pack('=QIIII6I',0,1,23,1,1,*([0]*6))])
def test_reader_error_is_na(monkeypatch,data):
    sensor=p.GpioPwmProbe.__new__(p.GpioPwmProbe);sensor.window=p.PwmWindow(feedback()['pwm']);sensor.pin=24;sensor.fd=11;sensor.stop=threading.Event()
    monkeypatch.setattr(p.select,'select',lambda *a:([11],[],[]));monkeypatch.setattr(p.os,'read',lambda *a:data)
    sensor._read();assert sensor.snapshot()['reason']=='CollectorError'


def test_reader_idle_and_start_failure(monkeypatch):
    sensor=p.GpioPwmProbe.__new__(p.GpioPwmProbe);sensor.window=p.PwmWindow(feedback()['pwm']);sensor.pin=24;sensor.fd=11;sensor.stop=threading.Event()
    def idle(*a):sensor.stop.set();return([],[],[])
    monkeypatch.setattr(p.select,'select',idle);sensor._read();assert not sensor.window.error
    monkeypatch.setattr(p,'request_input',lambda *a,**kw:11)
    monkeypatch.setattr(p.threading.Thread,'start',lambda self:(_ for _ in ()).throw(RuntimeError()))
    closed=[];monkeypatch.setattr(p.os,'close',closed.append)
    with pytest.raises(RuntimeError):p.GpioPwmProbe(feedback()['pwm'])
    assert closed==[11]


@pytest.mark.parametrize('configured,ready,stamp,expected',[
    (False,False,None,'N/A'),(True,False,None,'N/A'),
    (True,True,'old','N/A'),(True,True,'invalid','N/A'),(True,True,'fresh',1000)])
def test_cli_available_and_missing(monkeypatch,configured,ready,stamp,expected):
    from datetime import datetime,timezone,timedelta
    import yaml
    from typer.testing import CliRunner
    from main import app
    from pifanctl.topology import cli
    if stamp=='fresh':stamp=datetime.now(timezone.utc).isoformat()
    elif stamp=='old':stamp=(datetime.now(timezone.utc)-timedelta(seconds=61)).isoformat()
    item={'spec':{'feedback':feedback() if configured else {}},'status':{'dutyPercent':80,'feedback':{'pwm':{'ready':ready,'reason':'','frequencyHz':1000,'dutyPercent':25,'observedAt':stamp}}}}
    monkeypatch.setattr(cli,'api',lambda ctx:types.SimpleNamespace(get=lambda path:item))
    result=CliRunner().invoke(app,['fan','measurements','fan-a']);assert result.exit_code==0,result.output
    body=yaml.safe_load(result.output);assert body['pwm']['frequencyHz']==expected
    assert 'User must verify' in body['rpmNotice']


def test_cli_zero_rpm_and_pulse_configuration_notice(monkeypatch):
    from datetime import datetime,timezone
    import yaml
    from typer.testing import CliRunner
    from main import app
    from pifanctl.topology import cli
    item={'spec':{'feedback':{'tachometer':{'gpio':{'pin':23}}}},'status':{'feedback':{'tachometer':{'ready':False,'reason':'NoPulses','rpm':0,'observedAt':datetime.now(timezone.utc).isoformat()}}}}
    monkeypatch.setattr(cli,'api',lambda ctx:types.SimpleNamespace(get=lambda path:item))
    r=CliRunner().invoke(app,['fan','measurements','fan-a']);assert r.exit_code==0,r.output
    assert yaml.safe_load(r.output)['rpm']==0


def test_gpio_v2_both_edges_input_only_request(monkeypatch):
    from test_tachometer import fake_gpio
    from pifanctl.topology import tachometer as t
    fake_gpio(monkeypatch)
    monkeypatch.setattr(t.Path,'read_text',lambda self:'Raspberry Pi 4')
    monkeypatch.setattr(t.glob,'glob',lambda pattern:['chip'])
    monkeypatch.setattr(t.os,'open',lambda *a:10)
    monkeypatch.setattr(t.os,'close',lambda *a:None)
    monkeypatch.setattr(t.os,'set_blocking',lambda *a:None)
    def ioctl(fd,op,buffer,mutate):
        if op==0x8044b401:buffer[:]=struct.pack('=32s32sI',b'chip',b'pinctrl-bcm2711',58)
        else:
            assert struct.unpack_from('=Q',buffer,288)[0]==4|16|32|1024
            assert struct.unpack_from('=II',buffer,560)==(1,4096)
            struct.pack_into('=i',buffer,588,11)
    monkeypatch.setattr(t.fcntl,'ioctl',ioctl)
    assert t.request_input(feedback()['pwm'],both_edges=True)==11
