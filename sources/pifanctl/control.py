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

    ``temp_hysteresis`` is how far the temperature must fall below its highest
    recent value before the duty follows it down. While the temperature is
    rising the curve applies as written. While it is falling the same curve is
    used shifted down by ``temp_hysteresis``: with the defaults the fan starts
    at 50 C but only stops once the temperature is back under 45 C. This is the
    5 C hysteresis of the official Raspberry Pi 5 fan. ``0`` turns it off.
    """
    temp_low: float = 50.0
    temp_high: float = 70.0
    duty_idle: float = 0.0
    duty_start: float = 30.0
    duty_max: float = 100.0
    duty_down_step: float = 5.0
    temp_hysteresis: float = 5.0

    def __post_init__(self):
        if not self.temp_low < self.temp_high:
            raise ValueError(f"temp_low ({self.temp_low}) must be lower than temp_high ({self.temp_high})")
        if not 0 <= self.duty_idle <= self.duty_start <= self.duty_max <= 100:
            raise ValueError("duty values must satisfy 0 <= idle <= start <= max <= 100")
        if self.duty_down_step <= 0:
            raise ValueError("duty_down_step must be positive")
        if not 0 <= self.temp_hysteresis < self.temp_high - self.temp_low:
            raise ValueError(
                f"temp_hysteresis ({self.temp_hysteresis}) must be at least 0 and below the "
                f"curve width ({self.temp_high - self.temp_low})"
            )


def curve_target(temperature: float, config: CurveConfig) -> float:
    if temperature < config.temp_low:
        return config.duty_idle
    if temperature >= config.temp_high:
        return config.duty_max
    ratio = (temperature - config.temp_low) / (config.temp_high - config.temp_low)
    return config.duty_start + ratio * (config.duty_max - config.duty_start)


class CurveController:
    """
    Follows the curve upwards immediately and comes down in two ways.

    Temperature hysteresis decides *when* the duty may fall: after a peak, the
    duty keeps its value until the temperature has dropped ``temp_hysteresis``
    below that peak, then follows the curve shifted down by the same amount.
    Without it a fan whose own cooling pulls the temperature back under
    ``temp_low`` switches off, the temperature climbs over ``temp_low`` again,
    and the fan switches on, over and over.

    ``duty_down_step`` decides *how fast* it falls: the duty comes down in
    limited steps, so a drop in temperature never produces an abrupt change.
    """

    def __init__(self, config: CurveConfig, initial_duty: float = 0.0):
        self.config = config
        self.duty = _clamp(initial_duty)
        # The temperature the curve is evaluated at: the highest value seen
        # recently, relaxed downwards only by the hysteresis.
        self._held: float | None = None

    def _hold(self, temperature: float) -> float:
        held = self._held
        if held is None or temperature >= held:
            held = temperature
        elif temperature < held - self.config.temp_hysteresis:
            held = temperature + self.config.temp_hysteresis
        self._held = held
        return held

    def update(self, temperature: float) -> float:
        target = curve_target(self._hold(temperature), self.config)
        if target >= self.duty:
            self.duty = target
        else:
            self.duty = max(target, self.duty - self.config.duty_down_step)
        return self.duty

    def force(self, duty: float) -> float:
        # Only the duty is overridden. The held temperature stays, because
        # callers use this between updates and must not lose the hysteresis.
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
