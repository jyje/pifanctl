"""Validate branch coverage reports and render trusted coverage badges."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import html
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "coverage-policy.json"
SCHEMA_VERSION = 1


class CoverageError(ValueError):
    """Raised when a coverage report cannot support a trustworthy decision."""


def _count(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CoverageError(f"{name} must be a non-negative integer")
    return value


def _percentage(covered: int, total: int) -> float | None:
    return round(covered * 100 / total, 4) if total else None


def _summary_counts(summary: Any, *, name: str) -> dict[str, int]:
    if not isinstance(summary, dict):
        raise CoverageError(f"{name}.summary must be an object")
    result = {
        key: _count(summary.get(key), f"{name}.summary.{key}")
        for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")
    }
    for covered, total in (("covered_lines", "num_statements"), ("covered_branches", "num_branches")):
        if result[covered] > result[total]:
            raise CoverageError(f"{name}.summary.{covered} exceeds {total}")
    return result


def report_metrics(report: Any) -> dict[str, int | float | None]:
    """Validate coverage.py JSON and return raw counts plus precise percentages."""
    if not isinstance(report, dict):
        raise CoverageError("coverage report must be a JSON object")
    meta = report.get("meta")
    if not isinstance(meta, dict) or meta.get("branch_coverage") is not True:
        raise CoverageError("coverage report was not collected with branch coverage enabled")
    files = report.get("files")
    if not isinstance(files, dict) or not files:
        raise CoverageError("coverage report contains no application files")

    sums = {key: 0 for key in ("covered_lines", "num_statements", "covered_branches", "num_branches")}
    for filename, details in files.items():
        if not isinstance(filename, str) or not filename.startswith("sources/"):
            raise CoverageError(f"unexpected application path: {filename!r}")
        file_counts = _summary_counts(details.get("summary") if isinstance(details, dict) else None, name=filename)
        for key, value in file_counts.items():
            sums[key] += value

    totals = _summary_counts(report.get("totals"), name="totals")
    if sums != totals:
        raise CoverageError(f"project totals do not match per-file totals: {sums!r} != {totals!r}")
    if totals["num_statements"] == 0:
        raise CoverageError("coverage report contains no executable statements")

    return {
        **totals,
        "line_percent": _percentage(totals["covered_lines"], totals["num_statements"]),
        "branch_percent": _percentage(totals["covered_branches"], totals["num_branches"]),
    }


def check_line_floor(metrics: dict[str, int | float | None], floor: float) -> None:
    covered = metrics.get("covered_lines")
    total = metrics.get("num_statements")
    if (
        isinstance(covered, bool)
        or not isinstance(covered, int)
        or isinstance(total, bool)
        or not isinstance(total, int)
        or total <= 0
        or covered * 100 + 1e-9 < floor * total
    ):
        line_percent = metrics.get("line_percent")
        raise CoverageError(f"line coverage {line_percent}% is below {floor}%")


def check_branch_floor(metrics: dict[str, int | float | None], floor: float) -> None:
    covered, total = metrics.get("covered_branches"), metrics.get("num_branches")
    if (isinstance(covered, bool) or not isinstance(covered, int)
            or isinstance(total, bool) or not isinstance(total, int) or total <= 0
            or covered * 100 + 1e-9 < floor * total):
        raise CoverageError(f"branch coverage {metrics.get('branch_percent')}% is below {floor}%")


def check_floors(metrics: dict[str, int | float | None], policy: dict[str, Any]) -> None:
    check_line_floor(metrics, policy["line_floor_percent"])
    if policy.get("branch_floor_percent") is not None:
        check_branch_floor(metrics, policy["branch_floor_percent"])


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CoverageError(f"coverage report not found: {path}") from exc
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CoverageError(f"invalid JSON coverage report: {path}") from exc


def load_policy(path: Path = POLICY_PATH) -> dict[str, Any]:
    policy = load_json(path)
    if not isinstance(policy, dict) or policy.get("schema_version") != SCHEMA_VERSION:
        raise CoverageError("unsupported coverage policy schema")
    versions = policy.get("python_versions")
    canonical = policy.get("canonical_python")
    floor = policy.get("line_floor_percent")
    if not isinstance(versions, list) or not versions or any(not isinstance(v, str) for v in versions):
        raise CoverageError("coverage policy must define Python versions")
    if len(set(versions)) != len(versions) or canonical not in versions:
        raise CoverageError("canonical Python version must appear once in the matrix")
    if isinstance(floor, bool) or not isinstance(floor, (int, float)) or not 0 < floor <= 100:
        raise CoverageError("line_floor_percent must be in (0, 100]")
    branch_floor = policy.get("branch_floor_percent")
    if branch_floor is not None and (
        isinstance(branch_floor, bool) or not isinstance(branch_floor, (int, float)) or not 0 <= branch_floor <= 100
    ):
        raise CoverageError("branch_floor_percent must be null or in [0, 100]")
    return policy


def make_manifest(report: Any, python_version: str, commit_sha: str, *, measured_at: str | None = None) -> dict[str, Any]:
    metrics = report_metrics(report)
    coverage_version = report.get("meta", {}).get("version")
    if not isinstance(coverage_version, str) or not coverage_version:
        raise CoverageError("coverage.py version is missing from report metadata")
    if not isinstance(python_version, str) or not python_version:
        raise CoverageError("Python version is required")
    if not isinstance(commit_sha, str) or not commit_sha:
        raise CoverageError("tested commit SHA is required")
    return {
        "schema_version": SCHEMA_VERSION,
        "python_version": python_version,
        "commit_sha": commit_sha,
        "coverage_version": coverage_version,
        "measured_at": measured_at or datetime.now(timezone.utc).isoformat(),
        "workflow_run_id": os.getenv("GITHUB_RUN_ID"),
        "workflow_run_attempt": os.getenv("GITHUB_RUN_ATTEMPT"),
        "event_name": os.getenv("GITHUB_EVENT_NAME"),
        "metrics": metrics,
    }


def validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != SCHEMA_VERSION:
        raise CoverageError("unsupported coverage manifest schema")
    for key in ("python_version", "commit_sha", "coverage_version", "measured_at"):
        if not isinstance(manifest.get(key), str) or not manifest[key]:
            raise CoverageError(f"manifest {key} is required")
    metrics = manifest.get("metrics")
    if not isinstance(metrics, dict):
        raise CoverageError("manifest metrics must be an object")
    counts = _summary_counts(metrics, name="manifest.metrics")
    if counts["num_statements"] == 0:
        raise CoverageError("manifest contains no executable statements")
    expected_line = _percentage(counts["covered_lines"], counts["num_statements"])
    expected_branch = _percentage(counts["covered_branches"], counts["num_branches"])
    if metrics.get("line_percent") != expected_line or metrics.get("branch_percent") != expected_branch:
        raise CoverageError("manifest percentages do not match the raw coverage counts")
    return manifest


def validate_matrix(directory: Path, expected_sha: str, *, policy: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    policy = policy or load_policy()
    manifests: dict[str, dict[str, Any]] = {}
    coverage_versions: set[str] = set()
    for path in directory.glob("coverage-*/coverage-manifest.json"):
        manifest = validate_manifest(load_json(path))
        version = manifest["python_version"]
        if version in manifests:
            raise CoverageError(f"duplicate coverage report for Python {version}")
        if manifest["commit_sha"] != expected_sha:
            raise CoverageError(f"Python {version} report was measured at {manifest['commit_sha']}, expected {expected_sha}")
        report_path = path.parent / "coverage.json"
        report = load_json(report_path)
        metrics = report_metrics(report)
        if metrics != manifest["metrics"]:
            raise CoverageError(f"Python {version} manifest does not match its coverage report")
        coverage_versions.add(manifest["coverage_version"])
        try:
            check_floors(metrics, policy)
        except CoverageError as exc:
            raise CoverageError(f"Python {version}: {exc}") from exc
        manifests[version] = manifest

    expected_versions = policy["python_versions"]
    if set(manifests) != set(expected_versions):
        missing = sorted(set(expected_versions) - set(manifests))
        extra = sorted(set(manifests) - set(expected_versions))
        raise CoverageError(f"coverage matrix mismatch: missing={missing}, extra={extra}")
    if len(coverage_versions) != 1:
        raise CoverageError(f"coverage matrix uses incompatible coverage.py versions: {sorted(coverage_versions)}")
    return [manifests[version] for version in expected_versions]


def write_github_summary(manifests: list[dict[str, Any]], path: Path) -> None:
    lines = ["### Coverage by Python version", "", "| Python | Lines | Branches | Statements | Branch destinations |", "| --- | ---: | ---: | ---: | ---: |"]
    for manifest in manifests:
        metrics = manifest["metrics"]
        lines.append(
            f"| {manifest['python_version']} | {metrics['line_percent']:.2f}% | "
            f"{metrics['branch_percent'] if metrics['branch_percent'] is not None else 'N/A'}"
            f"{'%' if metrics['branch_percent'] is not None else ''} | "
            f"{metrics['covered_lines']}/{metrics['num_statements']} | "
            f"{metrics['covered_branches']}/{metrics['num_branches']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _color(percent: float | None) -> str:
    if percent is None:
        return "#777777"
    if percent >= 90:
        return "#4c1"
    if percent >= 80:
        return "#dfb317"
    return "#e05d44"


def badge_svg(label: str, percent: float | None) -> str:
    """Return a Shields-compatible compact SVG badge."""
    value = "N/A" if percent is None else f"{percent:.2f}%"
    label = html.escape(label, quote=True)
    value = html.escape(value, quote=True)
    left = max(44, 6 * len(label) + 10)
    right = max(37, 6 * len(value) + 10)
    width = left + right
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="20" role="img" '
        f'aria-label="{label}: {value}"><title>{label}: {value}</title>'
        f'<linearGradient id="s" x2="0" y2="100%"><stop offset="0" stop-color="#bbb" stop-opacity=".1"/>'
        f'<stop offset="1" stop-opacity=".1"/></linearGradient>'
        f'<clipPath id="r"><rect width="{width}" height="20" rx="3" fill="#fff"/></clipPath>'
        f'<g clip-path="url(#r)"><path fill="#555" d="M0 0h{left}v20H0z"/>'
        f'<path fill="{_color(percent)}" d="M{left} 0h{right}v20H{left}z"/>'
        f'<path fill="url(#s)" d="M0 0h{width}v20H0z"/></g>'
        f'<g fill="#fff" text-anchor="middle" font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{left / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{label}</text>'
        f'<text x="{left / 2:.1f}" y="14">{label}</text>'
        f'<text x="{left + right / 2:.1f}" y="15" fill="#010101" fill-opacity=".3">{value}</text>'
        f'<text x="{left + right / 2:.1f}" y="14">{value}</text></g></svg>\n'
    )


def write_badges(manifest: Any, directory: Path) -> None:
    manifest = validate_manifest(manifest)
    directory.mkdir(parents=True, exist_ok=True)
    metrics = manifest["metrics"]
    (directory / "lines.svg").write_text(badge_svg("lines", metrics["line_percent"]), encoding="utf-8")
    (directory / "branches.svg").write_text(badge_svg("branches", metrics["branch_percent"]), encoding="utf-8")
    (directory / "metadata.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _command_report(args: argparse.Namespace) -> int:
    report = load_json(args.report)
    manifest = make_manifest(report, args.python, args.sha)
    policy = load_policy()
    check_floors(manifest["metrics"], policy)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.summary:
        write_github_summary([manifest], args.summary)
    branch = manifest["metrics"]["branch_percent"]
    print(f"Python {args.python}: lines {manifest['metrics']['line_percent']:.2f}%, branches {branch if branch is not None else 'N/A'}")
    return 0


def _command_matrix(args: argparse.Namespace) -> int:
    manifests = validate_matrix(args.directory, args.sha)
    if args.summary:
        write_github_summary(manifests, args.summary)
    for manifest in manifests:
        metrics = manifest["metrics"]
        print(f"Python {manifest['python_version']}: lines={metrics['line_percent']:.2f}% branches={metrics['branch_percent']}")
    return 0


def _command_badges(args: argparse.Namespace) -> int:
    write_badges(load_json(args.manifest), args.output)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="validate one coverage.py JSON report")
    report.add_argument("--report", type=Path, default=Path("coverage.json"))
    report.add_argument("--python", required=True)
    report.add_argument("--sha", default=os.getenv("GITHUB_SHA", "local"))
    report.add_argument("--manifest", type=Path, default=Path("coverage-manifest.json"))
    report.add_argument("--summary", type=Path, default=Path(os.getenv("GITHUB_STEP_SUMMARY", "")) if os.getenv("GITHUB_STEP_SUMMARY") else None)
    report.set_defaults(handler=_command_report)

    matrix = commands.add_parser("matrix", help="validate all version reports and write the CI summary")
    matrix.add_argument("--directory", type=Path, default=Path("coverage-artifacts"))
    matrix.add_argument("--sha", required=True)
    matrix.add_argument("--summary", type=Path, default=Path(os.getenv("GITHUB_STEP_SUMMARY", "")) if os.getenv("GITHUB_STEP_SUMMARY") else None)
    matrix.set_defaults(handler=_command_matrix)

    badges = commands.add_parser("badges", help="render SVG badges from a canonical manifest")
    badges.add_argument("--manifest", type=Path, required=True)
    badges.add_argument("--output", type=Path, required=True)
    badges.set_defaults(handler=_command_badges)

    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (CoverageError, OSError) as exc:
        print(f"coverage error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
