import pytest

from pifanctl.drivers import DriverError, MockDriver, SysfsDriver, create_driver
from pifanctl.enum import Drivers


def fake_pwm(tmp_path, chip=0, channel=2):
    chip_dir = tmp_path / f"pwmchip{chip}"
    channel_dir = chip_dir / f"pwm{channel}"
    channel_dir.mkdir(parents=True)
    (chip_dir / "export").write_text("")
    for name in ("period", "duty_cycle", "enable"):
        (channel_dir / name).write_text("")
    return channel_dir


def test_sysfs_programs_period_duty_and_enable(tmp_path):
    channel_dir = fake_pwm(tmp_path)
    driver = SysfsDriver(0, 2, 1000, 25, base_path=str(tmp_path))
    assert (channel_dir / "period").read_text() == "1000000"
    assert (channel_dir / "duty_cycle").read_text() == "250000"
    assert (channel_dir / "enable").read_text() == "1"
    driver.set_duty(100)
    assert (channel_dir / "duty_cycle").read_text() == "1000000"
    driver.set_duty(250)
    assert (channel_dir / "duty_cycle").read_text() == "1000000"
    driver.set_duty(-3)
    assert (channel_dir / "duty_cycle").read_text() == "0"


def test_sysfs_requires_the_pwm_chip(tmp_path):
    with pytest.raises(DriverError, match="PWM overlay"):
        SysfsDriver(0, 2, 1000, 0, base_path=str(tmp_path))


def test_mock_records_the_duty():
    driver = create_driver(Drivers.MOCK, 18, 1000, 0)
    driver.set_duty(42)
    assert driver.duty == 42


def test_auto_never_falls_back_to_the_mock_on_a_pi4():
    # RPi.GPIO is not installed in the test environment, so a real board
    # request must fail instead of silently selecting the mock.
    with pytest.raises(DriverError):
        create_driver(Drivers.AUTO, 18, 1000, 0, model="Raspberry Pi 4 Model B Rev 1.5")


def test_auto_selects_sysfs_on_a_pi5(tmp_path, monkeypatch):
    created = {}

    class Fake(MockDriver):
        name = "sysfs"
        def __init__(self, chip, channel, frequency, initial_duty):
            super().__init__()
            created.update(chip=chip, channel=channel)

    monkeypatch.setattr("pifanctl.drivers.SysfsDriver", Fake)
    driver = create_driver(Drivers.AUTO, 18, 1000, 0, pwm_chip=0, pwm_channel=2,
                           model="Raspberry Pi 5 Model B Rev 1.0")
    assert driver.name == "sysfs" and created == {"chip": 0, "channel": 2}


class FakeGpio:
    """Stands in for RPi.GPIO, which only imports on a Raspberry Pi."""
    BCM, OUT, HIGH = "BCM", "OUT", 1

    def __init__(self):
        self.calls = []
        gpio = self

        class PWM:
            def __init__(self, pin, frequency):
                gpio.calls.append(("PWM", pin, frequency))

            def start(self, duty):
                gpio.calls.append(("start", duty))

            def ChangeDutyCycle(self, duty):
                gpio.calls.append(("duty", duty))
            def stop(self):
                gpio.calls.append(('stop',))

        self.PWM = PWM

    def setwarnings(self, flag):
        self.calls.append(("setwarnings", flag))

    def setmode(self, mode):
        self.calls.append(("setmode", mode))

    def setup(self, pin, direction):
        self.calls.append(("setup", pin, direction))

    def cleanup(self):
        self.calls.append(("cleanup",))
    def output(self, pin, level):
        self.calls.append(('output', pin, level))


@pytest.fixture
def fake_gpio(monkeypatch):
    import sys
    import types

    gpio = FakeGpio()
    package = types.ModuleType("RPi")
    package.GPIO = gpio
    monkeypatch.setitem(sys.modules, "RPi", package)
    monkeypatch.setitem(sys.modules, "RPi.GPIO", gpio)
    return gpio


def test_rpigpio_drives_the_pin_with_the_requested_pwm(fake_gpio):
    from pifanctl.drivers import RpiGpioDriver

    driver = RpiGpioDriver(pin=18, frequency=1000, initial_duty=30)
    driver.set_duty(55)
    assert fake_gpio.calls == [
        ("setwarnings", False), ("setmode", "BCM"), ("setup", 18, "OUT"),
        ("PWM", 18, 1000), ("start", 30), ("duty", 55),
    ]


def test_rpigpio_does_not_release_the_pin_on_close(fake_gpio):
    # cleanup() would float the pin, and a floating pin can stop the fan.
    from pifanctl.drivers import RpiGpioDriver

    driver = RpiGpioDriver(pin=18, frequency=1000, initial_duty=0)
    driver.close()
    assert ("cleanup",) not in fake_gpio.calls


def test_auto_picks_rpigpio_on_a_pi4_when_the_library_works(fake_gpio):
    driver = create_driver(Drivers.AUTO, 18, 1000, 10, model="Raspberry Pi 4 Model B Rev 1.5")
    assert driver.name == "rpigpio"


def test_sysfs_exports_the_channel_when_it_is_missing(tmp_path):
    chip = tmp_path / "pwmchip0"
    chip.mkdir()
    (chip / "export").write_text("")

    # The kernel creates pwm<N> when N is written to export; emulate that.
    import builtins

    real_open = builtins.open

    def fake_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if str(path).endswith("/export") and "w" in mode:
            channel_dir = chip / "pwm2"
            channel_dir.mkdir(exist_ok=True)
            for name in ("period", "duty_cycle", "enable"):
                (channel_dir / name).write_text("")
        return handle

    builtins.open = fake_open
    try:
        driver = SysfsDriver(0, 2, 1000, 50, base_path=str(tmp_path))
    finally:
        builtins.open = real_open
    assert (chip / "export").read_text() == "2"
    assert (chip / "pwm2" / "duty_cycle").read_text() == "500000"
    driver.close()


def test_a_write_failure_is_reported_as_a_driver_error(tmp_path):
    chip = tmp_path / "pwmchip0"
    (chip / "pwm2").mkdir(parents=True)
    # period is a directory, so writing it fails the way a read-only /sys does.
    (chip / "pwm2" / "period").mkdir()
    with pytest.raises(DriverError, match="cannot configure"):
        SysfsDriver(0, 2, 1000, 0, base_path=str(tmp_path))


def test_detect_model_reads_the_device_tree(tmp_path):
    from pifanctl.drivers import detect_model

    model = tmp_path / "model"
    model.write_bytes(b"Raspberry Pi 5 Model B Rev 1.0\x00")
    assert detect_model(str(model)) == "Raspberry Pi 5 Model B Rev 1.0"
    assert detect_model(str(tmp_path / "missing")) == ""
