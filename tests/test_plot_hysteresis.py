from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import plot_hysteresis as figures


def test_the_ramp_goes_up_and_comes_back_to_where_it_started():
    temperatures = figures.ramp_temperatures()
    assert temperatures[0] == pytest.approx(40)
    assert max(temperatures) == pytest.approx(66)
    assert temperatures[-1] == pytest.approx(40)


def test_the_figure_ramp_shows_the_curve_shifted_down_on_the_way_down():
    # The claim written under the ramp figure: rising is identical, and falling
    # keeps the duty until the temperature is the hysteresis below the peak.
    temperatures = figures.ramp_temperatures()
    peak = temperatures.index(max(temperatures))
    plain = figures.ramp_duties(0.0, temperatures)
    held = figures.ramp_duties(figures.HYSTERESIS, temperatures)
    assert plain[: peak + 1] == pytest.approx(held[: peak + 1])
    first_stop = lambda duties: next(i for i in range(peak, len(duties)) if duties[i] == 0)
    gap = temperatures[first_stop(plain)] - temperatures[first_stop(held)]
    assert gap == pytest.approx(figures.HYSTERESIS, abs=0.2)


def test_the_figure_closed_loop_hunts_without_hysteresis_and_settles_with_it():
    _, hunting = figures.closed_loop(0.0)
    temperatures, settled = figures.closed_loop(figures.HYSTERESIS)
    assert figures.switches(hunting) > 50
    assert figures.switches(settled) == 0
    assert max(settled[-60:]) - min(settled[-60:]) < 1
    assert temperatures[-1] < figures.TEMP_LOW


def test_every_label_exists_in_both_languages():
    assert figures.LABELS["en"].keys() == figures.LABELS["ko"].keys()
    assert all(figures.LABELS["ko"].values())


def test_rendering_writes_a_figure_per_language(tmp_path):
    pytest.importorskip("matplotlib")
    written = figures.render(tmp_path)
    assert sorted(path.name for path in written) == [
        "hysteresis-closed-loop-ko.svg",
        "hysteresis-closed-loop.svg",
        "hysteresis-ramp-ko.svg",
        "hysteresis-ramp.svg",
    ]
    assert all(path.read_text().startswith("<?xml") for path in written)
