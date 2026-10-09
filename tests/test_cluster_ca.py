"""Verify the diagnosed CA defect using generated, non-production certificates."""
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which('openssl') is None, reason='OpenSSL CLI unavailable')
def test_ca_key_usage_is_required_by_strict_chain_verification(tmp_path):
    def openssl(*args, check=True):
        return subprocess.run(['openssl', *args], cwd=tmp_path, text=True,
                              capture_output=True, check=check)

    openssl('genrsa', '-out', 'ca.key', '2048')
    common = ['req', '-new', '-x509', '-key', 'ca.key', '-days', '1',
              '-subj', '/CN=pifanctl test CA',
              '-addext', 'basicConstraints=critical,CA:TRUE',
              '-addext', 'subjectKeyIdentifier=hash']
    openssl(*common, '-out', 'missing-usage.crt')
    openssl(*common, '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
            '-out', 'valid-ca.crt')
    openssl('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'server.key',
            '-out', 'server.csr', '-subj', '/CN=localhost')
    (tmp_path / 'server.ext').write_text(
        'basicConstraints=critical,CA:FALSE\n'
        'keyUsage=critical,digitalSignature,keyEncipherment\n'
        'extendedKeyUsage=serverAuth\nsubjectAltName=DNS:localhost\n'
        'authorityKeyIdentifier=keyid:always\nsubjectKeyIdentifier=hash\n')
    openssl('x509', '-req', '-in', 'server.csr', '-CA', 'valid-ca.crt',
            '-CAkey', 'ca.key', '-CAcreateserial', '-out', 'server.crt',
            '-days', '1', '-extfile', 'server.ext')
    good = openssl('verify', '-x509_strict', '-purpose', 'sslserver',
                   '-verify_hostname', 'localhost', '-CAfile', 'valid-ca.crt',
                   'server.crt')
    assert 'OK' in good.stdout
    bad = openssl('verify', '-x509_strict', '-purpose', 'sslserver',
                  '-verify_hostname', 'localhost', '-CAfile', 'missing-usage.crt',
                  'server.crt', check=False)
    assert bad.returncode != 0
    assert 'CA cert does not include key usage extension' in bad.stderr
