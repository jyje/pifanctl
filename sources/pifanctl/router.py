import logging

from pifanctl.service import (
    get_temperature,
    set_pwm_fan,
    run_pwm_fan,
)

def status(state):
    temperature_array = get_temperature()
    if len(temperature_array) > 0:
        print(f"Current temperature: {max(temperature_array):.3f} °C")
    else:
        print("No temperature data available")


def start(
    state: dict,
    pin: int,
    target_temperature: float,
    pwm_frequency: int,
    pwm_refresh_interval: float,
    duty_cycle_initial: float,
    duty_cycle_step: float,
):
    fan = set_pwm_fan(
        pin = pin,
        pwm_frequency = pwm_frequency,
        duty_cycle_initial = duty_cycle_initial,
    )

    run_pwm_fan(
        fan = fan,
        target_temperature = target_temperature,
        pwm_refresh_interval = pwm_refresh_interval,
        duty_cycle_initial = duty_cycle_initial,
        duty_cycle_step = duty_cycle_step,
    )


def stop(state):
    pass


def enable(state):
    pass


def disable(state):
    pass


def config(state):
    pass
