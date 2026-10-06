import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_storage_migration import identity, rewrite


def item(name='fan-a'):
    return {'apiVersion': 'pifanctl.jyje.online/v1', 'kind': 'Fan',
            'metadata': {'name': name, 'uid': 'uid-' + name, 'generation': 1,
                         'resourceVersion': '1', 'finalizers': ['release']},
            'spec': {'nodeName': 'pi-a'}, 'status': {'ready': False}}


class Fake:
    def __init__(self): self.calls = []; self.conflicts = 0; self.change = None
    def __call__(self, *args, body=None, check=True):
        self.calls.append(args)
        if args[0] == 'replace':
            if self.conflicts:
                self.conflicts -= 1
                return SimpleNamespace(returncode=1, stdout='', stderr='Conflict')
            obj = copy.deepcopy(body)
            if self.change == 'status': obj['status']['ready'] = True
        elif args[0] == 'patch': obj = {}
        elif args[-1].endswith('/fans'): obj = {'items': [item()]}
        else:
            obj = item()
            if self.change == 'identity': obj['metadata']['uid'] = 'replacement'
        return SimpleNamespace(returncode=0, stdout=json.dumps(obj), stderr='')


def test_complete_rewrite_precedes_stored_versions_patch():
    fake = Fake()
    assert rewrite(fake, 'v1', {'fans': [item()]}) == [('fans', 'fan-a')]
    assert [c[0] for c in fake.calls] == ['get', 'replace', 'get', 'patch']
    assert json.loads(fake.calls[-1][-1]) == {'status': {'storedVersions': ['v1']}}


@pytest.mark.parametrize('change', ['identity', 'status'])
def test_changed_identity_or_status_never_clears_storage_history(change):
    fake = Fake(); fake.change = change
    with pytest.raises(RuntimeError, match='changed'):
        rewrite(fake, 'v1', {'fans': [item()]})
    assert not any(c[0] == 'patch' for c in fake.calls)


def test_conflicts_retry_with_fresh_reads():
    fake = Fake(); fake.conflicts = 2
    rewrite(fake, 'v1', {'fans': [item()]})
    assert len([c for c in fake.calls if c[0] == 'replace']) == 3
    assert len([c for c in fake.calls if c[0] == 'get']) == 4


def test_exhausted_conflicts_never_clear_storage_history():
    fake = Fake(); fake.conflicts = 4
    with pytest.raises(RuntimeError, match='rewrite failed'):
        rewrite(fake, 'v1', {'fans': [item()]})
    assert not any(c[0] == 'patch' for c in fake.calls)


def test_added_resource_blocks_storage_history_cleanup():
    fake = Fake()
    def changed(*args, **kwargs):
        result = fake(*args, **kwargs)
        if args[0] == 'get' and args[-1].endswith('/fans'):
            result.stdout = json.dumps({'items': [item(), item('new-fan')]})
        return result
    with pytest.raises(RuntimeError, match='inventory changed'):
        rewrite(changed, 'v1', {'fans': [item()]})
    assert not any(c[0] == 'patch' for c in fake.calls)
