"""Bounded requests through the official Kubernetes client. No GPIO imports."""
from urllib.parse import quote

from pifanctl.topology.model import API

ROOT = '/apis/' + API
PLURALS = {'Fan': 'fans', 'CoolingZone': 'coolingzones'}


class APIError(RuntimeError):
    def __init__(self, status, reason):
        self.status = status
        super().__init__(f'Kubernetes API {status}: {reason}')


def name(value):
    return quote(value, safe='')


def resource(kind, resource_name=''):
    return ROOT + '/' + PLURALS[kind] + ('/' + name(resource_name) if resource_name else '')


class Kube:
    def __init__(self, kubeconfig=None, context=None, client=None):
        if client is None:
            import os
            from kubernetes import client as kclient, config
            if not kubeconfig and not context and os.environ.get('KUBERNETES_SERVICE_HOST'):
                config.load_incluster_config()
                self.client = kclient.ApiClient()
            else:
                self.client = config.new_client_from_config(config_file=kubeconfig, context=context)
        else:
            self.client = client

    def request(self, method, path, body=None, query=None, content_type='application/json'):
        from kubernetes.client.exceptions import ApiException
        try:
            return self.client.call_api(
                path, method, body=body, query_params=list((query or {}).items()),
                header_params={'Accept': 'application/json', 'Content-Type': content_type},
                response_type='object', auth_settings=['BearerToken'],
                _return_http_data_only=True, _request_timeout=(3, 10))
        except ApiException as error:
            # Never echo bodies, kubeconfig contents, bearer tokens or exec output.
            raise APIError(error.status, error.reason) from None

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
        finally: stream.stop()
