import logging
import signal
import threading
from typing import Callable, Optional, Protocol

from pifanctl.drivers import PwmDriver
from pifanctl.metrics import AgentMetrics, ControllerMetrics
from pifanctl.sources import Reading
from pifanctl.thermal import read_zones

logger = logging.getLogger(__name__)


class Controller(Protocol):
    duty: float

    def update(self, temperature: float) -> float: ...

    def force(self, duty: float) -> float: ...


def install_stop_handlers(stop: threading.Event) -> None:
    """Turn SIGTERM and SIGINT into a request to leave the loop cleanly."""
    def _handler(signum, _frame):
        logger.info(f"Received signal {signum}, stopping")
        stop.set()

    signal.signal(signal.SIGTERM, _handler)
    signal.signal(signal.SIGINT, _handler)


def run_agent(
    metrics: AgentMetrics,
    thermal_path: str,
    interval: float,
    stop: threading.Event,
) -> None:
    """Publish this node's temperatures until asked to stop."""
    logger.info(f"Agent started for node '{metrics.node}', interval {interval}s")
    while not stop.is_set():
        zones = read_zones(thermal_path)
        metrics.observe(zones)
        if zones:
            logger.debug(f"Hottest zone: {max(z.celsius for z in zones):.1f}°C")
        else:
            logger.warning("No readable thermal zone")
        stop.wait(interval)
    logger.info("Agent stopped")


def run_controller(
    driver: PwmDriver,
    controller: Controller,
    read: Callable[[], Reading],
    metrics: Optional[ControllerMetrics],
    interval: float,
    failsafe_duty: float,
    exit_duty: float,
    stop: threading.Event,
    wants_cluster: bool = False,
) -> None:
    """
    Drive the fan until asked to stop.

    When no temperature can be read the fan goes to ``failsafe_duty``: a fan
    stuck at a low duty because its sensor died is the dangerous failure. On
    exit the fan is left at ``exit_duty`` (full speed by default), because a
    stopped controller no longer protects the board.
    """
    logger.info(f"Controller started with driver '{driver.name}', interval {interval}s")
    try:
        while not stop.is_set():
            reading = read()

            if reading.value is None:
                duty = controller.force(failsafe_duty)
                logger.error(f"No temperature available ({reading.reason}); failsafe duty {duty:.1f}%")
                if metrics:
                    metrics.fallback("failsafe")
            else:
                duty = controller.update(reading.value)
                if wants_cluster and reading.source != "prometheus":
                    logger.warning(f"Cluster view unavailable ({reading.reason}); using local temperature")
                    if metrics:
                        metrics.fallback(reading.source)
                logger.info(
                    f"Duty: {duty:.1f}%, Temperature: {reading.value:.1f}°C, Source: {reading.source}"
                )

            driver.set_duty(duty)
            if metrics:
                metrics.observe(duty, reading.value, reading.source)
            stop.wait(interval)
    finally:
        try:
            driver.set_duty(exit_duty)
            logger.info(f"Controller stopped, fan left at {exit_duty:.1f}%")
        finally:
            driver.close()
