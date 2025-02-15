import logging

from pifanctl.service import get_temperature

def status(state):
    temperature_array = get_temperature()
    if len(temperature_array) > 0:
        print(f"Current temperature: {max(temperature_array):.3f} °C")
    else:
        print("No temperature data available")


def start(state):
    pass


def stop(state):
    pass


def enable(state):
    pass


def disable(state):
    pass


def config(state):
    pass
