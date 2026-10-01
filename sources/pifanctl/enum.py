from enum import Enum


class _ListableEnum(str, Enum):
    def __str__(self):
        return self.value

    @classmethod
    def list(cls):
        return [member.value for member in cls]


class LogLevels(_ListableEnum):
    """
    Log levels
    """
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Drivers(_ListableEnum):
    """
    How the PWM signal reaches the fan.

    AUTO picks RPIGPIO on Raspberry Pi 4 and older, and SYSFS on Raspberry Pi 5.
    It never picks MOCK, so a misconfigured board fails loudly instead of
    silently leaving the fan uncontrolled.
    """
    AUTO = "auto"
    RPIGPIO = "rpigpio"
    SYSFS = "sysfs"
    MOCK = "mock"


class Sources(_ListableEnum):
    """
    Where the controller reads the temperature it acts on.
    """
    LOCAL = "local"
    PROMETHEUS = "prometheus"


class Algorithms(_ListableEnum):
    """
    How a temperature becomes a duty cycle.
    """
    CURVE = "curve"
    STEP = "step"
