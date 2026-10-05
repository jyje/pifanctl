import pytest

from pifanctl.control import CurveConfig, CurveController, StepController, curve_target


@pytest.fixture
def config():
    return CurveConfig(temp_low=50, temp_high=70, duty_idle=0, duty_start=30, duty_max=100, duty_down_step=5)


def test_curve_is_idle_below_low(config):
    assert curve_target(49.9, config) == 0


def test_curve_starts_at_duty_start_on_low(config):
    assert curve_target(50, config) == 30


def test_curve_is_linear_between(config):
    assert curve_target(60, config) == pytest.approx(65)


def test_curve_saturates_at_high(config):
    assert curve_target(70, config) == 100
    assert curve_target(95, config) == 100


def test_controller_rises_immediately(config):
    controller = CurveController(config)
    assert controller.update(70) == 100


def test_controller_falls_in_steps(config):
    controller = CurveController(config, initial_duty=100)
    assert controller.update(40) == 95
    assert controller.update(40) == 90


def test_controller_never_falls_below_target(config):
    controller = CurveController(config, initial_duty=32)
    assert controller.update(50) == 30


def test_hovering_around_low_does_not_toggle(config):
    controller = CurveController(config)
    duties = [controller.update(t) for t in (50.5, 49.5, 50.5, 49.5, 50.5)]
    assert min(duties[1:]) > 20


def test_force_clamps(config):
    controller = CurveController(config)
    assert controller.force(250) == 100
    assert controller.force(-5) == 0


@pytest.mark.parametrize("kwargs", [
    {"temp_low": 70, "temp_high": 50},
    {"temp_low": 50, "temp_high": 50},
    {"duty_idle": 40, "duty_start": 30},
    {"duty_max": 120},
    {"duty_down_step": 0},
])
def test_invalid_curve_is_rejected(kwargs):
    with pytest.raises(ValueError):
        CurveConfig(**kwargs)


def test_step_controller_is_bounded():
    controller = StepController(target_temperature=50, duty_step=60)
    assert controller.update(60) == 60
    assert controller.update(60) == 100
    assert controller.update(10) == 40
    assert controller.update(10) == 0


# --- temperature hysteresis -------------------------------------------------

def hysteresis_config(hysteresis=5.0):
    return CurveConfig(temp_low=50, temp_high=75, duty_idle=0, duty_start=30, duty_max=100,
                       duty_down_step=100, temp_hysteresis=hysteresis)


def test_the_fan_keeps_running_until_the_temperature_is_hysteresis_below_the_start():
    controller = CurveController(hysteresis_config(), initial_duty=0)
    assert controller.update(50.2) == pytest.approx(30.56)
    # Falling back under the start temperature does not stop it ...
    for temperature in (49.9, 48.0, 46.0, 45.2):
        assert controller.update(temperature) == pytest.approx(30.56)
    # ... it stops once the temperature is a full hysteresis under it.
    assert controller.update(44.9) == 0


def test_after_a_peak_the_duty_follows_the_curve_shifted_down_by_the_hysteresis():
    controller = CurveController(hysteresis_config(), initial_duty=0)
    controller.update(60)
    assert controller.update(58) == pytest.approx(curve_target(60, hysteresis_config()))
    assert controller.update(55.1) == pytest.approx(curve_target(60, hysteresis_config()))
    assert controller.update(54) == pytest.approx(curve_target(59, hysteresis_config()))
    assert controller.update(50) == pytest.approx(curve_target(55, hysteresis_config()))


def test_rising_temperature_is_never_delayed():
    controller = CurveController(hysteresis_config(), initial_duty=0)
    controller.update(60)
    controller.update(52)  # falling, held
    assert controller.update(70) == pytest.approx(curve_target(70, hysteresis_config()))


def test_zero_hysteresis_keeps_the_previous_behaviour():
    controller = CurveController(hysteresis_config(0), initial_duty=0)
    controller.update(60)
    assert controller.update(49.9) == 0  # drops with the curve straight away


def test_forcing_the_duty_does_not_lose_the_hysteresis():
    # The v1 worker calls force() between updates, so it must not reset the state.
    controller = CurveController(hysteresis_config(), initial_duty=0)
    controller.update(60)
    controller.force(100)
    assert controller.update(57) == pytest.approx(curve_target(60, hysteresis_config()))


@pytest.mark.parametrize("hysteresis", [-1, 25, 30])
def test_hysteresis_must_be_positive_and_smaller_than_the_curve(hysteresis):
    with pytest.raises(ValueError, match="temp_hysteresis"):
        hysteresis_config(hysteresis)


def simulate(hysteresis, off_temperature, steps=400, degrees_per_duty=0.32, lag=0.15):
    """
    A fan and the hottest node it cools.

    ``off_temperature`` is where the node settles with the fan off. Cooling
    lowers the temperature in proportion to the duty, with a first-order lag.
    """
    controller = CurveController(hysteresis_config(hysteresis), initial_duty=0)
    temperature, duties = off_temperature, []
    for _ in range(steps):
        duty = controller.update(temperature)
        duties.append(duty)
        temperature += lag * ((off_temperature - degrees_per_duty * duty) - temperature)
    return duties


def switches(duties, threshold=15):
    running = [duty >= threshold for duty in duties]
    return sum(1 for before, after in zip(running, running[1:]) if before != after)


def test_hysteresis_stops_the_fan_from_hunting_around_the_start_temperature():
    # Without the fan the node would sit at 55 C, so the fan comes on, cools it
    # under 50 C, switches off, and the node heats up again. Without hysteresis
    # that repeats forever; with it the fan settles on one duty.
    assert switches(simulate(0.0, 55)) > 50
    settled = simulate(5.0, 55)
    assert switches(settled) == 0
    assert max(settled[-100:]) - min(settled[-100:]) < 1


def test_hysteresis_slows_the_unavoidable_cycle_when_the_node_runs_just_above_the_start():
    # At 52 C the fan cooling pulls the node under the stop temperature, so some
    # cycling is inherent. The hysteresis band makes each cycle longer.
    assert switches(simulate(5.0, 52)) < switches(simulate(0.0, 52))


def test_a_cool_node_never_starts_the_fan():
    assert max(simulate(5.0, 45)) == 0
