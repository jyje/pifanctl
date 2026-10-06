import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from plot_remaining_acceptance import build


def test_remaining_figures_render_from_declared_scope_and_evidence(tmp_path):
    stages = [{'fans': n, 'zones': n*4, 'apply_to_ready_seconds': 10,
               'status_nearest_rank_p95_seconds': 0.1} for n in (1,4,16)]
    (tmp_path/'fleet-fault-verification-2026-10-07.json').write_text(json.dumps({'stages': stages}))
    (tmp_path/'fleet-resource-verification-2026-10-07.json').write_text(json.dumps({k:{'maximum_sampled_rss_bytes': 1048576} for k in ('operator','worker')}))
    build(tmp_path)
    assert (tmp_path/'fleet-scale-2026-10-07.png').read_bytes().startswith(b'\x89PNG')
    assert 'one simulated actuator' in (tmp_path/'fleet-scale-2026-10-07.svg').read_text()
    assert 'Hypothesis: configured rising curve' in (tmp_path/'current-curve-2026-10-07.svg').read_text()
