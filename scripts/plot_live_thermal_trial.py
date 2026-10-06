#!/usr/bin/env python3
"""Render the timestamped 2026-10-06 live thermal-trial CSV as SVG and PNG."""

from __future__ import annotations

import csv
import html
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "docs/v1/thermal-load-observations-2026-10-06.csv"
FIGURE_DIR = ROOT / "docs/v1/figures"
WIDTH, HEIGHT = 1440, 900
INK = "#19264d"
MUTED = "#566276"
GRID = "#d8dee9"
SERIES = {
    "raspi-40": ("raspi_40_c", "#3478b9"),
    "raspi-41": ("raspi_41_c", "#218b82"),
    "raspi-50": ("raspi_50_c", "#e87544"),
    "raspi-51": ("raspi_51_c", "#7f63ad"),
}
STAGE_COLORS = {
    "baseline": "#d8dee9",
    "load-1cpu": "#3478b9",
    "load-2cpu": "#e87544",
    "cooldown": "#218b82",
}
STAGE_LABELS = {
    "baseline": "Baseline",
    "load-1cpu": "1 vCPU load",
    "load-2cpu": "2 vCPU load, stopped at 60°C gate",
    "cooldown": "No-load cooldown",
}


def text(x: float, y: float, value: str, *, size: int = 14, color: str = INK,
         anchor: str = "middle", weight: str = "400") -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" '
        f'font-family="Arial,sans-serif" font-size="{size}" font-weight="{weight}" '
        f'fill="{color}">{html.escape(value)}</text>'
    )


def render() -> tuple[Path, Path]:
    with CSV_PATH.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError(f"No observations found in {CSV_PATH}")

    stamps = [datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")) for row in rows]
    start, end = stamps[0], stamps[-1]
    elapsed = [(stamp - start).total_seconds() for stamp in stamps]
    span = max(elapsed) or 1
    left, top, plot_w, plot_h = 110, 150, 1120, 555
    right, bottom = left + plot_w, top + plot_h
    temp_min, temp_max = 38.0, 66.0
    x_at = lambda seconds: left + plot_w * seconds / span
    y_temp = lambda value: bottom - plot_h * (float(value) - temp_min) / (temp_max - temp_min)
    y_duty = lambda value: bottom - plot_h * float(value) / 100

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
        "<rect width='100%' height='100%' fill='white'/>",
        text(80, 54, "MicroK8s live temperature and fan-command response", size=27, weight="700", anchor="start"),
        text(80, 83, "2026-10-06 | Deployed alpha.2 shared fan | Requested duty is not measured RPM or voltage", size=15, color=MUTED, anchor="start"),
    ]

    # Stage bands use the first and last sample for each stage.
    stage_groups: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        stage_groups.setdefault(row["stage"], []).append(index)
    for stage, indices in stage_groups.items():
        x1, x2 = x_at(elapsed[indices[0]]), x_at(elapsed[indices[-1]])
        if x2 - x1 < 18:
            x2 = x1 + 18
        svg.append(f'<rect x="{x1:.1f}" y="116" width="{x2-x1:.1f}" height="11" fill="{STAGE_COLORS[stage]}" opacity="0.78"/>')
        svg.append(text((x1+x2)/2, 109, STAGE_LABELS[stage], size=12, color=MUTED))

    for value in (40, 45, 50, 55, 60, 65):
        y = y_temp(value)
        svg.extend([f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{GRID}"/>',
                    text(left - 15, y + 5, f"{value}°C", size=13, color=MUTED, anchor="end")])
    for value in range(0, 101, 20):
        y = y_duty(value)
        svg.append(text(right + 18, y + 5, f"{value}%", size=13, color=MUTED, anchor="start"))
    svg.extend([
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="{INK}" stroke-width="2"/>',
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="{INK}" stroke-width="2"/>',
        f'<line x1="{right}" y1="{top}" x2="{right}" y2="{bottom}" stroke="{INK}" stroke-width="2"/>',
        text(28, top + plot_h/2, "Node temperature", size=15, weight="600"),
        text(right + 80, top + plot_h/2, "Requested fan duty", size=15, weight="600"),
    ])
    svg[-2] = svg[-2].replace(f'y="{top + plot_h/2:.1f}"', f'y="{top + plot_h/2:.1f}" transform="rotate(-90 28 {top + plot_h/2:.1f})"')
    svg[-1] = svg[-1].replace(f'y="{top + plot_h/2:.1f}"', f'y="{top + plot_h/2:.1f}" transform="rotate(-90 {right + 80} {top + plot_h/2:.1f})"')

    for minutes in range(0, int(span // 60) + 1):
        sec = min(minutes * 60, span)
        x = x_at(sec)
        svg.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="#edf0f5"/>')
        svg.append(text(x, bottom + 24, f"+{minutes} min", size=12, color=MUTED))

    for value, color, label in ((60, "#e87544", "60°C stage gate"), (65, "#ed3158", "65°C hard abort")):
        y = y_temp(value)
        svg.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="{color}" stroke-width="2" stroke-dasharray="8 6"/>')
        svg.append(text(right - 8, y - 7, label, size=12, color=color, anchor="end", weight="600"))

    for node, (key, color) in SERIES.items():
        points = " ".join(f"{x_at(t):.1f},{y_temp(row[key]):.1f}" for t, row in zip(elapsed, rows))
        svg.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linejoin="round" stroke-linecap="round"/>')
        for t, row in zip(elapsed, rows):
            svg.append(f'<circle cx="{x_at(t):.1f}" cy="{y_temp(row[key]):.1f}" r="2.8" fill="{color}"/>')

    duty_points = " ".join(f"{x_at(t):.1f},{y_duty(row['requested_fan_duty_percent']):.1f}" for t, row in zip(elapsed, rows))
    svg.append(f'<polyline points="{duty_points}" fill="none" stroke="#ed3158" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
    for t, row in zip(elapsed, rows):
        svg.append(f'<circle cx="{x_at(t):.1f}" cy="{y_duty(row["requested_fan_duty_percent"]):.1f}" r="3.2" fill="#ed3158"/>')

    legend = [("raspi-40", SERIES["raspi-40"][1]), ("raspi-41", SERIES["raspi-41"][1]),
              ("raspi-50", SERIES["raspi-50"][1]), ("raspi-51", SERIES["raspi-51"][1]),
              ("Requested duty", "#ed3158")]
    for index, (label, color) in enumerate(legend):
        x = 170 + index * 220
        svg.extend([f'<line x1="{x}" y1="786" x2="{x+32}" y2="786" stroke="{color}" stroke-width="4"/>',
                    text(x+42, 791, label, size=13, color=MUTED, anchor="start")])
    svg.append(text(720, 842, "Peak sample: 61.15°C on raspi-51; load stopped at the 60°C gate. No fan-stop test was run.", size=14, color=INK))
    svg.append("</svg>")

    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    svg_path = FIGURE_DIR / "thermal-live-2026-10-06.svg"
    png_path = FIGURE_DIR / "thermal-live-2026-10-06.png"
    svg_path.write_text("\n".join(svg) + "\n")
    subprocess.run(["rsvg-convert", "--width", "2160", "--output", str(png_path), str(svg_path)], check=True)
    return svg_path, png_path


if __name__ == "__main__":
    svg_file, png_file = render()
    print(f"Wrote {svg_file.relative_to(ROOT)} and {png_file.relative_to(ROOT)}")
