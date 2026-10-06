#!/usr/bin/env python3
"""Build the release acceptance figures and PDF from the checked-in evidence."""

from __future__ import annotations

import csv
import html
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from verify_thermal_acceptance import evaluate

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/v1/release-acceptance.md"
CSV = ROOT / "docs/v1/thermal-load-observations.csv"
STABILITY_CSV = ROOT / "docs/v1/thermal-stability-55c-2026-10-06.csv"
FIGURES = ROOT / "docs/v1/figures"
PDF = ROOT / "docs/v1/release-acceptance.pdf"

INK = "#19264d"
BLUE = "#3478b9"
TEAL = "#218b82"
ORANGE = "#e87544"
PURPLE = "#7f63ad"
GRID = "#d8dee9"
MUTED = "#566276"
PINK = "#ed3158"


def rows():
    with CSV.open(newline="") as stream:
        return list(csv.DictReader(stream))


def stability_rows():
    with STABILITY_CSV.open(newline="") as stream:
        return list(csv.DictReader(stream))


def svg_shell(title, subtitle, width=1440, height=840):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<title>{html.escape(title)}</title>',
        f'<desc>{html.escape(subtitle)}</desc>',
        """<style>
        text{font-family:Arial,sans-serif;fill:#20293a}
        .title{font-size:27px;font-weight:700}.sub{font-size:15px;fill:#566276}
        .tick{font-size:14px;fill:#566276}.label{font-size:16px;font-weight:600}
        .small{font-size:13px;fill:#566276}.legend{font-size:14px}
        </style><rect width="100%" height="100%" fill="#fff"/>""",
        f'<text class="title" x="80" y="48">{html.escape(title)}</text>',
        f'<text class="sub" x="80" y="76">{html.escape(subtitle)}</text>',
    ]


def svg_text(x, y, value, cls="tick", anchor="middle"):
    return f'<text class="{cls}" x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}">{html.escape(str(value))}</text>'


def svg_line(x1, y1, x2, y2, color=GRID, width=1, dash=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{color}" stroke-width="{width}"{d}/>'


def render_svg(name, parts):
    parts.append("</svg>")
    svg_path = FIGURES / f"{name}.svg"
    png_path = FIGURES / f"{name}.png"
    svg_path.write_text("\n".join(parts) + "\n")
    subprocess.run(["rsvg-convert", "--width", "2160", "--output", str(png_path), str(svg_path)], check=True)


def build_measured_figure(data):
    title = "Measured MicroK8s temperature and fan-command response"
    subtitle = "Node CPU thermal sensor samples; Fan resource values are requested commands, not measured RPM or PWM voltage."
    parts = svg_shell(title, subtitle)
    left, top, plot_w, plot_h = 105, 130, 1125, 535
    right = left + plot_w
    bottom = top + plot_h
    temps_min, temps_max = 38.0, 58.0
    duty_min, duty_max = 0.0, 100.0
    times = [datetime.fromisoformat(row["timestamp_utc"].replace("Z", "+00:00")) for row in data]
    t0, t1 = min(times), max(times)
    span = (t1 - t0).total_seconds()

    def x_at(when):
        return left + plot_w * (when - t0).total_seconds() / span

    def y_temp(value):
        return bottom - plot_h * (float(value) - temps_min) / (temps_max - temps_min)

    def y_duty(value):
        return bottom - plot_h * (float(value) - duty_min) / (duty_max - duty_min)

    phase_labels = {
        "load-1cpu": "1 vCPU load",
        "load-2cpu": "2 vCPU load",
        "load-3cpu": "3 vCPU load",
        "cooldown-after-2cpu": "No-load observation",
        "cooldown-after-3cpu": "No-load observation",
    }
    palette = {"load-1cpu": BLUE, "load-2cpu": TEAL, "load-3cpu": ORANGE, "cooldown-after-2cpu": PURPLE, "cooldown-after-3cpu": PURPLE}
    phases = {}
    for row, when in zip(data, times):
        phases.setdefault(row["phase"], []).append((when, row))
    phase_y = 102
    for phase, members in phases.items():
        x1, x2 = x_at(members[0][0]), x_at(members[-1][0])
        if x2 - x1 < 3:
            x2 = x1 + 3
        parts.append(f'<rect x="{x1:.1f}" y="{phase_y}" width="{x2-x1:.1f}" height="10" fill="{palette[phase]}" opacity="0.78"/>')
        parts.append(svg_text((x1 + x2) / 2, phase_y - 7, phase_labels[phase], "small"))

    for value in (40, 45, 50, 55):
        y = y_temp(value)
        parts.append(svg_line(left, y, right, y, GRID, 1))
        parts.append(svg_text(left - 16, y + 5, f"{value}°C", "tick", "end"))
    for value in (0, 20, 40, 60, 80, 100):
        y = y_duty(value)
        parts.append(svg_text(right + 18, y + 5, f"{value}%", "tick", "start"))
    parts.extend([svg_line(left, top, left, bottom, INK, 2), svg_line(left, bottom, right, bottom, INK, 2), svg_line(right, top, right, bottom, INK, 2)])
    parts.append(svg_text(35, top + plot_h / 2, "Temperature", "label"))
    parts[-1] = parts[-1].replace('x="35.0" y="397.5"', 'x="35.0" y="397.5" transform="rotate(-90 35 397.5)"')
    parts.append(svg_text(right + 73, top + plot_h / 2, "Duty command", "label"))
    parts[-1] = parts[-1].replace('x="1303.0" y="397.5"', 'x="1303.0" y="397.5" transform="rotate(-90 1303 397.5)"')

    minute_count = 9
    for minute in range(minute_count + 1):
        when = t0.timestamp() + span * minute / minute_count
        x = left + plot_w * minute / minute_count
        parts.append(svg_line(x, top, x, bottom, "#edf0f5", 1))
        stamp = datetime.fromtimestamp(when, timezone.utc).strftime("%H:%M")
        parts.append(svg_text(x, bottom + 25, stamp, "tick"))

    series = [("raspi-41 test node", "raspi_41_c", BLUE, 2.5)]
    for label, key, color, width in series:
        for members in phases.values():
            points = " ".join(f"{x_at(t):.1f},{y_temp(r[key]):.1f}" for t, r in members)
            parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
            for t, row in members:
                parts.append(f'<circle cx="{x_at(t):.1f}" cy="{y_temp(row[key]):.1f}" r="3" fill="{color}"/>')

    maxima = [max(float(row[k]) for k in ("raspi_40_c", "raspi_41_c", "raspi_50_c", "raspi_51_c")) for row in data]
    for members in phases.values():
        indices = [data.index(row) for _, row in members]
        points = " ".join(f"{x_at(t):.1f},{y_temp(maxima[index]):.1f}" for index, (t, _) in zip(indices, members))
        parts.append(f'<polyline points="{points}" fill="none" stroke="{INK}" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>')
        for index, (t, _) in zip(indices, members):
            parts.append(f'<circle cx="{x_at(t):.1f}" cy="{y_temp(maxima[index]):.1f}" r="3.2" fill="{INK}"/>')

    for members in phases.values():
        points = " ".join(f"{x_at(t):.1f},{y_temp(row['control_c']):.1f}" for t, row in members)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{PURPLE}" stroke-width="2" stroke-dasharray="7 5"/>')
        points = " ".join(f"{x_at(t):.1f},{y_duty(row['duty_percent']):.1f}" for t, row in members)
        parts.append(f'<polyline points="{points}" fill="none" stroke="{PINK}" stroke-width="2.5" stroke-linejoin="round"/>')
        for t, row in members:
            parts.append(f'<circle cx="{x_at(t):.1f}" cy="{y_duty(row["duty_percent"]):.1f}" r="3" fill="{PINK}"/>')

    legend = [
        ("Cluster maximum", INK),
        ("raspi-41, load target", BLUE),
        ("Fan status control temperature", PURPLE),
        ("Fan status requested duty", PINK),
    ]
    lx, ly = 116, 738
    for i, (label, color) in enumerate(legend):
        x = lx + i * 250
        parts.append(svg_line(x, ly, x + 30, ly, color, 4))
        parts.append(svg_text(x + 38, ly + 5, label, "legend", "start"))
    parts.append(svg_text(720, 790, "Max sensor reading: 55.1°C on raspi-51; the loaded node raspi-41 peaked at 50.147°C.", "small"))
    render_svg("thermal-load-response", parts)


def build_curve_figure(data):
    title = "Configured control curve and observed duty commands"
    subtitle = "Hypothesis: linear increase from 30% at 50°C to 100% at 70°C; actual status includes the 5% per-refresh down-step."
    parts = svg_shell(title, subtitle)
    left, top, plot_w, plot_h = 120, 135, 1110, 530
    right, bottom = left + plot_w, top + plot_h

    def x_at(value):
        return left + plot_w * (float(value) - 45) / 27

    def y_at(value):
        return bottom - plot_h * float(value) / 100

    for t in (0, 20, 40, 60, 80, 100):
        y = y_at(t)
        parts.append(svg_line(left, y, right, y, GRID, 1))
        parts.append(svg_text(left - 18, y + 5, f"{t}%", "tick", "end"))
    for t in (45, 50, 55, 60, 65, 70, 72):
        x = x_at(t)
        parts.append(svg_line(x, top, x, bottom, "#edf0f5", 1))
        parts.append(svg_text(x, bottom + 27, f"{t}°C", "tick"))
    parts.extend([svg_line(left, top, left, bottom, INK, 2), svg_line(left, bottom, right, bottom, INK, 2)])
    parts.append(svg_text((left + right) / 2, bottom + 65, "Cooling-zone control temperature", "label"))
    parts.append(svg_text(34, top + plot_h / 2, "Requested duty", "label"))
    parts[-1] = parts[-1].replace('x="34.0" y="400.0"', 'x="34.0" y="400.0" transform="rotate(-90 34 400)"')

    values = [(45, 0), (50, 0), (50, 30), (70, 100), (72, 100)]
    points = " ".join(f"{x_at(x):.1f},{y_at(y):.1f}" for x, y in values)
    parts.append(f'<polyline points="{points}" fill="none" stroke="{BLUE}" stroke-width="4" stroke-linejoin="round"/>')

    for temp, duty in ((50, 30), (55, 47.5), (60, 65), (65, 82.5), (70, 100)):
        x, y = x_at(temp), y_at(duty)
        parts.append(svg_line(x, y, x, bottom, "#adb7c6", 1, "4 4"))
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{BLUE}"/>')
        parts.append(svg_text(x, y - 13, f"{duty:g}%", "small"))

    for row in data:
        x, y = x_at(row["control_c"]), y_at(row["duty_percent"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.2" fill="{PINK}" stroke="#fff" stroke-width="1.2"/>')

    parts.append(svg_line(800, 155, 840, 155, BLUE, 4))
    parts.append(svg_text(850, 160, "Configured steady-state curve", "legend", "start"))
    parts.append(svg_line(800, 184, 840, 184, ORANGE, 4))
    parts.append(svg_text(850, 189, "Observed Fan.status samples", "legend", "start"))
    parts.append(svg_text(800, 230, "Observed range: 48.5–55.1°C / 2.075–47.85%", "small", "start"))
    parts.append(svg_text(800, 254, "No 60°C or higher point was physically reached.", "small", "start"))
    render_svg("thermal-control-curve", parts)


def build_55c_stability_figure(data):
    """Plot the alpha.3 bounded 55 C trial from its timestamped source samples."""
    title = "Measured 55°C shared-rack response"
    subtitle = "Fresh source observations from the v1 worker; requested duty is a command, not measured RPM or PWM voltage."
    parts = svg_shell(title, subtitle)
    left, top, plot_w, plot_h = 120, 135, 1110, 530
    right, bottom = left + plot_w, top + plot_h
    t_min, t_max = 45.0, 60.0
    duty_max = 60.0
    times = [float(row["elapsed_s"]) for row in data]
    e_min, e_max = min(times), max(times)

    def x_at(value):
        return left + plot_w * (float(value) - e_min) / (e_max - e_min)

    def y_temp(value):
        return bottom - plot_h * (float(value) - t_min) / (t_max - t_min)

    def y_duty(value):
        return bottom - plot_h * float(value) / duty_max

    for value in (45, 48, 51, 54, 57, 60):
        y = y_temp(value)
        parts.append(svg_line(left, y, right, y, GRID, 1))
        parts.append(svg_text(left - 18, y + 5, f"{value}°C", "tick", "end"))
    for value in (0, 15, 30, 45, 60):
        y = y_duty(value)
        parts.append(svg_text(right + 38, y + 5, f"{value}%", "tick", "start"))
    for value in (0, 60, 120, 180, 240, 300):
        x = x_at(value)
        parts.append(svg_line(x, top, x, bottom, "#edf0f5", 1))
        parts.append(svg_text(x, bottom + 25, f"{value}s", "tick"))

    load_rows = [row for row in data if row["phase"] == "load-1cpu"]
    cooldown_rows = [row for row in data if row["phase"] == "cooldown"]
    if load_rows and cooldown_rows:
        x0, x1 = x_at(load_rows[0]["elapsed_s"]), x_at(load_rows[-1]["elapsed_s"])
        parts.append(f'<rect x="{x0:.1f}" y="{top}" width="{x1-x0:.1f}" height="{plot_h}" fill="#f8e9df" opacity="0.65"/>')
        parts.append(svg_text((x0+x1)/2, top+22, "1 vCPU capped load", "small"))
    band_top, band_bottom = y_temp(56), y_temp(54)
    parts.append(f'<rect x="{left}" y="{band_top:.1f}" width="{plot_w}" height="{band_bottom-band_top:.1f}" fill="#e6f4f1" opacity="0.8"/>')

    parts.extend([svg_line(left, top, left, bottom, INK, 2), svg_line(left, bottom, right, bottom, INK, 2)])
    parts.append(svg_text((left + right) / 2, bottom + 62, "Elapsed time from first sample", "label"))
    parts.append(svg_text(30, top + plot_h / 2, "Hottest member", "label"))
    parts[-1] = parts[-1].replace(f'x="30.0" y="{top + plot_h / 2:.1f}"', f'x="30.0" y="{top + plot_h / 2:.1f}" transform="rotate(-90 30 {top + plot_h / 2:.1f})"')

    hottest_points = " ".join(f'{x_at(r["elapsed_s"]):.1f},{y_temp(r["hottest_c"]):.1f}' for r in data)
    duty_points = " ".join(f'{x_at(r["elapsed_s"]):.1f},{y_duty(r["requested_duty_percent"]):.1f}' for r in data)
    parts.append(f'<polyline points="{hottest_points}" fill="none" stroke="{BLUE}" stroke-width="3" stroke-linejoin="round"/>')
    parts.append(f'<polyline points="{duty_points}" fill="none" stroke="{PINK}" stroke-width="3" stroke-linejoin="round"/>')
    for row in data:
        parts.append(f'<circle cx="{x_at(row["elapsed_s"]):.1f}" cy="{y_temp(row["hottest_c"]):.1f}" r="2.7" fill="{BLUE}"/>')

    parts.append(svg_line(300, 755, 335, 755, BLUE, 4))
    parts.append(svg_text(345, 760, "Hottest zone member", "legend", "start"))
    parts.append(svg_line(580, 755, 615, 755, PINK, 4))
    parts.append(svg_text(625, 760, "Requested fan duty", "legend", "start"))
    parts.append(f'<rect x="900" y="746" width="22" height="16" fill="#e6f4f1"/>')
    parts.append(svg_text(932, 760, "54–56°C acceptance band", "legend", "start"))
    result = evaluate(data)
    parts.append(svg_text(720, 805,
                          f'Target band: {result["target_band_seconds"]:g}s; 1°C maximum span: {result["strict_stability_seconds"]:g}s; required: 120s. Acceptance remains open.',
                          "small"))
    render_svg("thermal-stability-55c-2026-10-06", parts)


def inline_markup(text):
    value = html.escape(text, quote=False)
    value = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", value)
    value = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="#3478b9">\1</link>', value)
    return value


def build_pdf():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ManualTitle", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=23, leading=28, textColor=colors.HexColor(INK), alignment=TA_LEFT, spaceAfter=8))
    styles.add(ParagraphStyle(name="ManualH1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=colors.HexColor(INK), spaceBefore=10, spaceAfter=8, keepWithNext=True))
    styles.add(ParagraphStyle(name="ManualH2", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=colors.HexColor(PINK), spaceBefore=8, spaceAfter=5, keepWithNext=True))
    styles.add(ParagraphStyle(name="ManualBody", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.8, leading=12, textColor=colors.HexColor("#293345"), spaceAfter=5))
    styles.add(ParagraphStyle(name="ManualSmall", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9, textColor=colors.HexColor(MUTED), spaceAfter=3))
    styles.add(ParagraphStyle(name="ManualBullet", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.4, leading=11, leftIndent=12, firstLineIndent=-8, bulletIndent=0, textColor=colors.HexColor("#293345"), spaceAfter=3))
    styles.add(ParagraphStyle(name="ManualTable", parent=styles["BodyText"], fontName="Helvetica", fontSize=7.1, leading=9, textColor=colors.HexColor("#263145")))
    styles.add(ParagraphStyle(name="ManualTableHead", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=7.2, leading=9, textColor=colors.white))
    styles.add(ParagraphStyle(name="ManualCoverNote", parent=styles["BodyText"], fontName="Helvetica-Bold", fontSize=9, leading=12, textColor=colors.HexColor("#a41d3c"), backColor=colors.HexColor("#fff0f3"), borderColor=colors.HexColor(PINK), borderWidth=0.7, borderPadding=7, spaceBefore=5, spaceAfter=10))

    doc = SimpleDocTemplate(str(PDF), pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=18 * mm, bottomMargin=17 * mm, title="pifanctl v1 Release Acceptance Field Manual", author="pifanctl project", subject="Measured trial and hardware release acceptance")
    available_w = A4[0] - doc.leftMargin - doc.rightMargin
    story = []
    lines = DOC.read_text().splitlines()
    i = 0
    first_title = True
    while i < len(lines):
        line = lines[i].strip()
        if not line or line in ("---", "***"):
            i += 1
            continue
        if line == "<!-- pagebreak -->":
            story.append(PageBreak()); i += 1; continue
        image_match = re.match(r"!\[[^]]*\]\(([^)]+)\)", line)
        if image_match:
            image_path = (DOC.parent / image_match.group(1)).resolve()
            img = Image(str(image_path))
            max_height = 90 * mm if image_path.name == "thermal-live-2026-10-06.png" else 112 * mm
            img._restrictSize(available_w, max_height)
            story.extend([Spacer(1, 3 * mm), img, Spacer(1, 3 * mm)])
            i += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [cell.strip() for cell in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                    table_lines.append(cells)
                i += 1
            maxcols = max(len(row) for row in table_lines)
            normalized = [row + [""] * (maxcols - len(row)) for row in table_lines]
            table_data = []
            for row_no, row in enumerate(normalized):
                sty = styles["ManualTableHead"] if row_no == 0 else styles["ManualTable"]
                table_data.append([Paragraph(inline_markup(cell), sty) for cell in row])
            widths = [available_w / maxcols] * maxcols
            if maxcols == 2:
                widths = [available_w * 0.31, available_w * 0.69]
            elif maxcols == 3:
                widths = [available_w * 0.24, available_w * 0.24, available_w * 0.52]
            table = Table(table_data, colWidths=widths, repeatRows=1, hAlign="LEFT", splitByRow=1)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f0f3f8")]),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c8d1e0")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            story.extend([table, Spacer(1, 3 * mm)])
            continue
        if line.startswith("# "):
            if first_title:
                story.append(Paragraph(inline_markup(line[2:]), styles["ManualTitle"]))
                first_title = False
            else:
                story.append(Paragraph(inline_markup(line[2:]), styles["ManualH1"]))
            i += 1
            continue
        if line.startswith("## "):
            story.append(Paragraph(inline_markup(line[3:]), styles["ManualH1"]))
            i += 1
            continue
        if line.startswith("### "):
            story.append(Paragraph(inline_markup(line[4:]), styles["ManualH2"]))
            i += 1
            continue
        if line.startswith("- ") or re.match(r"\d+\. ", line):
            bullet = "•" if line.startswith("- ") else "•"
            content = line[2:] if line.startswith("- ") else re.sub(r"^\d+\. ", "", line)
            para = Paragraph(f"{bullet}  {inline_markup(content)}", styles["ManualBullet"])
            story.append(para)
            i += 1
            continue
        if line.startswith("**Decision:**"):
            story.append(Paragraph(inline_markup(line), styles["ManualCoverNote"]))
            i += 1
            continue
        paragraph = [line]
        i += 1
        while i < len(lines):
            nxt = lines[i].strip()
            if not nxt or nxt.startswith(("#", "- ", "|", "![")) or re.match(r"\d+\. ", nxt) or nxt == "<!-- pagebreak -->":
                break
            paragraph.append(nxt)
            i += 1
        story.append(Paragraph(inline_markup(" ".join(paragraph)), styles["ManualBody"]))

    def page_furniture(canvas, document):
        canvas.saveState()
        page_w, page_h = A4
        canvas.setFillColor(colors.HexColor(INK))
        canvas.rect(0, page_h - 10 * mm, page_w, 10 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(17 * mm, page_h - 6.7 * mm, "PIFANCTL / V1 RELEASE ACCEPTANCE")
        canvas.setFillColor(colors.HexColor(MUTED))
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(17 * mm, 8 * mm, "FIELD MANUAL  |  UPDATED 2026-10-07  |  MEASURED TRIAL EVIDENCE")
        canvas.drawRightString(page_w - 17 * mm, 8 * mm, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=page_furniture, onLaterPages=page_furniture)


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    data = rows()
    build_measured_figure(data)
    build_curve_figure(data)
    build_55c_stability_figure(stability_rows())
    build_pdf()
    print(f"Wrote {PDF.relative_to(ROOT)} and thermal figures from {len(data)} historical and {len(stability_rows())} 55 C observations.")


if __name__ == "__main__":
    main()
