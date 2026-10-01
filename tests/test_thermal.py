import pytest

from pifanctl.thermal import TemperatureUnavailable, max_temperature, read_zones


def make_zone(root, index, millidegrees, zone_type="cpu-thermal"):
    zone = root / f"thermal_zone{index}"
    zone.mkdir()
    (zone / "temp").write_text(f"{millidegrees}\n")
    (zone / "type").write_text(f"{zone_type}\n")


def test_reads_all_zones(tmp_path):
    make_zone(tmp_path, 0, 48200)
    make_zone(tmp_path, 1, 51100, "gpu-thermal")
    zones = read_zones(str(tmp_path))
    assert [(z.name, z.type, z.celsius) for z in zones] == [
        ("thermal_zone0", "cpu-thermal", 48.2),
        ("thermal_zone1", "gpu-thermal", 51.1),
    ]
    assert max_temperature(zones) == 51.1


def test_skips_unreadable_zone(tmp_path):
    make_zone(tmp_path, 0, 48200)
    broken = tmp_path / "thermal_zone1"
    broken.mkdir()
    (broken / "temp").write_text("not a number")
    zones = read_zones(str(tmp_path))
    assert [z.name for z in zones] == ["thermal_zone0"]


def test_missing_type_is_tolerated(tmp_path):
    zone = tmp_path / "thermal_zone0"
    zone.mkdir()
    (zone / "temp").write_text("40000")
    assert read_zones(str(tmp_path))[0].type == "unknown"


def test_no_zones_raises(tmp_path):
    assert read_zones(str(tmp_path)) == []
    with pytest.raises(TemperatureUnavailable):
        max_temperature([])
