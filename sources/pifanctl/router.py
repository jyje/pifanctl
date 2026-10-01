import logging
import threading
from typing import Optional

import typer

from pifanctl.control import CurveConfig, CurveController, StepController
from pifanctl.drivers import DriverError, create_driver
from pifanctl.enum import Algorithms, Drivers, Sources
from pifanctl.metrics import AgentMetrics, ControllerMetrics, resolve_node_name, serve
from pifanctl.service import install_stop_handlers, run_agent, run_controller
from pifanctl.sources import LocalSource, PrometheusSource, make_resolver
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


def start(
    state: dict,
    pin: int,
    driver: Drivers,
    pwm_chip: int,
    pwm_channel: int,
    pwm_frequency: int,
    pwm_refresh_interval: float,
    algorithm: Algorithms,
    source: Sources,
    prometheus_url: Optional[str],
    prometheus_query: str,
    prometheus_timeout: float,
    thermal_path: str,
    curve: CurveConfig,
    target_temperature: float,
    duty_cycle_initial: float,
    duty_cycle_step: float,
    failsafe_duty: float,
    exit_duty: float,
    metrics_port: Optional[int],
    node: Optional[str],
):
    if source == Sources.PROMETHEUS and not prometheus_url:
        raise typer.BadParameter("--prometheus-url is required with --source prometheus")

    local = LocalSource(thermal_path)
    cluster = PrometheusSource(prometheus_url, prometheus_query, prometheus_timeout) \
        if source == Sources.PROMETHEUS else None

    if algorithm == Algorithms.CURVE:
        controller = CurveController(curve, initial_duty=duty_cycle_initial)
    else:
        controller = StepController(target_temperature, duty_cycle_step, initial_duty=duty_cycle_initial)

    try:
        pwm = create_driver(driver, pin, pwm_frequency, duty_cycle_initial, pwm_chip, pwm_channel)
    except DriverError as e:
        # Do not fall back to a mock: an uncontrolled fan that looks healthy is
        # worse than a pod that crash-loops and gets noticed.
        logger.error(f"Cannot drive the fan: {e}")
        raise typer.Exit(code=2)

    metrics = None
    if metrics_port:
        metrics = ControllerMetrics(resolve_node_name(node))
        metrics.set_info(pwm.name, algorithm.value)
        serve(metrics.registry, metrics_port)

    stop = threading.Event()
    install_stop_handlers(stop)
    run_controller(
        driver=pwm,
        controller=controller,
        read=make_resolver(local, cluster, resolve_node_name(node)),
        metrics=metrics,
        interval=pwm_refresh_interval,
        failsafe_duty=failsafe_duty,
        exit_duty=exit_duty,
        stop=stop,
        wants_cluster=cluster is not None,
    )
