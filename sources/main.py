import os, time, logging
from typing import Annotated, Optional

import typer

import pifanctl.router as router
from pifanctl import __version__
import pifanctl.enum as enum
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

    def invoke(self, ctx):
        from pifanctl.topology.kube import APIError
        from pifanctl.topology.model import TopologyError
        try:
            return super().invoke(ctx)
        except (APIError, TopologyError, OSError) as error:
            typer.echo(str(error), err=True)
            raise typer.Exit(code=2)

app = typer.Typer(
    cls = TyperGroup,
    name = "pifanctl",
    context_settings = {"help_option_names": ["-h", "--help"]},
    help = """
    🥧 pifanctl: Raspberry Pi fan control, the Kubernetes way

    Declare Fan and CoolingZone CRs with the operator chart. Use topology,
    fan and zone commands to manage or inspect Kubernetes resources.
    Hardware workers run under the operator; local YAML execution is mock-only.

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
    kubeconfig: Optional[str] = typer.Option(None, "--kubeconfig", envvar="KUBECONFIG"),
    context: Optional[str] = typer.Option(None, "--context"),
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

    ctx.obj = {"kubeconfig": kubeconfig, "context": context}

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



from pifanctl.topology.cli import register
register(app)

if __name__ == "__main__":
    app()
