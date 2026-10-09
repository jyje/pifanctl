"""Optional independent Pi 4 digital PWM probe, never an output driver."""
from collections import deque
import math
import os
import select
import struct
import threading
import time

from pifanctl.topology.tachometer import GpioTachometer, request_input


def unavailable(reason, seconds=0, count=0):
    return {'ready': False, 'reason': reason,
            'sampleSeconds': seconds, 'cycleCount': count}


class PwmWindow:
    def __init__(self, config, clock=time.monotonic):
        self.clock = clock
        self.started = self.progress = clock()
        self.seconds = config['sampleSeconds']
        self.sequence = 0
        self.previous = self.rise = self.fall = None
        self.cycles = deque()
        self.error = ''
        self.lock = threading.Lock()

    def update(self, events=()):
        with self.lock:
            now = self.clock()
            for stamp, sequence, edge in events:
                if (not math.isfinite(stamp) or stamp < self.started or stamp > now + 0.1
                        or (self.previous is not None and stamp <= self.previous)):
                    self.error = 'InvalidEventClock'
                if sequence != (self.sequence + 1) % (2**32):
                    self.error = 'EventSequenceGap'
                self.sequence = sequence
                self.previous = stamp
                if edge == 1:
                    if self.rise is not None:
                        if self.fall is None or not self.rise < self.fall < stamp:
                            self.error = 'InvalidEdgeOrder'
                        else:
                            self.cycles.append((stamp, stamp - self.rise, self.fall - self.rise))
                    self.rise, self.fall = stamp, None
                elif edge == 2:
                    if self.fall is not None:
                        self.error = 'InvalidEdgeOrder'
                    if self.rise is not None:
                        self.fall = stamp
                else:
                    self.error = 'InvalidEdgeOrder'
            while self.cycles and self.cycles[0][0] <= now - self.seconds:
                self.cycles.popleft()
            if len(self.cycles) > 200000:
                self.error = 'SignalOverflow'
                self.cycles.clear()
            self.progress = now

    def snapshot(self):
        with self.lock:
            now = self.clock()
            elapsed = min(self.seconds, max(0, now - self.started))
            reason = self.error or ('CollectorStale' if now - self.progress > 2 else '')
            if not reason and elapsed < self.seconds:
                reason = 'WarmingUp'
            cycles = [c for c in self.cycles if now - self.seconds < c[0] <= now]
            if not reason and len(cycles) < 2:
                reason = 'InsufficientEdges'
            if reason:
                return unavailable(reason, elapsed, len(cycles))
            period = sum(c[1] for c in cycles)
            high = sum(c[2] for c in cycles)
            frequency = len(cycles) / period
            duty = high * 100 / period
            return {'ready': True, 'reason': '',
                    'sampleSeconds': elapsed, 'cycleCount': len(cycles),
                    'frequencyHz': frequency, 'dutyPercent': duty,
                    'observedTime': time.time() - max(0, now - cycles[-1][0])}


class GpioPwmProbe(GpioTachometer):
    def __init__(self, config):
        self.window = PwmWindow(config)
        self.pin = config['gpio']['pin']
        self.fd = request_input(config, both_edges=True)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True, name='pifanctl-pwm-probe')
        try:
            self.thread.start()
        except Exception:
            os.close(self.fd)
            raise

    def _read(self):
        try:
            while not self.stop.is_set():
                events = []
                if select.select([self.fd], [], [], 0.1)[0]:
                    data = os.read(self.fd, 48 * 4096)
                    if not data or len(data) % 48:
                        raise OSError('invalid GPIO event buffer')
                    for offset in range(0, len(data), 48):
                        stamp, edge, pin, sequence, _ = struct.unpack_from('=QIIII', data, offset)
                        if edge not in (1, 2) or pin != self.pin:
                            raise OSError('unexpected GPIO event')
                        events.append((stamp / 1e9, sequence, edge))
                self.window.update(events)
        except Exception:
            with self.window.lock:
                self.window.error = 'CollectorError'


class MockPwmProbe:
    def __init__(self, config):
        pass

    def snapshot(self):
        return unavailable('MockInput')

    def close(self):
        pass
