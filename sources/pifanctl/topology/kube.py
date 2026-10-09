"""Bounded requests through the official Kubernetes client. No GPIO imports."""
import re
import ssl
from urllib.parse import quote

from pifanctl.topology.model import API

ROOT = '/apis/' + API
PLURALS = {'Fan': 'fans', 'CoolingZone': 'coolingzones'}

# Python 3.13+ enables VERIFY_X509_STRICT. OpenSSL 85-94 are its RFC 5280 structure
# checks (missing key identifiers, CA without Key Usage, non-critical CA constraints).
STRICT_X509_CODES = frozenset(range(85, 95))
# The official client flattens SSL failures into a status 0 ApiException string, so the
# structured code is lost. Match the OpenSSL wording of the same structure checks.
STRICT_X509_MARKERS = ('key usage extension', 'key identifier', 'not marked critical',
                       'subject alternative name extension', 'requires at least x509v3')
STRICT_TLS_REASON = 'StrictTLSCertificateRejected'
CLUSTER_CA_DOC = 'docs/v1/cluster-ca.md'


class APIError(RuntimeError):
    def __init__(self, status, reason, code=None):
        self.status = status
        # Stable machine-readable reason for failures that need a documented fix.
        self.code = code
        super().__init__(f'Kubernetes API {status}: {reason}')


def strict_tls_detail(error):
    """OpenSSL's message when strict X.509 checks rejected the chain, else None."""
    stack, seen = [error], set()
    while stack:
        item = stack.pop()
        if not isinstance(item, BaseException) or id(item) in seen: continue
        seen.add(id(item))
        if isinstance(item, ssl.SSLCertVerificationError) and item.verify_code in STRICT_X509_CODES:
            return item.verify_message
        stack += [item.__cause__, item.__context__, getattr(item, 'reason', None), *item.args]
    return None


def strict_tls_text(reason):
    match = re.search(r'CERTIFICATE_VERIFY_FAILED\] certificate verify failed: (.+?) \(_ssl', str(reason))
    if match and any(marker in match.group(1).lower() for marker in STRICT_X509_MARKERS):
        return match.group(1)
    return None


def strict_tls_error(detail):
    # The detail is OpenSSL's fixed wording. Verification is never relaxed here.
    return APIError(0, f'{STRICT_TLS_REASON}: strict X.509 verification rejected the Kubernetes API '
                       f'certificate chain ({detail}). Fix the cluster CA or serving certificate; '
                       f'TLS verification stays enabled. See {CLUSTER_CA_DOC}', STRICT_TLS_REASON)


def name(value):
    return quote(value, safe='')


def resource(kind, resource_name=''):
    return ROOT + '/' + PLURALS[kind] + ('/' + name(resource_name) if resource_name else '')


class Kube:
    def __init__(self, kubeconfig=None, context=None, client=None):
        if client is None:
            import os
            from kubernetes import client as kclient, config
            from kubernetes.config.config_exception import ConfigException
            try:
                if not kubeconfig and not context and os.environ.get('KUBERNETES_SERVICE_HOST'):
                    config.load_incluster_config()
                    self.client = kclient.ApiClient()
                else:
                    self.client = config.new_client_from_config(config_file=kubeconfig, context=context)
            except ConfigException:
                raise APIError(0, 'cannot load Kubernetes credentials/context') from None
        else:
            self.client = client

    def request(self, method, path, body=None, query=None, content_type='application/json'):
        from kubernetes.client.exceptions import ApiException
        from urllib3.exceptions import HTTPError
        try:
            return self.client.call_api(
                path, method, body=body, query_params=list((query or {}).items()),
                header_params={'Accept': 'application/json', 'Content-Type': content_type},
                response_types_map={200: 'object', 201: 'object', 202: 'object', 204: None}, auth_settings=['BearerToken'],
                _return_http_data_only=True, _request_timeout=(3, 10))
        except ApiException as error:
            detail = error.status == 0 and strict_tls_text(error.reason)
            if detail: raise strict_tls_error(detail) from None
            # Never echo bodies, kubeconfig contents, bearer tokens or exec output.
            raise APIError(error.status, error.reason) from None
        except HTTPError as error:
            detail = strict_tls_detail(error)
            if detail: raise strict_tls_error(detail) from None
            raise APIError(0, 'transport request failed') from None

    def get(self, path):
        return self.request('GET', path)

    def optional(self, path):
        try: return self.get(path)
        except APIError as error:
            if error.status == 404: return None
            raise

    def items(self, path):
        return self.get(path).get('items', [])

    def patch(self, path, body):
        return self.request('PATCH', path, body, content_type='application/merge-patch+json')

    def apply(self, item, dry_run=False):
        query = {'fieldManager': 'pifanctl-cli', 'force': 'false'}
        if dry_run: query['dryRun'] = 'All'
        return self.request('PATCH', resource(item['kind'], item['metadata']['name']), item,
                            query, 'application/apply-patch+yaml')

    def events(self, kind, resource_version=''):
        from kubernetes import client, watch
        from kubernetes.client.exceptions import ApiException
        stream = watch.Watch()
        try:
            if kind == 'Node':
                method = client.CoreV1Api(self.client).list_node
                args = ()
            else:
                method = client.CustomObjectsApi(self.client).list_cluster_custom_object
                args = (*API.split('/'), PLURALS[kind])
            yield from stream.stream(method, *args, resource_version=resource_version,
                                     timeout_seconds=20, _request_timeout=(3, 25))
        except ApiException as error:
            detail = error.status == 0 and strict_tls_text(error.reason)
            if detail: raise strict_tls_error(detail) from None
            raise APIError(error.status, error.reason) from None
        finally: stream.stop()
