#!/usr/bin/env python3
"""Render measured lab scale and current rising-curve hypotheses from evidence."""
import argparse
import csv
import json
from pathlib import Path
from publish_thermal_evidence import normalize_svg


def build(directory):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fleet = json.loads((directory/'fleet-fault-verification-2026-10-07.json').read_text())
    resources = json.loads((directory/'fleet-resource-verification-2026-10-07.json').read_text())
    stages = fleet['stages']
    fig, axes = plt.subplots(1, 3, figsize=(11, 4))
    x = range(len(stages))
    axes[0].bar(x, [s['apply_to_ready_seconds'] for s in stages], color='#3478b9')
    axes[0].set_ylabel('Apply to all CRs Ready (seconds)')
    axes[1].bar(x, [s['status_nearest_rank_p95_seconds']*1000 for s in stages], color='#218b82')
    axes[1].set_ylabel('Status proxy call empirical p95 (ms)')
    for ax in axes[:2]:
        ax.set_xticks(list(x), [str(s['fans'])+' fans\n'+str(s['zones'])+' zones' for s in stages])
        ax.grid(axis='y', alpha=0.2)
    axes[2].bar(['operator', 'worker'], [resources[k]['maximum_sampled_rss_bytes']/1024**2 for k in ('operator','worker')], color=['#ed3158', '#7f63ad'])
    axes[2].set_ylabel('Maximum sampled process RSS (MiB)')
    axes[2].set_title('16 fans / 64 local zones', fontsize=10)
    fig.suptitle('Measured software scale: one simulated actuator and member node', fontweight='bold')
    fig.text(0.5, 0.01, '12 status samples per stage. No electrical PWM, distributed fleet or Prometheus query load acceptance.', ha='center', fontsize=8)
    fig.tight_layout(rect=(0,0.05,1,0.93))
    for suffix in ('.png','.svg'):
        fig.savefig(directory/('fleet-scale-2026-10-07'+suffix), dpi=180)
        if suffix == '.svg':
            normalize_svg(directory/('fleet-scale-2026-10-07'+suffix))
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10,5))
    temperatures = list(range(50,76))
    ax.plot(temperatures, [30+70*(t-50)/25 for t in temperatures], color='#19264d', label='Hypothesis: configured rising curve (50-75 C)')
    palette = ['#3478b9','#7f63ad','#218b82','#e87544','#ed3158','#566276']
    paths = sorted(directory.glob('thermal-fixed-*c-2026-10-07.csv'))
    for index, path in enumerate(paths):
        color = palette[index % len(palette)]
        data = [r for r in csv.DictReader(path.open()) if r['phase']=='load-fixed']
        ax.scatter([float(r['hottest_c']) for r in data], [float(r['requested_duty_percent']) for r in data],
                   s=12, alpha=0.55, color=color, label=path.stem.replace('thermal-fixed-', '').replace('-2026-10-07',''))
    for t in (50,55,60):
        duty = 30+70*(t-50)/25
        ax.plot(t,duty,'o',color='#ed3158')
        ax.annotate(str(t)+' C / '+str(int(duty))+'%',(t,duty),xytext=(7,8),textcoords='offset points',fontsize=9)
    ax.set(xlabel='Hottest observed member (C)', ylabel='Requested duty (%)', ylim=(0,105), xlim=(45,76))
    ax.grid(alpha=0.2)
    ax.legend(fontsize=8,loc='upper left')
    fig.suptitle('Current curve hypothesis and measured load observations',fontweight='bold')
    fig.text(0.5,0.01,'50/55/60 C are observation targets, not controller setpoints. Hysteresis can retain higher duty while cooling.',ha='center',fontsize=8)
    fig.tight_layout(rect=(0,0.035,1,0.94))
    for suffix in ('.png','.svg'):
        fig.savefig(directory/('current-curve-2026-10-07'+suffix),dpi=180)
        if suffix == '.svg':
            normalize_svg(directory/('current-curve-2026-10-07'+suffix))
    plt.close(fig)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path(__file__).resolve().parents[1]/'docs/v1')
    build(parser.parse_args().directory)
