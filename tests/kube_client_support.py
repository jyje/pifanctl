"""Stand-ins for the kubernetes 37 ApiClient request pipeline: serialize, send, deserialize."""
from types import SimpleNamespace
from unittest.mock import Mock


def mock_client(data=None):
    client = Mock()
    client.param_serialize.return_value = ('GET', '/x', {}, None, None)
    client.response_deserialize.return_value = SimpleNamespace(data=data)
    return client
