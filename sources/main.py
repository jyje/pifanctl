import os, time, logging
import typer
from typing_extensions import Annotated

import pifanctl.router as router
import pifanctl.enum as enum

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
    
    Project Page: https://github.com/jyje/pifanctl
    """
)

state: dict = {}


def version_callback(value: bool):
    """
    Version callback

    The version is set by value. The value is determined by the GitHub Actions workflow.
    """

    if not value:
        return

    VERSION_FILE_PATH = os.path.join(os.path.dirname(__file__), "version")

    assert os.path.exists(VERSION_FILE_PATH), f"version file not found: {VERSION_FILE_PATH}"

    version = open(VERSION_FILE_PATH, "r").read().strip()
    typer.echo(version)
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
        level = log_level,
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
    cls = TyperGroup,
    help = "Show current status"
)
def status(ctx: typer.Context):
    router.status(state)


@app.command(
    cls = TyperGroup,
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
    ] = 18.0,
    target_temperature: Annotated[
        float,
        typer.Option(
            "--target-temperature", "-t",
            envvar = "TARGET_TEMPERATURE",
            help = "Set the target temperature. [unit: °C]",
        )
    ] = 50.0,
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
    ] = 30.0,
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
            help = "Set the duty cycle step. [unit: %]",
        )
    ] = 2.0,
):
    params = {
        "pin": pin,
        "target_temperature": target_temperature,
        "pwm_frequency": pwm_frequency,
        "pwm_refresh_interval": pwm_refresh_interval,
        "duty_cycle_initial": duty_cycle_initial,
        "duty_cycle_step": duty_cycle_step,
    }
    logger.info(f"Starting fan control with params: {params}")

    router.start(state=state, **params)


@app.command(
    cls = TyperGroup,
    help = "Stop fan control"
)
def stop(ctx: typer.Context):
    router.stop(state)


@app.command(
    cls = TyperGroup,
    help = "Set and enable fan control in system service"
)
def enable(ctx: typer.Context):
    router.enable(state)


@app.command(
    cls = TyperGroup,
    help = "Disable fan control from system service"
)
def disable(ctx: typer.Context):
    router.disable(state)


@app.command(
    cls = TyperGroup,
    help = "Manage a configuration of fan control"
)
def config(ctx: typer.Context):
    router.config(state)


if __name__ == "__main__":
    app()
