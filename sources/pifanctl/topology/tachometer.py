"""Optional Pi 4 RPM feedback using exclusive Linux GPIO v2 falling-edge events."""
from collections import deque
import fcntl
import glob
import math
import os
from pathlib import Path
import select
import struct
import threading
import time


class PulseWindow:
    def __init__(self, config, clock=time.monotonic):
        self.clock = clock
        self.started = self.progress = clock()
        self.seconds = config['sampleSeconds']
        self.pulses = config['pulsesPerRevolution']
        self.edges = deque()
        self.sequence = 0
        self.error = ''
        self.lock = threading.Lock()

    def update(self, events=()):
        with self.lock:
            now = self.clock()
            for timestamp, sequence in events:
                if (not math.isfinite(timestamp) or timestamp < self.started
                        or timestamp > now + 0.1 or (self.edges and timestamp < self.edges[-1])):
                    self.error = 'InvalidEventClock'
                if sequence != (self.sequence + 1) % (2**32):
                    self.error = 'EventSequenceGap'
                self.sequence = sequence
                self.edges.append(timestamp)
            while self.edges and self.edges[0] <= now - self.seconds:
                self.edges.popleft()
            if len(self.edges) > 10000:
                self.error = 'SignalOverflow'
                self.edges.clear()
            self.progress = now

    def snapshot(self):
        with self.lock:
            now = self.clock()
            elapsed = min(self.seconds, max(0.0, now - self.started))
            reason = self.error or ('CollectorStale' if now - self.progress > 2 else '')
            if not reason and elapsed < self.seconds:
                reason = 'WarmingUp'
            count = sum(now - self.seconds < edge <= now for edge in self.edges)
            if not reason and not count:
                reason = 'NoPulses'
            result = {'ready': not bool(reason), 'reason': reason,
                      'sampleSeconds': elapsed, 'pulseCount': count}
            if reason in ('', 'NoPulses'):
                result['rpm'] = count * 60 / (self.pulses * self.seconds)
                result['observedTime'] = time.time() - max(0, now - self.progress)
            return result


def request_input(config, both_edges=False):
    """Linux GPIO v2 ABI: input only, falling edges, monotonic timestamps."""
    model = Path('/proc/device-tree/model').read_text().strip('\0')
    if 'Raspberry Pi 4' not in model:
        raise OSError('tachometer GPIO backend currently requires Raspberry Pi 4')
    # RPi.GPIO writers bypass kernel line ownership. Refuse an existing output
    # or alternate function even when the character-device request looks free.
    import RPi.GPIO as GPIO
    GPIO.setmode(GPIO.BCM)
    if GPIO.gpio_function(config['gpio']['pin']) != GPIO.IN:
        raise OSError('tachometer pin is already an output or alternate function')
    for path in sorted(glob.glob('/dev/gpiochip*')):
        chip = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
        try:
            info = bytearray(68)
            fcntl.ioctl(chip, 0x8044b401, info, True)
            _, label, lines = struct.unpack('=32s32sI', info)
            if label.rstrip(b'\0') != b'pinctrl-bcm2711' or lines <= config['gpio']['pin']:
                continue
            request = bytearray(592)
            struct.pack_into('=I', request, 0, config['gpio']['pin'])
            consumer = b'pifanctl-pwm-probe' if both_edges else b'pifanctl-tachometer'
            request[256:288] = consumer.ljust(32, b'\0')
            # gpio_v2_line_request: config occupies bytes 288-559;
            # num_lines/event_buffer_size follow it, before padding and fd.
            struct.pack_into('=II', request, 560, 1, 4096 if both_edges else 128)
            bias = {'up': 1 << 8, 'down': 1 << 9, 'off': 1 << 10}[config['gpio']['pull']]
            struct.pack_into('=Q', request, 288, (1 << 2) | (1 << 5) | ((1 << 4) if both_edges else 0) | bias)
            fcntl.ioctl(chip, 0xc250b407, request, True)
            fd = struct.unpack_from('=i', request, 588)[0]
            try:
                os.set_blocking(fd, False)
            except Exception:
                os.close(fd)
                raise
            return fd
        finally:
            os.close(chip)
    raise OSError('Pi 4 GPIO controller was not found')


class GpioTachometer:
    def __init__(self, config):
        self.window = PulseWindow(config)
        self.pin = config['gpio']['pin']
        self.fd = request_input(config)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._read, daemon=True, name='pifanctl-tachometer')
        try:
            self.thread.start()
        except Exception:
            os.close(self.fd)
            raise

    def _read(self):
        try:
            while not self.stop.is_set():
                events = []
                if select.select([self.fd], [], [], 0.25)[0]:
                    data = os.read(self.fd, 48 * 128)
                    if not data or len(data) % 48:
                        raise OSError('invalid GPIO event buffer')
                    for offset in range(0, len(data), 48):
                        timestamp, event, pin, sequence, _ = struct.unpack_from('=QIIII', data, offset)
                        if event != 2 or pin != self.pin:
                            raise OSError('unexpected GPIO event')
                        events.append((timestamp / 1e9, sequence))
                self.window.update(events)
        except Exception:
            with self.window.lock:
                self.window.error = 'CollectorError'

    def snapshot(self):
        return self.window.snapshot()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=2)
        if self.thread.is_alive():
            raise RuntimeError('tachometer reader did not stop')
        os.close(self.fd)


class MockTachometer:
    def __init__(self, config):
        pass

    def snapshot(self):
        return {'ready': False, 'reason': 'MockInput', 'sampleSeconds': 0, 'pulseCount': 0}

    def close(self):
        pass
