"""Rebuild anonymous 5 V RPM acceptance figures from the committed CSV records."""
import csv
import math
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'docs/v1/hardware-verification/rpm-5v'


def read_samples(path):
    with Path(path).open() as stream:
        raw = list(csv.DictReader(stream))
    if not raw:
        raise ValueError('No measured samples')
    fields = ('elapsed_seconds', 'commanded_duty_percent', 'observed_rpm',
              'pulse_count') + tuple('member_%02d_celsius' % i for i in range(1, 5))
    rows = [{field: float(row[field]) for field in fields} for row in raw]
    if any(not math.isfinite(value) for row in rows for value in row.values()):
        raise ValueError('Non-finite measurement')
    seconds = [row['elapsed_seconds'] for row in rows]
    if any(t < 0 for t in seconds) or seconds != sorted(seconds):
        raise ValueError('Elapsed times must increase')
    for row in rows:
        if not 0 <= row['commanded_duty_percent'] <= 100 or row['observed_rpm'] < 0:
            raise ValueError('Invalid duty or RPM')
        if row['pulse_count'] < 0 or not row['pulse_count'].is_integer() or row['observed_rpm'] != row['pulse_count'] * 6:
            raise ValueError('RPM does not match the recorded five-second pulse count')
    return rows


def build():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    rows = read_samples(DATA / 'samples.csv')
    seconds = [row['elapsed_seconds'] for row in rows]
    duty = [row['commanded_duty_percent'] for row in rows]
    rpm = [row['observed_rpm'] for row in rows]
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    fig, axes = plt.subplots(3, 1, figsize=(10, 8), layout='constrained')
    axes[0].step(seconds, duty, where='post', color='#27677c')
    axes[0].set(ylabel='Commanded duty (%)', ylim=(-5, 105), title='A. Requests through one managed worker')
    axes[1].plot(seconds, rpm, '.-', color='#27677c', markersize=3)
    axes[1].set(ylabel='Observed RPM', title='B. GPIO23 tach: two pulses/revolution, five-second window')
    for i in range(1, 5):
        axes[2].plot(seconds, [float(row['member_%02d_celsius' % i]) for row in rows], label='Member %02d' % i)
    axes[2].axhline(55, color='#bd5c31', linestyle='--', label='Trial abort threshold')
    axes[2].set(xlabel='Elapsed time (s)', ylabel='Temperature (C)', title='C. All four members; actual 5 V supply, existing 1 kHz PWM')
    axes[2].legend(fontsize=8, loc='lower right', ncol=3)
    fig.savefig(DATA / 'response.png', dpi=160)
    plt.close(fig)
    print(DATA / 'response.png')


if __name__ == '__main__':
    build()
