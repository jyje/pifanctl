import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import measure_live_fleet


def test_live_fleet_refuses_existing_evidence_before_api(monkeypatch, tmp_path):
    path = tmp_path/'record.json'
    path.write_text('existing')
    monkeypatch.setattr(sys, 'argv', ['measure', '--report', str(path)])
    monkeypatch.setattr(measure_live_fleet.subprocess, 'check_output', lambda *_a, **_k: pytest.fail('API must not run'))
    with pytest.raises(SystemExit, match='overwrite'):
        measure_live_fleet.main()
    assert path.read_text() == 'existing'


def test_live_fleet_preserves_failed_preflight_and_never_mutates(monkeypatch, tmp_path):
    path = tmp_path/'record.json'
    monkeypatch.setattr(sys, 'argv', ['measure', '--report', str(path)])
    def api(parts, **kwargs):
        assert parts[:3] == ['kubectl', '--context', 'microk8s']
        assert parts[3] == 'get'
        return json.dumps({'spec': {}, 'status': {}})
    monkeypatch.setattr(measure_live_fleet.subprocess, 'check_output', api)
    with pytest.raises(RuntimeError, match='GitOps'):
        measure_live_fleet.main()
    assert not json.loads(path.read_text())['passed']
