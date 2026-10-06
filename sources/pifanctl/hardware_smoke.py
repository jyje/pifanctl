"""Verify that an unprivileged image refuses unavailable GPIO hardware.

Run only in the image build environment, without GPIO devices or privileges.
A CLI parsing failure must never count as a successful hardware refusal.
"""
from pifanctl.drivers import DriverError, create_driver
from pifanctl.enum import Drivers


def verify_unavailable_gpio():
    try:
        driver = create_driver(Drivers.RPIGPIO, 18, 1000, 100)
    except DriverError as error:
        print(f"Expected hardware refusal: {error}")
        return
    driver.close()
    raise RuntimeError("Image smoke environment unexpectedly provides GPIO hardware")


if __name__ == "__main__":
    verify_unavailable_gpio()
