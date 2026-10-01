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
