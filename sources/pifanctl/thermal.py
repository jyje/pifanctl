import glob
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

DEFAULT_THERMAL_PATH = "/sys/class/thermal"


class TemperatureUnavailable(Exception):
    """No usable temperature could be obtained from a source."""


@dataclass(frozen=True)
class Zone:
    name: str
    type: str
    celsius: float


def _read_text(path: str) -> str:
    with open(path, "r") as file:
        return file.read().strip()


def read_zones(thermal_path: str = DEFAULT_THERMAL_PATH) -> list[Zone]:
    """
    Read every thermal zone under ``thermal_path``.

    A zone that cannot be read is skipped rather than failing the whole read:
    some boards expose zones that return EINVAL/ENODATA, and one broken zone
    must not hide the others.
    """
    zones = []
    for temp_path in sorted(glob.glob(os.path.join(thermal_path, "thermal_zone*", "temp"))):
        zone_dir = os.path.dirname(temp_path)
        name = os.path.basename(zone_dir)
        try:
            celsius = float(_read_text(temp_path)) / 1000
        except (OSError, ValueError) as e:
            logger.debug(f"Skipping unreadable thermal zone {name}: {e}")
            continue
        try:
            zone_type = _read_text(os.path.join(zone_dir, "type"))
        except OSError:
            zone_type = "unknown"
        logger.debug(f"Temperature reading from {temp_path}: {celsius}°C")
        zones.append(Zone(name=name, type=zone_type, celsius=celsius))
    return zones


def max_temperature(zones: list[Zone]) -> float:
    if not zones:
        raise TemperatureUnavailable("no readable thermal zone")
    return max(zone.celsius for zone in zones)
