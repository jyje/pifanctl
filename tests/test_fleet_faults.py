import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_fleet_faults import expired, fixtures
from pifanctl.topology.model import normalize
from pifanctl.topology.planner import plan


@pytest.mark.parametrize('count', [1, 4, 16])
def test_declared_fleet_has_unique_channels_and_valid_local_zones(count):
    fans, zones = fixtures('node-a', count)
    node = {'metadata': {'name': 'node-a', 'uid': 'uid', 'labels': {}}, 'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    topology = plan(normalize(fans + zones), [node])
    assert len(topology['fans']) == count
    assert len(topology['zones']) == count*4
    assert len({f['spec']['hardware']['rpigpio']['pin'] for f in fans}) == count
    assert all(not f['issues'] for f in topology['fans'].values())
    assert all(not z['issues'] for z in topology['zones'].values())


def test_fixture_bounds_and_failsafe_predicate():
    with pytest.raises(ValueError):
        fixtures('node', 28)
    value = {'ready': False, 'fans': {'a': {'ready': False, 'dutyPercent': 100, 'reason': 'OperatorHeartbeatExpired'}}}
    assert expired(value, ['a'])
    assert not expired(value, ['a', 'b'])
    assert not expired({'ready': True, 'fans': value['fans']}, ['a'])
    value['fans']['a']['dutyPercent'] = 99
    assert not expired(value, ['a'])
