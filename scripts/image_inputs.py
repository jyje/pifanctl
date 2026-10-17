"""
Decides whether a pull request can change the container image.

    python scripts/image_inputs.py <base-ref>

Prints `image=true` or `image=false`, ready to append to $GITHUB_OUTPUT. The image is
built from `sources/` (code and pinned requirements) and the Dockerfiles in `docker/`.
`.github/workflows/ci.yaml` holds the build and smoke test steps, so a change there is
tested too. Anything else cannot change the image: charts, tests, docs, bot
configuration and the other workflows.
"""
import re
import subprocess
import sys

IMAGE_INPUTS = (
    re.compile(r"^sources/"),
    re.compile(r"^docker/"),
    re.compile(r"^\.dockerignore$"),
    re.compile(r"^\.github/workflows/ci\.yaml$"),
)


def affects_image(paths: list[str]) -> bool:
    return any(pattern.match(path) for path in paths for pattern in IMAGE_INPUTS)


def changed_files(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", f"{base}...HEAD"],
        capture_output=True, text=True, check=True,
    )
    return [path for path in result.stdout.split("\0") if path]


def main(base: str) -> int:
    print(f"image={'true' if affects_image(changed_files(base)) else 'false'}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    sys.exit(main(sys.argv[1]))
