"""Strict TLS rejection is reported with a typed, documented reason.

The handshake tests use generated, non-production certificates and the real
Kubernetes client. Only the server socket is local."""
import json
import logging
import shutil
import socket
import ssl
import subprocess
import threading
from unittest.mock import Mock

import pytest
from kubernetes import client as kclient
from urllib3.exceptions import MaxRetryError, SSLError

from pifanctl.topology import operator as op
from pifanctl.topology.kube import (
    CLUSTER_CA_DOC, STRICT_TLS_REASON, APIError, Kube, strict_tls_detail, strict_tls_text)

pytestmark = pytest.mark.skipif(shutil.which('openssl') is None, reason='OpenSSL CLI unavailable')


def openssl(cwd, *args):
    return subprocess.run(['openssl', *args], cwd=cwd, text=True, capture_output=True, check=True)


def make_chain(path, with_key_usage):
    """CA (with or without Key Usage) and a strict-valid server certificate for localhost."""
    openssl(path, 'genrsa', '-out', 'ca.key', '2048')
    ca = ['req', '-new', '-x509', '-key', 'ca.key', '-days', '1', '-subj', '/CN=pifanctl test CA',
          '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'subjectKeyIdentifier=hash']
    if with_key_usage: ca += ['-addext', 'keyUsage=critical,keyCertSign,cRLSign']
    openssl(path, *ca, '-out', 'ca.crt')
    openssl(path, 'req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'server.key',
            '-out', 'server.csr', '-subj', '/CN=localhost')
    (path / 'server.ext').write_text(
        'basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n'
        'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n'
        'authorityKeyIdentifier=keyid:always\nsubjectKeyIdentifier=hash\n')
    openssl(path, 'x509', '-req', '-in', 'server.csr', '-CA', 'ca.crt', '-CAkey', 'ca.key',
            '-CAcreateserial', '-out', 'server.crt', '-days', '1', '-extfile', 'server.ext')


@pytest.fixture
def api_server(tmp_path):
    """TLS server that answers one /version request per connection until closed."""
    def start(directory):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(directory / 'server.crt', directory / 'server.key')
        listener = socket.socket()
        listener.bind(('127.0.0.1', 0)); listener.listen(5); listener.settimeout(0.2)
        stop = threading.Event()
        def serve():
            while not stop.is_set():
                try: raw, _ = listener.accept()
                except OSError: continue
                try:
                    with context.wrap_socket(raw, server_side=True) as conn:
                        conn.recv(4096)
                        body = json.dumps({'gitVersion': 'v-test'}).encode()
                        conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                                     b'Connection: close\r\nContent-Length: %d\r\n\r\n' % len(body) + body)
                except (ssl.SSLError, OSError): pass
        thread = threading.Thread(target=serve, daemon=True); thread.start()
        def close():
            stop.set(); thread.join(2); listener.close()
        return listener.getsockname()[1], close
    return start


def real_client(port, ca_file):
    config = kclient.Configuration()
    config.host = f'https://localhost:{port}'
    config.ssl_ca_cert = str(ca_file)
    config.verify_ssl = True
    return kclient.ApiClient(config)


def test_ca_without_key_usage_is_reported_with_a_typed_documented_reason(tmp_path, api_server):
    make_chain(tmp_path, with_key_usage=False)
    port, close = api_server(tmp_path)
    try:
        with pytest.raises(APIError) as caught:
            Kube(client=real_client(port, tmp_path / 'ca.crt')).get('/version')
    finally: close()
    error = caught.value
    assert error.code == STRICT_TLS_REASON and error.status == 0
    message = str(error)
    assert 'key usage extension' in message
    assert CLUSTER_CA_DOC in message and 'verification stays enabled' in message


def test_ca_with_key_usage_connects_with_strict_verification(tmp_path, api_server):
    make_chain(tmp_path, with_key_usage=True)
    port, close = api_server(tmp_path)
    try:
        assert Kube(client=real_client(port, tmp_path / 'ca.crt')).get('/version') == {'gitVersion': 'v-test'}
    finally: close()


def test_untrusted_issuer_keeps_the_generic_failure(tmp_path, api_server):
    server_dir, other_dir = tmp_path / 'server', tmp_path / 'other'
    server_dir.mkdir(); other_dir.mkdir()
    make_chain(server_dir, with_key_usage=True); make_chain(other_dir, with_key_usage=True)
    port, close = api_server(server_dir)
    try:
        with pytest.raises(APIError) as caught:
            Kube(client=real_client(port, other_dir / 'ca.crt')).get('/version')
    finally: close()
    assert caught.value.code is None
    assert STRICT_TLS_REASON not in str(caught.value)


def verification_error(code, message):
    error = ssl.SSLCertVerificationError(1, f'[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: {message}')
    error.verify_code, error.verify_message = code, message
    return error


def test_transport_chain_is_classified_by_verification_code():
    cause = verification_error(92, 'CA cert does not include key usage extension')
    wrapped = MaxRetryError(None, '/version', SSLError(cause))
    assert strict_tls_detail(wrapped) == 'CA cert does not include key usage extension'
    assert strict_tls_detail(MaxRetryError(None, '/version', SSLError(verification_error(18, 'self-signed')))) is None
    assert strict_tls_detail(MaxRetryError(None, '/version', None)) is None


def test_transport_failure_is_translated_to_the_typed_error():
    cause = verification_error(85, 'Missing Authority Key Identifier')
    client = Mock()
    client.call_api.side_effect = MaxRetryError(None, '/version', SSLError(cause))
    with pytest.raises(APIError) as caught:
        Kube(client=client).get('/version')
    assert caught.value.code == STRICT_TLS_REASON and 'Missing Authority Key Identifier' in str(caught.value)
    client.call_api.side_effect = MaxRetryError(None, '/version', None)
    with pytest.raises(APIError, match='transport request failed') as caught:
        Kube(client=client).get('/version')
    assert caught.value.code is None


@pytest.mark.parametrize('text,expected', [
    ('SSLError\n... [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: CA cert does not include key usage extension (_ssl.c:1032)',
     'CA cert does not include key usage extension'),
    ('SSLError\n... [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Missing Authority Key Identifier (_ssl.c:1032)',
     'Missing Authority Key Identifier'),
    ('SSLError\n... [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: certificate has expired (_ssl.c:1032)', None),
    ('SSLError\n... [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: unable to get local issuer certificate (_ssl.c:1032)', None),
    ('connection refused', None)])
def test_flattened_client_message_is_classified_without_relaxing_checks(text, expected):
    assert strict_tls_text(text) == expected


def test_operator_logs_the_actionable_reason_for_documented_failures(monkeypatch, caplog):
    class Stop:
        def __init__(self): self.flag = False
        def is_set(self): return self.flag
        def set(self): self.flag = True
        def wait(self, timeout): return True
        def clear(self): pass
    stop = Stop()
    operator = Mock()
    def reconcile():
        stop.set()
        raise APIError(0, 'StrictTLSCertificateRejected: rejected', STRICT_TLS_REASON)
    operator.reconcile = reconcile
    operator.input_configmap = True
    monkeypatch.setattr(op, 'install_stop_handlers', lambda event: None)
    monkeypatch.setattr(op.threading, 'Thread', lambda *a, **k: Mock())
    with caplog.at_level(logging.ERROR):
        op.run_operator(operator, stop, port=0)
    assert STRICT_TLS_REASON in caplog.text and not operator.ready


def test_watch_reports_strict_tls_rejection_and_stops_the_stream(monkeypatch):
    from kubernetes import watch
    from kubernetes.client.exceptions import ApiException
    flattened = ('SSLError\nHTTPSConnectionPool: Max retries exceeded (Caused by SSLError(SSLCertVerificationError('
                 "1, '[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: CA cert does not include "
                 "key usage extension (_ssl.c:1032)')))")
    stream = Mock()
    stream.stream.side_effect = ApiException(status=0, reason=flattened)
    monkeypatch.setattr(watch, 'Watch', lambda: stream)
    with pytest.raises(APIError) as caught:
        list(Kube(client=kclient.ApiClient()).events('Fan'))
    assert caught.value.code == STRICT_TLS_REASON
    stream.stop.assert_called_once()
