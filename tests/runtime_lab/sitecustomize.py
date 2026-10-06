"""Explicit simulated I/O adapter for disposable Kubernetes runtime tests only."""
import json
import os
from pathlib import Path
import sys
import types

if os.environ.get('PIFANCTL_RUNTIME_LAB') != '1':
    os.write(2, b'Runtime lab adapter requires explicit PIFANCTL_RUNTIME_LAB=1\n')
    os._exit(79)

print('PIFANCTL_RUNTIME_LAB: simulated GPIO and thermal input', file=sys.stderr, flush=True)
gpio = types.ModuleType('RPi.GPIO')
gpio.BCM, gpio.OUT, gpio.HIGH = 'BCM', 'OUT', 1

def emit(action, **values):
    print(json.dumps({'runtime_lab_gpio': action, **values}), flush=True)

gpio.setwarnings = lambda value: None
gpio.setmode = lambda value: None
gpio.setup = lambda pin, mode: emit('setup', pin=pin)
gpio.output = lambda pin, value: emit('output', pin=pin, value=value)

class PWM:
    def __init__(self, pin, frequency): self.pin, self.frequency = pin, frequency
    def start(self, duty): emit('start', pin=self.pin, duty=duty, frequency=self.frequency)
    def ChangeDutyCycle(self, duty): emit('duty', pin=self.pin, duty=duty)
    def stop(self): emit('stop', pin=self.pin)

gpio.PWM = PWM
package = types.ModuleType('RPi')
package.GPIO = gpio
sys.modules['RPi'] = package
sys.modules['RPi.GPIO'] = gpio

from pifanctl import thermal

def read_lab_zones(path=thermal.DEFAULT_THERMAL_PATH):
    input_file = Path('/etc/pifanctl/lab-temperature-celsius')
    try:
        value = float(input_file.read_text()) if input_file.exists() else 55.0
    except (OSError, ValueError):
        return []
    return [thermal.Zone('thermal_zone0', 'runtime-lab-synthetic', value)]

thermal.read_zones = read_lab_zones
