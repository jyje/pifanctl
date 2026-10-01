import logging
import os
from typing import Optional, Protocol

from pifanctl.enum import Drivers

logger = logging.getLogger(__name__)


class DriverError(Exception):
    """The requested PWM driver cannot be used on this machine."""


class PwmDriver(Protocol):
    name: str

    def set_duty(self, duty: float) -> None: ...

    def close(self) -> None: ...


class MockDriver:
    """Records the duty and touches no hardware. Only for tests and development."""
    name = "mock"

    def __init__(self):
        self.duty: Optional[float] = None

    def set_duty(self, duty: float) -> None:
        self.duty = duty

    def close(self) -> None:
        pass


class RpiGpioDriver:
    """Software PWM through RPi.GPIO. Works on Raspberry Pi 4 and older."""
    name = "rpigpio"

    def __init__(self, pin: int, frequency: int, initial_duty: float):
        try:
            import RPi.GPIO as GPIO
        except Exception as e:
            raise DriverError(f"RPi.GPIO is not usable here: {e}") from e
        self._gpio = GPIO
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(pin, GPIO.OUT)
        self._pin = pin
        self._pwm = GPIO.PWM(pin, frequency)
        self._pwm.start(initial_duty)

    def set_duty(self, duty: float) -> None:
        self._pwm.ChangeDutyCycle(duty)

    def close(self) -> None:
        # Leave the pin driven by the caller's last set_duty(); cleanup() would
        # float the pin and could stop the fan.
        pass


class SysfsDriver:
    """
    Kernel hardware PWM through /sys/class/pwm. Works on Raspberry Pi 4 and 5
    once the pwm overlay is enabled (``dtoverlay=pwm,pin=<pin>,func=<alt>``),
    and needs no Python GPIO library.
    """
    name = "sysfs"

    def __init__(self, chip: int, channel: int, frequency: int, initial_duty: float,
                 base_path: str = "/sys/class/pwm"):
        self._chip_path = os.path.join(base_path, f"pwmchip{chip}")
        self._path = os.path.join(self._chip_path, f"pwm{channel}")
        if not os.path.isdir(self._chip_path):
            raise DriverError(
                f"{self._chip_path} does not exist; enable the PWM overlay in config.txt "
                "(for example dtoverlay=pwm-2chan) and mount /sys read-write"
            )
        try:
            if not os.path.isdir(self._path):
                self._write(os.path.join(self._chip_path, "export"), str(channel))
            self._period_ns = int(1e9 / frequency)
            self._write(os.path.join(self._path, "period"), str(self._period_ns))
            self.set_duty(initial_duty)
            self._write(os.path.join(self._path, "enable"), "1")
        except OSError as e:
            raise DriverError(f"cannot configure {self._path}: {e}") from e

    @staticmethod
    def _write(path: str, value: str) -> None:
        with open(path, "w") as file:
            file.write(value)

    def set_duty(self, duty: float) -> None:
        duty_ns = int(self._period_ns * max(0.0, min(100.0, duty)) / 100)
        self._write(os.path.join(self._path, "duty_cycle"), str(duty_ns))

    def close(self) -> None:
        pass


def detect_model(path: str = "/proc/device-tree/model") -> str:
    try:
        with open(path, "rb") as file:
            return file.read().decode("utf-8", "ignore").strip("\x00\n ")
    except OSError:
        return ""


def create_driver(
    driver: Drivers,
    pin: int,
    frequency: int,
    initial_duty: float,
    pwm_chip: int = 0,
    pwm_channel: int = 2,
    model: Optional[str] = None,
) -> PwmDriver:
    """
    Build the requested driver.

    AUTO prefers sysfs on a Raspberry Pi 5, where RPi.GPIO does not work, and
    RPi.GPIO elsewhere. It never falls back to the mock: if the real driver
    cannot start, the controller must stop instead of pretending to cool.
    """
    if driver == Drivers.MOCK:
        logger.warning("Mock driver selected: no fan will be driven")
        return MockDriver()
    if driver == Drivers.RPIGPIO:
        return RpiGpioDriver(pin, frequency, initial_duty)
    if driver == Drivers.SYSFS:
        return SysfsDriver(pwm_chip, pwm_channel, frequency, initial_duty)

    model = detect_model() if model is None else model
    if "Raspberry Pi 5" in model or "Compute Module 5" in model:
        logger.info(f"Detected '{model}', using the sysfs PWM driver")
        return SysfsDriver(pwm_chip, pwm_channel, frequency, initial_duty)
    logger.info(f"Detected '{model or 'unknown board'}', using the RPi.GPIO driver")
    return RpiGpioDriver(pin, frequency, initial_duty)
