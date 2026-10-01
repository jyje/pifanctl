import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional

from pifanctl.thermal import TemperatureUnavailable, max_temperature, read_zones

logger = logging.getLogger(__name__)

DEFAULT_PROMETHEUS_QUERY = "max(pifanctl_temperature_celsius)"


class LocalSource:
    """The hottest thermal zone of the node this process runs on."""

    def __init__(self, thermal_path: str):
        self.thermal_path = thermal_path

    def read(self) -> float:
        return max_temperature(read_zones(self.thermal_path))


class PrometheusSource:
    """
    The result of an instant query, typically the hottest node of a cluster.

    Only the standard HTTP API is used, so any Prometheus-compatible endpoint
    works (Prometheus, Thanos Query, VictoriaMetrics, Mimir with a path prefix).
    """

    def __init__(self, url: str, query: str = DEFAULT_PROMETHEUS_QUERY, timeout: float = 3.0):
        if not url:
            raise ValueError("a Prometheus URL is required for the prometheus source")
        self.url = url.rstrip("/")
        self.query = query
        self.timeout = timeout

    def read(self) -> float:
        endpoint = f"{self.url}/api/v1/query?{urllib.parse.urlencode({'query': self.query})}"
        try:
            with urllib.request.urlopen(endpoint, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise TemperatureUnavailable(f"Prometheus request failed: {e}") from e
        return parse_query_result(payload)


def parse_query_result(payload: dict) -> float:
    """
    Reduce an instant query response to one number: the maximum finite value.
    """
    if payload.get("status") != "success":
        raise TemperatureUnavailable(f"Prometheus returned {payload.get('status')}: {payload.get('error')}")
    data = payload.get("data") or {}
    result_type = data.get("resultType")
    result = data.get("result")

    if result_type == "scalar":
        raw_values = [result[1]] if result else []
    elif result_type == "vector":
        raw_values = [sample["value"][1] for sample in result or []]
    else:
        raise TemperatureUnavailable(f"unsupported result type: {result_type}")

    values = []
    for raw in raw_values:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            values.append(value)

    if not values:
        raise TemperatureUnavailable("query returned no usable value")
    return max(values)


@dataclass(frozen=True)
class Reading:
    """
    The temperature the controller should act on, and how it was obtained.

    ``source`` is ``prometheus``, ``local`` or ``failsafe``. In the failsafe
    case ``value`` is None and the caller must run the fan at its failsafe duty.
    """
    value: Optional[float]
    source: str
    local: Optional[float] = None
    cluster: Optional[float] = None
    reason: Optional[str] = None


def resolve(local: LocalSource, cluster: Optional[PrometheusSource] = None) -> Reading:
    """
    Pick the temperature to act on.

    1. Cluster view available: the maximum of the cluster value and the local
       value, so this node is never ignored even if its own agent is missing.
    2. Cluster view unavailable: the local value.
    3. Nothing readable: failsafe.
    """
    local_value: Optional[float] = None
    local_error: Optional[str] = None
    try:
        local_value = local.read()
    except TemperatureUnavailable as e:
        local_error = str(e)

    if cluster is not None:
        try:
            cluster_value = cluster.read()
        except TemperatureUnavailable as e:
            reason = f"prometheus: {e}"
        else:
            value = cluster_value if local_value is None else max(cluster_value, local_value)
            return Reading(value=value, source="prometheus", local=local_value, cluster=cluster_value)
    else:
        reason = None

    if local_value is not None:
        return Reading(value=local_value, source="local", local=local_value, reason=reason)

    reasons = "; ".join(r for r in (reason, f"local: {local_error}") if r)
    return Reading(value=None, source="failsafe", reason=reasons)


def make_resolver(local: LocalSource, cluster: Optional[PrometheusSource]) -> Callable[[], Reading]:
    return lambda: resolve(local, cluster)
