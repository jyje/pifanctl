import logging
import os
from typing import Optional

from prometheus_client import CollectorRegistry, Counter, Gauge, start_http_server

from pifanctl import __version__
from pifanctl.thermal import Zone

logger = logging.getLogger(__name__)


def resolve_node_name(explicit: Optional[str] = None) -> str:
    """The ``node`` label value: flag, then NODE_NAME (downward API), then hostname."""
    return explicit or os.environ.get("NODE_NAME") or os.uname().nodename


class AgentMetrics:
    """
    Per-node temperatures, one series per thermal zone.

    The ``node`` label is a constant label set by the agent itself, so the
    series are identifiable even when scraped through a plain Service and keep
    their identity in long-term storage.
    """

    def __init__(self, node: str, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()
        self.node = node
        self.temperature = Gauge(
            "pifanctl_temperature_celsius",
            "Temperature of a thermal zone in degrees Celsius",
            ["node", "zone", "type"],
            registry=self.registry,
        )
        self.temperature_max = Gauge(
            "pifanctl_node_temperature_max_celsius",
            "Hottest thermal zone of the node in degrees Celsius",
            ["node"],
            registry=self.registry,
        )
        self.read_errors = Counter(
            "pifanctl_temperature_read_errors_total",
            "Number of reads that returned no usable thermal zone",
            ["node"],
            registry=self.registry,
        )
        self.info = Gauge(
            "pifanctl_agent_info",
            "Agent build information",
            ["node", "version"],
            registry=self.registry,
        )
        self.info.labels(node=node, version=__version__).set(1)

    def observe(self, zones: list[Zone]) -> None:
        # Drop the previous reading first: a stale value is worse than a gap,
        # because the controller would keep acting on it.
        self.temperature.clear()
        self.temperature_max.clear()
        if not zones:
            self.read_errors.labels(node=self.node).inc()
            return
        for zone in zones:
            self.temperature.labels(node=self.node, zone=zone.name, type=zone.type).set(zone.celsius)
        self.temperature_max.labels(node=self.node).set(max(zone.celsius for zone in zones))


class ControllerMetrics:
    """What the controller decided, and why."""

    SOURCES = ("prometheus", "local", "failsafe")

    def __init__(self, node: str, registry: Optional[CollectorRegistry] = None):
        self.registry = registry or CollectorRegistry()
        self.node = node
        self.duty = Gauge(
            "pifanctl_fan_duty_percent",
            "Fan duty cycle currently applied, in percent",
            ["node"],
            registry=self.registry,
        )
        self.control_temperature = Gauge(
            "pifanctl_control_temperature_celsius",
            "Temperature the controller acted on in the last cycle",
            ["node"],
            registry=self.registry,
        )
        self.source = Gauge(
            "pifanctl_control_source",
            "1 for the source the controller used in the last cycle",
            ["node", "source"],
            registry=self.registry,
        )
        self.followed = Gauge(
            "pifanctl_control_followed_node",
            "1 for the node whose temperature the controller followed in the last cycle",
            ["node", "followed"],
            registry=self.registry,
        )
        self.fallbacks = Counter(
            "pifanctl_control_fallbacks_total",
            "Cycles that could not use the cluster view and fell back",
            ["node", "to"],
            registry=self.registry,
        )
        self.info = Gauge(
            "pifanctl_controller_info",
            "Controller build and driver information",
            ["node", "version", "driver", "algorithm"],
            registry=self.registry,
        )

    def set_info(self, driver: str, algorithm: str) -> None:
        self.info.labels(node=self.node, version=__version__, driver=driver, algorithm=algorithm).set(1)

    def observe(self, duty: float, temperature: Optional[float], source: str,
                followed: Optional[str] = None) -> None:
        self.duty.labels(node=self.node).set(duty)
        # Only the node followed now is exported, so the series reads as "who
        # drives this fan" without a trail of nodes it used to follow.
        self.followed.clear()
        if followed is not None:
            self.followed.labels(node=self.node, followed=followed).set(1)
        if temperature is not None:
            self.control_temperature.labels(node=self.node).set(temperature)
        for name in self.SOURCES:
            self.source.labels(node=self.node, source=name).set(1 if name == source else 0)

    def fallback(self, to: str) -> None:
        self.fallbacks.labels(node=self.node, to=to).inc()


def serve(registry: CollectorRegistry, port: int, address: str = "0.0.0.0") -> None:
    start_http_server(port, addr=address, registry=registry)
    logger.info(f"Serving metrics on {address}:{port}/metrics")
