import os, time, logging
from typing import Annotated, Optional

import typer

import pifanctl.router as router
from pifanctl import __version__
import pifanctl.enum as enum
from pifanctl.control import CurveConfig
from pifanctl.sources import DEFAULT_PROMETHEUS_QUERY
from pifanctl.thermal import DEFAULT_THERMAL_PATH

logger = logging.getLogger(__name__)
class TyperGroup(typer.core.TyperGroup):
    """
    Custom TyperGroup
    """

    def get_usage(self, ctx: typer.Context) -> str:
        usage = super().get_usage(ctx)
        main_py_name = "main.py"
        app_name = "pifanctl"
        return usage.replace(main_py_name, app_name)

app = typer.Typer(
    cls = TyperGroup,
    name = "pifanctl",
    context_settings = {"help_option_names": ["-h", "--help"]},
    help = """
    🥧 pifanctl: A CLI for PWM Fan Controlling of Raspberry Pi

    Run `agent` on every node to publish temperatures, and `start` on the node
    that has the fan. With `--source prometheus` the fan follows the hottest
    node of the cluster.

    Project Page: https://github.com/jyje/pifanctl
    """
)

state: dict = {}

ThermalPath = Annotated[
    str,
    typer.Option(
        "--thermal-path",
        envvar = "THERMAL_PATH",
        help = "Directory that contains the thermal_zone* entries",
    ),
]
NodeName = Annotated[
    Optional[str],
    typer.Option(
        "--node",
        envvar = "NODE_NAME",
        help = "Node name for the `node` metric label. Defaults to the hostname",
    ),
]


def version_callback(value: bool):
    """
    Version callback

    Prints the release version and, when the build recorded one, the commit it
    was built from, for example ``0.2.0 (188b3e2)``. The commit comes from the
    ``version`` file that the image build and ``install.sh`` write.
    """

    if not value:
        return

    VERSION_FILE_PATH = os.path.join(os.path.dirname(__file__), "version")

    assert os.path.exists(VERSION_FILE_PATH), f"version file not found: {VERSION_FILE_PATH}"

    build = open(VERSION_FILE_PATH, "r").read().strip()
    typer.echo(f"{__version__} ({build})" if build else __version__)
    raise typer.Exit()


@app.callback()
def common_callback(
    ctx: typer.Context,
    log_level: Annotated[
        enum.LogLevels,
        typer.Option(
            "--log-level", "-l",
            envvar = "LOG_LEVEL",
            help = "Set the log level",
            autocompletion = enum.LogLevels.list,
        )
    ] = enum.LogLevels.INFO,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose", "-v",
            help = "Enable verbose output",
        )
    ] = False,
    version: Annotated[
        bool,
        typer.Option(
            "--version", "-V",
            help = "Show version and exit",
            callback = version_callback,
        )
    ] = False,
):
    """
    Common callback
    """

    # Set logging
    logging.basicConfig(
        level = log_level.value,
        format = "%(levelname)s [%(asctime)sZ] %(message)s",
        datefmt = "%Y-%m-%d %H:%M:%S",
    )
    logging.Formatter.converter = time.gmtime
    logging.addLevelName(logging.DEBUG, "\033[94mDEBUG\033[0m")
    logging.addLevelName(logging.INFO, "\033[92mINFO\033[0m")
    logging.addLevelName(logging.WARNING, "\033[93mWARNING\033[0m")
    logging.addLevelName(logging.ERROR, "\033[91mERROR\033[0m")
    logging.addLevelName(logging.CRITICAL, "\033[95mCRITICAL\033[0m")
    state["log_level"] = log_level

    # Set verbose
    state["verbose"] = verbose

    # Show state
    logger.debug(f"state: {state}")


@app.command(
    help = "Show current temperatures"
)
def status(
    ctx: typer.Context,
    thermal_path: ThermalPath = DEFAULT_THERMAL_PATH,
):
    router.status(state, thermal_path)


@app.command(
    help = "Publish this node's temperatures as Prometheus metrics (run on every node)"
)
def agent(
    ctx: typer.Context,
    thermal_path: ThermalPath = DEFAULT_THERMAL_PATH,
    interval: Annotated[
        float,
        typer.Option(
            "--interval",
            envvar = "AGENT_INTERVAL",
            help = "Seconds between temperature reads. [unit: s]",
        )
    ] = 5.0,
    metrics_port: Annotated[
        int,
        typer.Option(
            "--metrics-port",
            envvar = "METRICS_PORT",
            help = "Port that serves /metrics",
        )
    ] = 9101,
    node: NodeName = None,
):
    router.agent(state, thermal_path, interval, metrics_port, node)


@app.command(
    help = "Start fan control"
)
def start(
    ctx: typer.Context,
    pin: Annotated[
        int,
        typer.Option(
            "--pin", "-p",
            envvar = "PIN",
            help = "Set the BCM pin number to drive the PWM fan",
        )
    ] = 18,
    driver: Annotated[
        enum.Drivers,
        typer.Option(
            "--driver",
            envvar = "DRIVER",
            help = "How to drive the pin. `auto` uses sysfs PWM on Raspberry Pi 5 and RPi.GPIO elsewhere, and never the mock",
        )
    ] = enum.Drivers.AUTO,
    pwm_chip: Annotated[
        int,
        typer.Option(
            "--pwm-chip",
            envvar = "PWM_CHIP",
            help = "pwmchip index for the sysfs driver",
        )
    ] = 0,
    pwm_channel: Annotated[
        int,
        typer.Option(
            "--pwm-channel",
            envvar = "PWM_CHANNEL",
            help = "PWM channel for the sysfs driver (GPIO 18 is channel 2 on Raspberry Pi 5)",
        )
    ] = 2,
    pwm_frequency: Annotated[
        int,
        typer.Option(
            "--pwm-frequency",
            envvar = "PWM_FREQUENCY",
            help = "Set the PWM frequency. [unit: Hz]",
        )
    ] = 1000,
    pwm_refresh_interval: Annotated[
        float,
        typer.Option(
            "--pwm-refresh-interval",
            envvar = "PWM_REFRESH_INTERVAL",
            help = "Set the PWM refresh interval. [unit: s]",
        )
    ] = 5.0,
    algorithm: Annotated[
        enum.Algorithms,
        typer.Option(
            "--algorithm",
            envvar = "ALGORITHM",
            help = "`curve` maps temperature to duty, `step` is the original fixed-step behaviour",
        )
    ] = enum.Algorithms.CURVE,
    source: Annotated[
        enum.Sources,
        typer.Option(
            "--source",
            envvar = "SOURCE",
            help = "`local` reads this node. `prometheus` follows the hottest node of the cluster and falls back to local",
        )
    ] = enum.Sources.LOCAL,
    prometheus_url: Annotated[
        Optional[str],
        typer.Option(
            "--prometheus-url",
            envvar = "PROMETHEUS_URL",
            help = "Base URL of a Prometheus-compatible API, for example http://prometheus:9090",
        )
    ] = None,
    prometheus_query: Annotated[
        str,
        typer.Option(
            "--prometheus-query",
            envvar = "PROMETHEUS_QUERY",
            help = "Instant query whose maximum value is the control temperature",
        )
    ] = DEFAULT_PROMETHEUS_QUERY,
    prometheus_timeout: Annotated[
        float,
        typer.Option(
            "--prometheus-timeout",
            envvar = "PROMETHEUS_TIMEOUT",
            help = "Timeout of a Prometheus request. [unit: s]",
        )
    ] = 3.0,
    thermal_path: ThermalPath = DEFAULT_THERMAL_PATH,
    temp_low: Annotated[
        float,
        typer.Option(
            "--temp-low",
            envvar = "TEMP_LOW",
            help = "Curve: below this the fan idles. [unit: °C]",
        )
    ] = 50.0,
    temp_high: Annotated[
        float,
        typer.Option(
            "--temp-high",
            envvar = "TEMP_HIGH",
            help = "Curve: at and above this the fan runs at the maximum duty. [unit: °C]",
        )
    ] = 70.0,
    duty_idle: Annotated[
        float,
        typer.Option(
            "--duty-idle",
            envvar = "DUTY_IDLE",
            help = "Curve: duty below --temp-low. [unit: %]",
        )
    ] = 0.0,
    duty_start: Annotated[
        float,
        typer.Option(
            "--duty-start",
            envvar = "DUTY_START",
            help = "Curve: duty at --temp-low, where the ramp begins. [unit: %]",
        )
    ] = 30.0,
    duty_max: Annotated[
        float,
        typer.Option(
            "--duty-max",
            envvar = "DUTY_MAX",
            help = "Curve: duty at and above --temp-high. [unit: %]",
        )
    ] = 100.0,
    duty_down_step: Annotated[
        float,
        typer.Option(
            "--duty-down-step",
            envvar = "DUTY_DOWN_STEP",
            help = "Curve: largest duty decrease per interval, the hysteresis. [unit: %]",
        )
    ] = 5.0,
    target_temperature: Annotated[
        float,
        typer.Option(
            "--target-temperature", "-t",
            envvar = "TARGET_TEMPERATURE",
            help = "Step algorithm: the target temperature. [unit: °C]",
        )
    ] = 50.0,
    duty_cycle_initial: Annotated[
        float,
        typer.Option(
            "--duty-cycle-initial",
            envvar = "DUTY_CYCLE_INITIAL",
            help = "Set the initial duty cycle. [unit: %]",
        )
    ] = 0.0,
    duty_cycle_step: Annotated[
        float,
        typer.Option(
            "--duty-cycle-step",
            envvar = "DUTY_CYCLE_STEP",
            help = "Step algorithm: the duty cycle step. [unit: %]",
        )
    ] = 2.0,
    failsafe_duty: Annotated[
        float,
        typer.Option(
            "--failsafe-duty",
            envvar = "FAILSAFE_DUTY",
            help = "Duty used when no temperature can be read. [unit: %]",
        )
    ] = 100.0,
    exit_duty: Annotated[
        float,
        typer.Option(
            "--exit-duty",
            envvar = "EXIT_DUTY",
            help = "Duty left on the fan when the controller stops. [unit: %]",
        )
    ] = 100.0,
    metrics_port: Annotated[
        int,
        typer.Option(
            "--metrics-port",
            envvar = "METRICS_PORT",
            help = "Port that serves the controller's /metrics. 0 disables it",
        )
    ] = 9102,
    node: NodeName = None,
):
    try:
        curve = CurveConfig(
            temp_low = temp_low,
            temp_high = temp_high,
            duty_idle = duty_idle,
            duty_start = duty_start,
            duty_max = duty_max,
            duty_down_step = duty_down_step,
        )
    except ValueError as e:
        raise typer.BadParameter(str(e))

    params = {
        "pin": pin,
        "driver": driver.value,
        "algorithm": algorithm.value,
        "source": source.value,
        "pwm_frequency": pwm_frequency,
        "pwm_refresh_interval": pwm_refresh_interval,
        "curve": curve if algorithm == enum.Algorithms.CURVE else None,
        "failsafe_duty": failsafe_duty,
        "exit_duty": exit_duty,
    }
    logger.info(f"Starting fan control with params: {params}")

    router.start(
        state = state,
        pin = pin,
        driver = driver,
        pwm_chip = pwm_chip,
        pwm_channel = pwm_channel,
        pwm_frequency = pwm_frequency,
        pwm_refresh_interval = pwm_refresh_interval,
        algorithm = algorithm,
        source = source,
        prometheus_url = prometheus_url,
        prometheus_query = prometheus_query,
        prometheus_timeout = prometheus_timeout,
        thermal_path = thermal_path,
        curve = curve,
        target_temperature = target_temperature,
        duty_cycle_initial = duty_cycle_initial,
        duty_cycle_step = duty_cycle_step,
        failsafe_duty = failsafe_duty,
        exit_duty = exit_duty,
        metrics_port = metrics_port or None,
        node = node,
    )


if __name__ == "__main__":
    app()
