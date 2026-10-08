"""
Fails a pull request that changes what ships without bumping its version.

    python scripts/check_version_bump.py <base-ref>

The application is `sources/main.py` and `sources/pifanctl/`. The supported
operator chart follows the application version, including appVersion. Historical
charts retain separate version sources; chart `ci/` value sets are fixtures.
Updating chart content requires its version to change.
"""
import re
from pathlib import Path
import subprocess
import sys

APP_FILE = "sources/pifanctl/__init__.py"
CHARTS_DIR = Path("charts")


def touches_application(path: str) -> bool:
    return path == "sources/main.py" or path.startswith("sources/pifanctl/")


def changed_chart_files(changed: list[str]) -> list[Path]:
    touched = []
    for chart_file in CHARTS_DIR.glob("*/Chart.yaml"):
        prefix = str(chart_file.parent) + "/"
        if any(path.startswith(prefix) and "/ci/" not in path for path in changed):
            touched.append(chart_file)
    return touched


def app_version(text: str) -> str | None:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else None


def chart_version(text: str) -> str | None:
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.M)
    return match.group(1) if match else None


def check(changed: list[str], old_app: str | None, new_app: str | None,
          old_charts: dict[str, str | None],
          new_charts: dict[str, str | None]) -> list[str]:
    errors = []
    if any(touches_application(p) for p in changed) and old_app == new_app:
        errors.append(
            f"The application changed but __version__ is still {new_app} in {APP_FILE}. "
            "Bump __version__ in the application package."
        )
    for chart_file in changed_chart_files(changed):
        path = str(chart_file)
        if old_charts.get(path) == new_charts.get(path):
            errors.append(
                f"The chart changed but its version is still {new_charts.get(path)} "
                f"in {path}. Bump that chart's `version`."
            )
    return errors


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main(base: str) -> int:
    changed = git("diff", "--name-only", f"{base}...HEAD").split()
    try:
        old_app = app_version(git("show", f"{base}:{APP_FILE}"))
    except subprocess.CalledProcessError:
        old_app = None
    with open(APP_FILE) as f:
        new_app = app_version(f.read())
    old_charts = {}
    new_charts = {}
    for file in CHARTS_DIR.glob('*/Chart.yaml'):
        path = str(file)
        try:
            old_charts[path] = chart_version(git("show", f"{base}:{path}"))
        except subprocess.CalledProcessError:
            old_charts[path] = None
        new_charts[path] = chart_version(file.read_text())

    errors = check(changed, old_app, new_app, old_charts, new_charts)
    operator = Path('charts/pifanctl-operator/Chart.yaml')
    if operator.exists():
        text = operator.read_text()
        pinned = re.search(r'^appVersion:\s*[\'"]?([^\'"\s]+)', text, re.M)
        if chart_version(text) != new_app or not pinned or pinned.group(1) != new_app:
            errors.append('The supported operator chart version and appVersion must match the application version.')
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print(f"Version check passed (application {new_app}; supported operator chart follows the application).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
