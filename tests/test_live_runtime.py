from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_live_runtime import telemetry


def series(node, value):
    return {'metric': {'node': node}, 'value': [9999, str(value)]}


def test_member_freshness_uses_source_clock_not_query_evaluation_time():
    values, clocks = [series('pi', 49)], [series('pi', 90)]
    assert telemetry(values, clocks, ['pi'], 100) == ({'pi': 49}, {'pi': 90})
    with pytest.raises(RuntimeError, match='stale'):
        telemetry(values, clocks, ['pi'], 121)


@pytest.mark.parametrize('values,clocks', [
    ([], [series('pi', 99)]), ([series('pi', 49)], []),
    ([series('other', 49)], [series('pi', 99)]),
    ([series('pi', 65)], [series('pi', 99)]),
    ([series('pi', 49)], [series('pi', 101)]),
])
def test_missing_hot_and_future_sources_are_rejected(values, clocks):
    with pytest.raises(RuntimeError):
        telemetry(values, clocks, ['pi'], 100)
