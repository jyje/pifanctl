#!/usr/bin/env python3
"""Reproduce the stable-runtime figure from anonymized acquisition-clock samples."""
import csv
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'docs/releases/1.0.0/stable-runtime.csv'
OUTPUT = DATA.with_suffix('')


def _render():
    with DATA.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    x = [float(r['hold_seconds']) for r in rows]
    fig, axes = plt.subplots(2, 1, figsize=(8, 5.5), sharex=True, constrained_layout=True)
    top, bottom = axes
    top.plot(x, [float(r['hottest_c']) for r in rows], color='#397ab8', label='Hottest member')
    top.set_ylabel('Temperature (C)')
    top.set_ylim(40, 55)
    duty = top.twinx()
    duty.plot(x, [float(r['commanded_duty_percent']) for r in rows], color='#ec2b54', label='Commanded duty')
    duty.set_ylabel('PWM command (%)')
    duty.set_ylim(0, 100)
    top.legend(loc='upper left', frameon=False)
    duty.legend(loc='upper right', frameon=False)
    bottom.plot(x, [float(r['max_member_age_seconds']) for r in rows], color='#397ab8', label='Oldest sensor acquisition')
    bottom.plot(x, [float(r['worker_age_seconds']) for r in rows], color='#188875', label='Worker heartbeat')
    bottom.axhline(30, color='#397ab8', linestyle='--', label='Member age limit: 30 s')
    bottom.axhline(15, color='#188875', linestyle='--', label='Worker age limit: 15 s')
    bottom.set_ylim(0, 35)
    bottom.set_ylabel('Age (s)')
    bottom.set_xlabel('Elapsed observation time (s)')
    bottom.legend(loc='upper center', ncol=2, fontsize=8, frameon=True, facecolor='white', framealpha=1)
    for axis in axes:
        axis.grid(alpha=0.2)
        axis.set_xlim(0, max(x))
    fig.suptitle('Stable v1 runtime: actual sensor clocks\nPWM command is not measured RPM', color='#15213f', fontsize=12)
    for suffix in ('.png', '.svg'):
        path = OUTPUT.with_suffix(suffix)
        fig.savefig(path, dpi=200, metadata={'Date': None} if suffix == '.svg' else None)
        if suffix == '.svg':
            path.write_text('\n'.join(line.rstrip() for line in path.read_text().splitlines()) + '\n')
    plt.close(fig)


def render():
    settings = {**matplotlib.rcParamsDefault, 'backend': 'Agg',
                'svg.hashsalt': 'pifanctl-stable-v1'}
    with matplotlib.rc_context(rc=settings):
        _render()


if __name__ == '__main__':
    render()
