"""
Fails a pull request that changes what ships without bumping its version.

    python scripts/check_version_bump.py <base-ref>

The application is `sources/main.py` and `sources/pifanctl/`. The chart is
`charts/pifanctl/` (its `ci/` value sets are test fixtures and do not count).
A new application version changes the chart's `appVersion`, so it also needs a
new chart version.
"""
import re
import subprocess
import sys

APP_FILE = "sources/pifanctl/__init__.py"
CHART_FILE = "charts/pifanctl/Chart.yaml"


def touches_application(path: str) -> bool:
    return path == "sources/main.py" or path.startswith("sources/pifanctl/")


def touches_chart(path: str) -> bool:
    return path.startswith("charts/pifanctl/") and not path.startswith("charts/pifanctl/ci/")


def app_version(text: str) -> str | None:
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', text, re.M)
    return match.group(1) if match else None


def chart_version(text: str) -> str | None:
    match = re.search(r"^version:\s*['\"]?([^'\"\s]+)", text, re.M)
    return match.group(1) if match else None


def check(changed: list[str], old_app: str | None, new_app: str | None,
          old_chart: str | None, new_chart: str | None) -> list[str]:
    errors = []
    if any(touches_application(p) for p in changed) and old_app == new_app:
        errors.append(
            f"The application changed but __version__ is still {new_app} in {APP_FILE}. "
            "Bump __version__ and the chart's appVersion together."
        )
    if any(touches_chart(p) for p in changed) and old_chart == new_chart:
        errors.append(
            f"The chart changed but its version is still {new_chart} in {CHART_FILE}. "
            "Bump `version`; a new application version also changes `appVersion`."
        )
    return errors


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def main(base: str) -> int:
    changed = git("diff", "--name-only", f"{base}...HEAD").split()
    try:
        old_app = app_version(git("show", f"{base}:{APP_FILE}"))
        old_chart = chart_version(git("show", f"{base}:{CHART_FILE}"))
    except subprocess.CalledProcessError:
        old_app = old_chart = None  # the file did not exist on the base branch
    with open(APP_FILE) as f:
        new_app = app_version(f.read())
    with open(CHART_FILE) as f:
        new_chart = chart_version(f.read())

    errors = check(changed, old_app, new_app, old_chart, new_chart)
    for error in errors:
        print(f"::error::{error}")
    if not errors:
        print(f"Version check passed (application {new_app}, chart {new_chart}).")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
