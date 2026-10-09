"""Only Kubernetes IO is substituted; client selection/translation is real."""
from unittest.mock import Mock

import pytest
from kubernetes.client import ApiClient
from kubernetes.client.exceptions import ApiException
from kubernetes import watch

from pifanctl.topology.kube import APIError, Kube


def test_optional_returns_existing_object():
    client = Mock()
    client.call_api.return_value = {'metadata': {'name': 'fan-a'}}
    assert Kube(client=client).optional('/existing') == {'metadata': {'name': 'fan-a'}}


@pytest.mark.parametrize('kind', ['Node', 'Fan'])
def test_watch_translates_forbidden_and_stops_stream(monkeypatch, kind):
    stream = Mock()
    stream.stream.side_effect = ApiException(status=403, reason='Forbidden')
    monkeypatch.setattr(watch, 'Watch', lambda: stream)
    with ApiClient() as client:
        with pytest.raises(APIError, match='403: Forbidden'):
            list(Kube(client=client).events(kind))
    stream.stop.assert_called_once()
    method = stream.stream.call_args.args[0]
    assert method.__name__ == ('list_node' if kind == 'Node' else 'list_cluster_custom_object')


def test_items_unwraps_api_list_response():
    client = Mock()
    client.call_api.return_value = {'items': [{'metadata': {'name': 'pi-a'}}]}
    assert Kube(client=client).items('/api/v1/nodes') == [{'metadata': {'name': 'pi-a'}}]
