import csv
from datetime import datetime
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import plot_stable_runtime as figure


def test_public_runtime_summary_is_recomputed_from_actual_clocks():
    with figure.DATA.open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    summary = json.loads(figure.DATA.with_suffix('.json').read_text())
    assert len(rows) == summary['observations']
    assert float(rows[-1]['hold_seconds']) == summary['hold_seconds']
    assert summary['hold_seconds'] >= 120
    member_ages, worker_ages = [], []
    for row in rows:
        now = datetime.fromisoformat(row['observed_at_utc']).timestamp()
        ages = [now - float(row[f'member_{i}_source_timestamp']) for i in range(1, 5)]
        worker_age = now - float(row['worker_heartbeat_timestamp'])
        assert max(ages) == pytest.approx(float(row['max_member_age_seconds']))
        assert worker_age == pytest.approx(float(row['worker_age_seconds']))
        assert 0 <= max(ages) <= 30
        assert 0 <= worker_age <= 15
        member_ages.extend(ages)
        worker_ages.append(worker_age)
    assert max(member_ages) == summary['max_member_age_seconds']
    assert max(worker_ages) == summary['max_worker_age_seconds']
    assert 'nodeName' not in rows[0] and 'nodeUID' not in rows[0]


def test_runtime_figure_reproduces_valid_raster_and_vector(monkeypatch, tmp_path):
    monkeypatch.setattr(figure, 'OUTPUT', tmp_path / 'runtime')
    figure.render()
    svg = (tmp_path / 'runtime.svg').read_bytes()
    assert ET.fromstring(svg).tag.endswith('svg')
    assert (tmp_path / 'runtime.png').read_bytes().startswith(b'\x89PNG\r\n\x1a\n')
    figure.render()
    assert (tmp_path / 'runtime.svg').read_bytes() == svg
