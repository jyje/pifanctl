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


def test_step_controller_matches_the_original_behaviour():
    controller = StepController(target_temperature=50, duty_step=2, initial_duty=10)
    assert controller.update(51) == 12
    assert controller.update(50) == 10
    assert controller.update(20) == 8


def test_step_controller_is_bounded():
    controller = StepController(target_temperature=50, duty_step=60)
    assert controller.update(60) == 60
    assert controller.update(60) == 100
    assert controller.update(10) == 40
    assert controller.update(10) == 0
