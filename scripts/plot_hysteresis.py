"""
Draws the temperature hysteresis figures used by the documentation.

    uv run --with matplotlib python scripts/plot_hysteresis.py

The data comes from the real `CurveController`, so the figures cannot drift
away from the behaviour that is tested. Only the drawing needs matplotlib,
which is deliberately not a dependency of pifanctl; the data functions are
plain Python and are covered by tests/test_plot_hysteresis.py.

Two situations are drawn, each in English and in Korean:

* ramp: the temperature is moved up and down by hand (open loop), which shows
  the curve a hysteresis shifts on the way down;
* closed loop: a node whose fan cools it below the start temperature, which
  shows the on and off hunting that the hysteresis removes.

The node in the closed loop is a model, not a measurement: with the fan off it
would settle at `OFF_TEMPERATURE`, and each duty percent cools it by
`DEGREES_PER_DUTY` degrees with a first-order lag. The numbers were fitted to a
light-load Raspberry Pi 4 cluster and are only meant to illustrate the effect.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sources"))

from pifanctl.control import CurveConfig, CurveController  # noqa: E402

TEMP_LOW = 50.0
TEMP_HIGH = 75.0
HYSTERESIS = 5.0
DUTY_DOWN_STEP = 5.0  # the chart default, so the figure shows the shipped behaviour

UPDATE_SECONDS = 5  # one controller update every 5 s
OFF_TEMPERATURE = 55.0
DEGREES_PER_DUTY = 0.32
LAG = 0.15
STEPS = 240

# Burgundy, deep teal, pale gray and muted pink, the palette of the project site.
BURGUNDY = "#8b2331"
TEAL = "#1f6f6b"
GRAY = "#9aa0a6"
PINK = "#d9a5b3"
INK = "#2b2b2b"

LABELS = {
    "en": {
        "ramp_title": "Open loop: the temperature rises to 66 °C and falls back",
        "closed_title": "Closed loop: a node that would sit at {off:g} °C without the fan",
        "temperature": "Temperature (°C)",
        "duty": "Fan duty (%)",
        "minutes": "Time (minutes)",
        "start": "start temperature ({low:g} °C)",
        "no_hysteresis": "hysteresis 0",
        "hysteresis": "hysteresis {h:g} °C",
        "stops_late": "stops {h:g} °C later",
        "hunting": "the fan switches on and off",
        "settled": "the fan settles on one duty",
    },
    "ko": {
        "ramp_title": "개루프: 온도가 66 °C까지 올랐다가 내려옵니다",
        "closed_title": "폐루프: 팬이 없으면 {off:g} °C에 머무는 노드",
        "temperature": "온도 (°C)",
        "duty": "팬 듀티 (%)",
        "minutes": "시간 (분)",
        "start": "시작 온도 ({low:g} °C)",
        "no_hysteresis": "히스테리시스 0",
        "hysteresis": "히스테리시스 {h:g} °C",
        "stops_late": "{h:g} °C 늦게 꺼집니다",
        "hunting": "팬이 켜졌다 꺼지기를 반복합니다",
        "settled": "팬이 한 듀티에서 안정됩니다",
    },
}


def curve_config(hysteresis: float) -> CurveConfig:
    return CurveConfig(
        temp_low=TEMP_LOW,
        temp_high=TEMP_HIGH,
        duty_down_step=DUTY_DOWN_STEP,
        temp_hysteresis=hysteresis,
    )


def ramp_temperatures(peak: float = 66.0, start: float = 40.0, step: float = 0.1) -> list[float]:
    """Rises from `start` to `peak` and back, one step per update."""
    count = round((peak - start) / step)
    rising = [start + index * step for index in range(count + 1)]
    return rising + rising[-2::-1]


def ramp_duties(hysteresis: float, temperatures: list[float]) -> list[float]:
    controller = CurveController(curve_config(hysteresis), initial_duty=0)
    return [controller.update(temperature) for temperature in temperatures]


def closed_loop(hysteresis: float, steps: int = STEPS) -> tuple[list[float], list[float]]:
    """A fan and the hottest node it cools: returns (temperatures, duties)."""
    controller = CurveController(curve_config(hysteresis), initial_duty=0)
    temperature = OFF_TEMPERATURE
    temperatures, duties = [], []
    for _ in range(steps):
        duty = controller.update(temperature)
        temperatures.append(temperature)
        duties.append(duty)
        cooled = OFF_TEMPERATURE - DEGREES_PER_DUTY * duty
        temperature += LAG * (cooled - temperature)
    return temperatures, duties


def switches(duties: list[float], threshold: float = 15.0) -> int:
    """How many times the fan goes from running to stopped or back."""
    running = [duty >= threshold for duty in duties]
    return sum(1 for before, after in zip(running, running[1:]) if before != after)


def minutes(count: int) -> list[float]:
    return [index * UPDATE_SECONDS / 60 for index in range(count)]


def render(output: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    matplotlib.rcParams.update({
        "svg.fonttype": "none",  # keep text as text so every viewer picks its own font
        "svg.hashsalt": "pifanctl",  # stable ids, so regenerating gives no diff
        "font.family": ["Noto Sans CJK KR", "Apple SD Gothic Neo", "Malgun Gothic", "DejaVu Sans"],
        "axes.edgecolor": GRAY,
        "axes.labelcolor": INK,
        "text.color": INK,
        "xtick.color": INK,
        "ytick.color": INK,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })

    written = []
    for language, text in LABELS.items():
        suffix = "" if language == "en" else f"-{language}"
        label_none = text["no_hysteresis"]
        label_some = text["hysteresis"].format(h=HYSTERESIS)

        temperatures = ramp_temperatures()
        axis = minutes(len(temperatures))
        figure, (top, bottom) = plt.subplots(
            2, 1, figsize=(8, 6), sharex=True, gridspec_kw={"height_ratios": [1, 1.4]}
        )
        top.plot(axis, temperatures, color=INK)
        top.axhline(TEMP_LOW, color=GRAY, linestyle=":")
        top.text(axis[0], TEMP_LOW + 0.8, text["start"].format(low=TEMP_LOW), ha="left", color=GRAY)
        top.set_ylabel(text["temperature"])
        top.set_title(text["ramp_title"], loc="left")
        bottom.plot(axis, ramp_duties(0.0, temperatures), color=BURGUNDY, label=label_none)
        bottom.plot(axis, ramp_duties(HYSTERESIS, temperatures), color=TEAL, label=label_some)
        bottom.set_ylabel(text["duty"])
        bottom.set_xlabel(text["minutes"])
        bottom.set_ylim(-3, 108)
        bottom.legend(loc="upper right", frameon=False)
        figure.tight_layout()
        path = output / f"hysteresis-ramp{suffix}.svg"
        figure.savefig(path, metadata={"Date": None})
        plt.close(figure)
        written.append(path)

        figure, grid = plt.subplots(2, 2, figsize=(10, 5.6), sharex=True, sharey="row")
        for column, (hysteresis, label, color, note) in enumerate([
            (0.0, label_none, BURGUNDY, text["hunting"]),
            (HYSTERESIS, label_some, TEAL, text["settled"]),
        ]):
            temperatures, duties = closed_loop(hysteresis)
            axis = minutes(len(temperatures))
            grid[0][column].plot(axis, temperatures, color=INK)
            grid[0][column].axhline(TEMP_LOW, color=GRAY, linestyle=":")
            grid[0][column].set_title(f"{label}: {note}", loc="left", color=color)
            grid[1][column].plot(axis, duties, color=color)
            grid[1][column].set_xlabel(text["minutes"])
        grid[0][0].set_ylabel(text["temperature"])
        grid[1][0].set_ylabel(text["duty"])
        figure.suptitle(text["closed_title"].format(off=OFF_TEMPERATURE), x=0.01, ha="left")
        figure.tight_layout()
        path = output / f"hysteresis-closed-loop{suffix}.svg"
        figure.savefig(path, metadata={"Date": None})
        plt.close(figure)
        written.append(path)
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--output", type=Path, default=ROOT / "docs" / "images")
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    for path in render(args.output):
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
