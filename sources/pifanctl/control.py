from dataclasses import dataclass


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class CurveConfig:
    """
    A temperature-to-duty curve.

    Below ``temp_low`` the fan idles at ``duty_idle``. Between ``temp_low`` and
    ``temp_high`` the duty rises linearly from ``duty_start`` to ``duty_max``.
    At or above ``temp_high`` it stays at ``duty_max``.
    """
    temp_low: float = 50.0
    temp_high: float = 70.0
    duty_idle: float = 0.0
    duty_start: float = 30.0
    duty_max: float = 100.0
    duty_down_step: float = 5.0

    def __post_init__(self):
        if not self.temp_low < self.temp_high:
            raise ValueError(f"temp_low ({self.temp_low}) must be lower than temp_high ({self.temp_high})")
        if not 0 <= self.duty_idle <= self.duty_start <= self.duty_max <= 100:
            raise ValueError("duty values must satisfy 0 <= idle <= start <= max <= 100")
        if self.duty_down_step <= 0:
            raise ValueError("duty_down_step must be positive")


def curve_target(temperature: float, config: CurveConfig) -> float:
    if temperature < config.temp_low:
        return config.duty_idle
    if temperature >= config.temp_high:
        return config.duty_max
    ratio = (temperature - config.temp_low) / (config.temp_high - config.temp_low)
    return config.duty_start + ratio * (config.duty_max - config.duty_start)


class CurveController:
    """
    Follows the curve upwards immediately and comes down in limited steps.

    Rising fast protects the hardware. Falling slowly is the hysteresis: a
    temperature hovering around ``temp_low`` does not toggle the fan on and off
    every interval.
    """

    def __init__(self, config: CurveConfig, initial_duty: float = 0.0):
        self.config = config
        self.duty = _clamp(initial_duty)

    def update(self, temperature: float) -> float:
        target = curve_target(temperature, self.config)
        if target >= self.duty:
            self.duty = target
        else:
            self.duty = max(target, self.duty - self.config.duty_down_step)
        return self.duty

    def force(self, duty: float) -> float:
        self.duty = _clamp(duty)
        return self.duty


class StepController:
    """
    The original pifanctl behaviour: nudge the duty up or down by a fixed step
    depending on which side of the target temperature we are.
    """

    def __init__(self, target_temperature: float, duty_step: float, initial_duty: float = 0.0):
        if duty_step <= 0:
            raise ValueError("duty_step must be positive")
        self.target_temperature = target_temperature
        self.duty_step = duty_step
        self.duty = _clamp(initial_duty)

    def update(self, temperature: float) -> float:
        if temperature > self.target_temperature:
            self.duty = _clamp(self.duty + self.duty_step)
        else:
            self.duty = _clamp(self.duty - self.duty_step)
        return self.duty

    def force(self, duty: float) -> float:
        self.duty = _clamp(duty)
        return self.duty
