"""Require sensor-read freshness and complete membership before reducing PWM."""
import json
import math
import re
import time
import urllib.parse
import urllib.request

from pifanctl.thermal import TemperatureUnavailable


def vector(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
        raise TemperatureUnavailable('invalid Prometheus response')
    if payload.get('status') != 'success' or payload.get('data', {}).get('resultType') != 'vector':
        raise TemperatureUnavailable('Prometheus did not return a successful vector')
    result = {}
    for sample in payload['data'].get('result', []):
        if not isinstance(sample, dict) or not isinstance(sample.get('metric'), dict):
            continue
        metric = sample.get('metric', {})
        key = tuple(sorted((k, v) for k, v in metric.items() if k != '__name__'))
        try:
            value = float(sample['value'][1])
            if not math.isfinite(value): continue
        except (KeyError, ValueError, TypeError, IndexError):
            continue
        result[key] = value
    return result


def query(url, expression, timeout=3):
    endpoint = url.rstrip('/') + '/api/v1/query?' + urllib.parse.urlencode({'query': expression})
    try:
        with urllib.request.urlopen(endpoint, timeout=timeout) as response:
            return vector(json.loads(response.read(4_000_000)))
    except (OSError, ValueError, TypeError) as error:
        raise TemperatureUnavailable('Prometheus query failed') from error


def read_members(telemetry, members, local, now=None):
    now = time.time() if now is None else now
    if not members:
        raise TemperatureUnavailable('EmptySelection')
    if telemetry['source'] == 'local':
        return {members[0]: local}
    expression = '|'.join(re.escape(n) for n in sorted(members))
    selector = '{node=~' + json.dumps(expression) + '}'
    temperatures = query(telemetry['prometheusURL'], 'pifanctl_temperature_celsius' + selector)
    timestamps = query(telemetry['prometheusURL'], 'pifanctl_temperature_observed_timestamp_seconds' + selector)
    nodes = {}
    age = telemetry['maxSampleAgeSeconds']
    for key, value in temperatures.items():
        node = dict(key).get('node')
        timestamp = timestamps.get(key)
        if node not in members or timestamp is None or not -5 <= now - timestamp <= age:
            continue
        nodes[node] = max(value, nodes.get(node, value))
    missing = set(members) - nodes.keys()
    if missing:
        raise TemperatureUnavailable('MissingOrStaleTemperature: ' + ','.join(sorted(missing)))
    return nodes


def fan_reading(fan, local, now=None):
    if fan['issues']:
        raise TemperatureUnavailable(','.join(fan['issues']))
    all_nodes = {fan['nodeName']: local}
    zone_readings = {}
    for zone in fan['zones']:
        if zone['issues']:
            raise TemperatureUnavailable(f"{zone['name']}: " + ','.join(zone['issues']))
        nodes = read_members(zone['telemetry'], zone['members'], local, now)
        zone_readings[zone['name']] = max(nodes.values())
        for node, value in nodes.items(): all_nodes[node] = max(value, all_nodes.get(node, value))
    return max(all_nodes.values()), zone_readings, all_nodes
