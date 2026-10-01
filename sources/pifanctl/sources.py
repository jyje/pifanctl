import json
import logging
import math
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Optional

from pifanctl.thermal import TemperatureUnavailable, max_temperature, read_zones

logger = logging.getLogger(__name__)

# One value per node. The controller acts on the maximum, and keeps the node
# labels so it can say which node it followed and what every other node reads.
DEFAULT_PROMETHEUS_QUERY = "max by (node) (pifanctl_temperature_celsius)"

# Label used for a sample that carries no node label (for example a custom
# query that already aggregates everything away).
UNKNOWN_NODE = "cluster"


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

    def read(self) -> dict[str, float]:
        """Temperature per node, from the query's node label."""
        endpoint = f"{self.url}/api/v1/query?{urllib.parse.urlencode({'query': self.query})}"
        try:
            with urllib.request.urlopen(endpoint, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError) as e:
            raise TemperatureUnavailable(f"Prometheus request failed: {e}") from e
        return parse_query_result(payload)


def parse_query_result(payload: dict) -> dict[str, float]:
    """
    Turn an instant query response into a temperature per node.

    The node comes from the sample's ``node`` label; a sample without one is
    reported as ``cluster``. Values that are not finite are dropped. When two
    samples name the same node the hotter one wins.
    """
    if payload.get("status") != "success":
        raise TemperatureUnavailable(f"Prometheus returned {payload.get('status')}: {payload.get('error')}")
    data = payload.get("data") or {}
    result_type = data.get("resultType")
    result = data.get("result")

    if result_type == "scalar":
        samples = [(UNKNOWN_NODE, result[1])] if result else []
    elif result_type == "vector":
        samples = [((sample.get("metric") or {}).get("node") or UNKNOWN_NODE, sample["value"][1])
                   for sample in result or []]
    else:
        raise TemperatureUnavailable(f"unsupported result type: {result_type}")

    nodes: dict[str, float] = {}
    for node, raw in samples:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if math.isfinite(value):
            nodes[node] = max(value, nodes.get(node, value))

    if not nodes:
        raise TemperatureUnavailable("query returned no usable value")
    return nodes


@dataclass(frozen=True)
class Reading:
    """
    The temperature the controller should act on, and how it was obtained.

    ``source`` is ``prometheus``, ``local`` or ``failsafe``. In the failsafe
    case ``value`` is None and the caller must run the fan at its failsafe duty.

    ``nodes`` holds every node's temperature as far as it is known, and
    ``driver`` names the node the controller followed, so a log line can say
    both what the fan reacted to and what the other nodes read.
    """
    value: Optional[float]
    source: str
    local: Optional[float] = None
    cluster: Optional[float] = None
    reason: Optional[str] = None
    nodes: dict[str, float] = field(default_factory=dict)
    driver: Optional[str] = None


def resolve(local: LocalSource, cluster: Optional[PrometheusSource] = None,
            local_node: str = "local") -> Reading:
    """
    Pick the temperature to act on.

    1. Cluster view available: the hottest node of the cluster and this node,
       so this node is never ignored even if its own agent is missing.
    2. Cluster view unavailable: the local value.
    3. Nothing readable: failsafe.
    """
    local_value: Optional[float] = None
    local_error: Optional[str] = None
    try:
        local_value = local.read()
    except TemperatureUnavailable as e:
        local_error = str(e)

    reason = None
    if cluster is not None:
        try:
            nodes = cluster.read()
        except TemperatureUnavailable as e:
            reason = f"prometheus: {e}"
        else:
            nodes = dict(nodes)
            cluster_driver = max(nodes, key=nodes.get)
            cluster_value = nodes[cluster_driver]
            if local_value is not None and local_value > cluster_value:
                value, driver = local_value, local_node
            else:
                value, driver = cluster_value, cluster_driver
            if local_value is not None:
                # The agent's own reading is older than the live one; show the
                # live one for this node.
                nodes[local_node] = local_value
            return Reading(value=value, source="prometheus", local=local_value,
                           cluster=cluster_value, nodes=nodes, driver=driver)

    if local_value is not None:
        return Reading(value=local_value, source="local", local=local_value, reason=reason,
                       nodes={local_node: local_value}, driver=local_node)

    reasons = "; ".join(r for r in (reason, f"local: {local_error}") if r)
    return Reading(value=None, source="failsafe", reason=reasons)


def make_resolver(local: LocalSource, cluster: Optional[PrometheusSource],
                  local_node: str = "local") -> Callable[[], Reading]:
    return lambda: resolve(local, cluster, local_node)
