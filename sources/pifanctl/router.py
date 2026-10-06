import logging
import threading
from typing import Optional

import typer

from pifanctl.metrics import AgentMetrics, resolve_node_name, serve
from pifanctl.service import install_stop_handlers, run_agent
from pifanctl.thermal import DEFAULT_THERMAL_PATH, max_temperature, read_zones

logger = logging.getLogger(__name__)


def status(state, thermal_path: str = DEFAULT_THERMAL_PATH):
    zones = read_zones(thermal_path)
    if not zones:
        typer.echo("No temperature data available")
        return
    for zone in zones:
        typer.echo(f"{zone.name} ({zone.type}): {zone.celsius:.3f} °C")
    typer.echo(f"Current temperature: {max_temperature(zones):.3f} °C")


def agent(
    state: dict,
    thermal_path: str,
    interval: float,
    metrics_port: int,
    node: Optional[str],
):
    metrics = AgentMetrics(resolve_node_name(node))
    serve(metrics.registry, metrics_port)
    stop = threading.Event()
    install_stop_handlers(stop)
    run_agent(metrics, thermal_path, interval, stop)
