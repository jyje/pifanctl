import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('gpio_analysis', Path('scripts/analyze_gpio_observation.py'))
module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)


def test_cycle_conversion_and_incomplete_edges():
    r = module.analyze([(0, 0), (.001, 1), (.00125, 0), (.002, 1), (.00225, 0), (.003, 1)])
    assert r['complete_cycles'] == 2
    assert r['median_cycle_hz'] == pytest.approx(1000)
    assert r['median_observed_high_percent'] == pytest.approx(25)
    assert not r['fan_connector_measured'] and not r['voltage_measured']


@pytest.mark.parametrize('events', [[], [(0, 1), (1, 0)], [(0, 0), (1, 1), (2, 0)],
    [(0, 1), (0, 0), (1, 1)], [(0, 1), (1, 1), (2, 0)],
    [(0, 1), (1, 2), (2, 1)], [(0, 1), (float('nan'), 0), (2, 1)],
    [(-1, 1), (1, 0), (2, 1)], [(0, 1), (float('inf'), 0), (2, 1)]])
def test_invalid_observations(events):
    with pytest.raises(ValueError): module.analyze(events)


def test_collector_is_read_only_and_memory_bounded():
    source = Path('scripts/observe_gpio_levels.py').read_text()
    assert 'os.O_RDONLY' in source and 'prot=mmap.PROT_READ' in source
    assert 'deque(maxlen=100000)' in source
    assert 'GPIO.setup' not in source and 'PROT_WRITE' not in source


def load_collector():
    spec = importlib.util.spec_from_file_location('gpio_capture', Path('scripts/observe_gpio_levels.py'))
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def fake_capture(monkeypatch, step=.25, temperature=45000):
    import struct
    capture = load_collector()
    memory = bytearray(4096); struct.pack_into('<I', memory, 4, 1 << 24)
    struct.pack_into('<I', memory, 0xe8, 2 << 14)
    class Mapping:
        def __enter__(self): return memory
        def __exit__(self, *args): pass
    def mapping(fd, length, flags, prot):
        assert fd == 12 and length == 4096 and prot == capture.mmap.PROT_READ
        return Mapping()
    clock = [0.0, 0]
    def tick():
        clock[0] += step; clock[1] += 1
        struct.pack_into('<I', memory, 0x34, (clock[1] % 2) << 18)
        return clock[0]
    monkeypatch.setattr(capture.time, 'monotonic', tick)
    monkeypatch.setattr(capture.mmap, 'mmap', mapping)
    monkeypatch.setattr(capture.Path, 'read_text', lambda path: 'Raspberry Pi 4' if path.name == 'model' else str(temperature))
    def opened(path, flags):
        assert path == '/dev/gpiomem' and flags == capture.os.O_RDONLY
        return 12
    monkeypatch.setattr(capture.os, 'open', opened)
    closed = []; monkeypatch.setattr(capture.os, 'close', closed.append)
    return capture, closed


def test_capture_closes_read_only_mapping_and_reports(monkeypatch, capsys):
    import json
    capture, closed = fake_capture(monkeypatch)
    capture.capture(); report = json.loads(capsys.readouterr().out)
    assert closed == [12] and report['samples'] > 0
    assert report['configuration_registers_unchanged']
    assert report['tach_falling_edges'] == 0 and report['quantile_tail_samples'] <= 100000


def test_capture_temperature_guard_runs_before_open(monkeypatch):
    capture, closed = fake_capture(monkeypatch, temperature=60000)
    with pytest.raises(RuntimeError, match='temperature cutoff'): capture.capture()
    assert closed == []


def test_capture_transition_overflow_closes_mapping(monkeypatch):
    capture, closed = fake_capture(monkeypatch, step=.000001)
    with pytest.raises(RuntimeError, match='Transition limit'): capture.capture()
    assert closed == [12]
