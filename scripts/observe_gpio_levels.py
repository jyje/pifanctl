"""Read-only Pi 4 GPIO18/PWM and GPIO23/tach observation, never reconfigure pins.

Run on the actuator through `kubectl exec -i ... -- python - < this_file`.
This is an intrusive CPU observer, not a calibrated connector waveform probe.
"""
from collections import deque
import json
import mmap
import os
from pathlib import Path
import statistics
import struct
import time


def capture():
    if 'Raspberry Pi 4' not in Path('/proc/device-tree/model').read_text():
        raise RuntimeError('Pi 4 required')
    def check_temperature():
        if int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) >= 60000:
            raise RuntimeError('Local temperature cutoff')
    check_temperature()
    fd = os.open('/dev/gpiomem', os.O_RDONLY)
    report = {'method': 'read-only SoC GPIO level polling', 'configuration_changed': False,
              'fan_connector_measured': False, 'voltage_measured': False,
              'duration_limit_seconds': 10, 'transition_limit': 30000,
              'pwm_pin': 18, 'tach_pin': 23}
    try:
        with mmap.mmap(fd, 4096, flags=mmap.MAP_SHARED, prot=mmap.PROT_READ) as memory:
            def word(offset): return struct.unpack_from('<I', memory, offset)[0]
            offsets = (4, 8, 0xe4, 0xe8)
            before = {str(offset): word(offset) for offset in offsets}
            if (word(4) >> 24) & 7 != 1: raise RuntimeError('GPIO18 is not existing output')
            if (word(8) >> 9) & 7 != 0: raise RuntimeError('GPIO23 is not existing input')
            report['tach_pull_code'] = (word(0xe8) >> 14) & 3
            transitions, gaps = [], deque(maxlen=100000)
            tach_edges = count = 0
            max_gap = 0.0
            started = previous_time = time.monotonic()
            levels = word(0x34)
            last_pwm, last_tach = (levels >> 18) & 1, (levels >> 23) & 1
            while True:
                now = time.monotonic()
                if now - started >= 10: break
                value = word(0x34)
                pwm, tach = (value >> 18) & 1, (value >> 23) & 1
                gap = now - previous_time
                gaps.append(gap); max_gap = max(max_gap, gap); count += 1
                if pwm != last_pwm:
                    transitions.append((now - started, pwm))
                    if len(transitions) > 30000: raise RuntimeError('Transition limit exceeded')
                if last_tach and not tach: tach_edges += 1
                last_pwm, last_tach, previous_time = pwm, tach, now
                if count % 50000 == 0:
                    check_temperature()
                    time.sleep(0)
            after = {str(offset): word(offset) for offset in offsets}
            report.update(elapsed_seconds=time.monotonic() - started, samples=count,
                          pwm_transitions=transitions, tach_falling_edges=tach_edges,
                          poll_gap_median_us=statistics.median(gaps) * 1e6,
                          poll_gap_p99_us=sorted(gaps)[int(.99 * (len(gaps) - 1))] * 1e6,
                          max_poll_gap_us=max_gap * 1e6, quantile_tail_samples=len(gaps),
                          configuration_registers_unchanged=before == after)
    finally:
        os.close(fd)
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    capture()
