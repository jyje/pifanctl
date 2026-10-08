import copy
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from jsonschema import Draft7Validator

API = 'pifanctl.jyje.online/v1'
SUPPORTED_APIS = (API, 'pifanctl.jyje.online/v1alpha1')
GROUP, VERSION = API.split('/')
MAX_BYTES = 900_000
SCHEMAS = json.loads(Path(__file__).with_name('schemas.json').read_text())
NAME = re.compile(r'^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$')
LABEL = re.compile(r'^[A-Za-z0-9]([A-Za-z0-9_.-]*[A-Za-z0-9])?$')


class TopologyError(ValueError):
    pass


class UniqueLoader(yaml.SafeLoader):
    """Reject duplicate mapping keys instead of silently choosing the last one."""


def _mapping(loader, node, deep=False):
    result = {}
    for key, value in node.value:
        key = loader.construct_object(key, deep=deep)
        if not isinstance(key, (str, int, float, bool)) or key in result:
            raise TopologyError('duplicate or non-scalar YAML mapping key')
        result[key] = loader.construct_object(value, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def parse(text):
    if len(text.encode()) > MAX_BYTES:
        raise TopologyError('topology exceeds 900 KB')
    try:
        docs = list(yaml.load_all(text, Loader=UniqueLoader))
    except (yaml.YAMLError, RecursionError) as error:
        raise TopologyError(f'invalid topology YAML: {error}') from error
    items = []
    for doc in docs:
        if not isinstance(doc, dict):
            if doc is None:
                continue
            raise TopologyError('each document must be an object')
        if doc.get('kind') == 'ConfigMap':
            raise TopologyError('extract data.topology.yaml first; do not pass the ConfigMap envelope')
        if doc.get('kind') == 'List':
            if doc.get('apiVersion') != 'v1' or not isinstance(doc.get('items'), list):
                raise TopologyError('List requires apiVersion v1 and an items array')
            items.extend(doc['items'])
        else:
            items.append(doc)
    if not docs or all(d is None for d in docs):
        raise TopologyError('empty topology document')
    return normalize(items)


def load(path):
    return parse(Path(path).read_text())


def defaults(schema, value):
    value = copy.deepcopy(value)
    if isinstance(value, dict):
        for key, prop in schema.get('properties', {}).items():
            if key not in value and 'default' in prop:
                value[key] = copy.deepcopy(prop['default'])
            if key in value:
                value[key] = defaults(prop, value[key])
    return value


def valid_name(value):
    return isinstance(value, str) and len(value) <= 253 and NAME.fullmatch(value) and all(len(p) <= 63 for p in value.split('.'))


def label_key(key):
    if not isinstance(key, str):
        return False
    parts = key.split('/')
    leaf = parts[-1]
    return len(parts) <= 2 and 0 < len(leaf) <= 63 and bool(LABEL.fullmatch(leaf)) and (len(parts) == 1 or valid_name(parts[0]))


def label_value(value):
    return isinstance(value, str) and len(value) <= 63 and (not value or bool(LABEL.fullmatch(value)))


def _plain(value, ancestors=None, depth=0):
    ancestors = ancestors or set()
    if depth > 40 or id(value) in ancestors:
        raise TopologyError('recursive or excessively nested topology')
    if isinstance(value, float) and not math.isfinite(value):
        raise TopologyError('non-finite values are forbidden')
    if isinstance(value, (dict, list)):
        children = value.values() if isinstance(value, dict) else value
        for child in children:
            _plain(child, ancestors | {id(value)}, depth + 1)


def normalize(items):
    if not isinstance(items, list) or len(items) > 2048:
        raise TopologyError('topology permits at most 2048 resources')
    _plain(items)
    result, seen = [], set()
    for raw in items:
        if not isinstance(raw, dict) or raw.get('apiVersion') not in SUPPORTED_APIS or raw.get('kind') not in SCHEMAS:
            raise TopologyError("only " + " or ".join(SUPPORTED_APIS) + " Fan and CoolingZone resources are supported")
        kind = raw['kind']
        metadata = raw.get('metadata', {})
        name = metadata.get('name') if isinstance(metadata, dict) else None
        if not valid_name(name) or metadata.get('namespace'):
            raise TopologyError('resources require a valid cluster-scoped name')
        if (kind, name) in seen:
            raise TopologyError(f'duplicate {kind}/{name}')
        seen.add((kind, name))
        spec = defaults(SCHEMAS[kind], raw.get('spec', {}))
        errors = list(Draft7Validator(SCHEMAS[kind]).iter_errors(spec))
        if errors:
            raise TopologyError(f'{kind}/{name}: {errors[0].message}')
        if kind == 'Fan':
            if not valid_name(spec['nodeName']):
                raise TopologyError('invalid fan nodeName')
            if 'feedback' in spec:
                pin = spec['feedback']['tachometer']['gpio']['pin']
                if 'rpigpio' not in spec['hardware'] or pin == spec['hardware']['rpigpio']['pin']:
                    raise TopologyError('tachometer requires rpigpio and a distinct BCM input pin')
            c = spec['control']['curve']
            hysteresis = c.get('temperatureHysteresis', 5)
            if not c['temperatureLow'] < c['temperatureHigh'] or not 0 <= c['dutyIdle'] <= c['dutyStart'] <= c['dutyMax'] <= 100 or c['dutyDownStep'] <= 0 or not 0 <= hysteresis < c['temperatureHigh'] - c['temperatureLow']:
                raise TopologyError(f'Fan/{name}: invalid control curve')
        else:
            refs = spec['fanRefs']
            if len(refs) != len(set(refs)) or not all(valid_name(n) for n in refs):
                raise TopologyError('fanRefs must be unique valid names')
            if 'nodeNames' in spec:
                names = spec['nodeNames']
                if len(names) != len(set(names)) or not all(valid_name(n) for n in names):
                    raise TopologyError('nodeNames must be unique valid names')
            if 'nodeSelector' in spec:
                sel = spec['nodeSelector']
                if not sel.get('matchLabels') and not sel.get('matchExpressions'):
                    raise TopologyError('empty nodeSelector is forbidden')
                for key, value in sel.get('matchLabels', {}).items():
                    if not label_key(key) or not label_value(value):
                        raise TopologyError('invalid matchLabels')
                for e in sel.get('matchExpressions', []):
                    values = e.get('values', [])
                    if not label_key(e['key']) or not all(label_value(v) for v in values) or len(values) != len(set(values)):
                        raise TopologyError('invalid matchExpressions')
                    if (e['operator'] in ('In', 'NotIn')) != bool(values):
                        raise TopologyError('In/NotIn require values; Exists/DoesNotExist forbid values')
            telemetry = spec['telemetry']
            if telemetry['source'] == 'local':
                if telemetry.get('prometheusURL') or len(spec.get('nodeNames', [])) != 1:
                    raise TopologyError('local source needs exactly one explicit node and no URL')
            else:
                try:
                    url = urlsplit(telemetry.get('prometheusURL', ''))
                    if url.port is not None and url.port <= 0: raise ValueError('invalid port')
                except ValueError as error:
                    raise TopologyError('invalid prometheusURL') from error
                if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.fragment:
                    raise TopologyError('prometheusURL needs an HTTP(S) endpoint without credentials or fragment')
        result.append({**raw, 'apiVersion': API, 'metadata': copy.deepcopy(metadata), 'spec': spec})
    return sorted(result, key=lambda o: (o['kind'], o['metadata']['name']))


def matches(selector, labels):
    if any(labels.get(k) != v for k, v in selector.get('matchLabels', {}).items()):
        return False
    for e in selector.get('matchExpressions', []):
        k, op, values = e['key'], e['operator'], e.get('values', [])
        if op == 'In' and labels.get(k) not in values:
            return False
        if op == 'NotIn' and labels.get(k) in values:
            return False
        if op == 'Exists' and k not in labels or op == 'DoesNotExist' and k in labels:
            return False
    return True


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def bundle(items):
    return {'apiVersion': 'v1', 'kind': 'List', 'items': [{k: o[k] for k in ('apiVersion', 'kind', 'spec')} | {'metadata': {'name': o['metadata']['name']}} for o in items]}
