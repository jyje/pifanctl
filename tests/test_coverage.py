import json
from pathlib import Path
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import check_changesets
import coverage_metrics as coverage


SHA = "a" * 40


def report(*, branch_coverage=True, statements=10, covered=9, branches=4, covered_branches=3, path="sources/pifanctl/control.py"):
    totals = {
        "covered_lines": covered,
        "num_statements": statements,
        "covered_branches": covered_branches,
        "num_branches": branches,
    }
    return {
        "meta": {"version": "7.16.2", "branch_coverage": branch_coverage},
        "files": {path: {"summary": dict(totals)}},
        "totals": dict(totals),
    }


def test_report_calculates_line_and_branch_coverage_independently():
    metrics = coverage.report_metrics(report())
    assert metrics["line_percent"] == 90
    assert metrics["branch_percent"] == 75


def test_branch_collection_must_be_enabled():
    with pytest.raises(coverage.CoverageError, match="branch coverage"):
        coverage.report_metrics(report(branch_coverage=False))


def test_empty_application_report_is_rejected():
    data = report()
    data["files"] = {}
    with pytest.raises(coverage.CoverageError, match="no application files"):
        coverage.report_metrics(data)


def test_missing_matrix_report_is_rejected(tmp_path):
    artifact = tmp_path / "coverage-3.10"
    artifact.mkdir()
    data = report()
    manifest = coverage.make_manifest(data, "3.10", SHA, measured_at="2026-10-04T00:00:00+00:00")
    (artifact / "coverage-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(coverage.CoverageError, match="coverage report not found"):
        coverage.validate_matrix(
            tmp_path,
            SHA,
            policy={"python_versions": ["3.10"], "line_floor_percent": 90},
        )


def test_malformed_json_report_is_rejected(tmp_path):
    report_path = tmp_path / "coverage.json"
    report_path.write_text("{invalid", encoding="utf-8")
    with pytest.raises(coverage.CoverageError, match="invalid JSON coverage report"):
        coverage.load_json(report_path)


def test_report_totals_must_match_file_summaries():
    data = report()
    data["totals"]["covered_branches"] -= 1
    with pytest.raises(coverage.CoverageError, match="totals do not match"):
        coverage.report_metrics(data)


def test_non_application_path_is_rejected():
    with pytest.raises(coverage.CoverageError, match="unexpected application path"):
        coverage.report_metrics(report(path="tests/test_control.py"))


def test_zero_branch_denominator_is_not_reported_as_full_coverage():
    metrics = coverage.report_metrics(report(branches=0, covered_branches=0))
    assert metrics["branch_percent"] is None


@pytest.mark.parametrize("covered, statements, succeeds", [(9, 10, True), (8999, 10000, False), (10, 10, True)])
def test_line_floor_uses_raw_ratio(covered, statements, succeeds):
    metrics = coverage.report_metrics(report(covered=covered, statements=statements))
    if succeeds:
        coverage.check_line_floor(metrics, 90)
    else:
        with pytest.raises(coverage.CoverageError, match="below 90%"):
            coverage.check_line_floor(metrics, 90)


def test_line_floor_does_not_round_a_below_threshold_report_up():
    metrics = {
        "covered_lines": 1_799_999,
        "num_statements": 2_000_000,
        "line_percent": 90.0,
    }
    with pytest.raises(coverage.CoverageError, match="below 90%"):
        coverage.check_line_floor(metrics, 90)


def write_artifact(directory: Path, version: str, *, sha=SHA, coverage_version="7.16.2"):
    artifact = directory / f"coverage-{version}"
    artifact.mkdir(parents=True)
    data = report()
    data["meta"]["version"] = coverage_version
    (artifact / "coverage.json").write_text(json.dumps(data), encoding="utf-8")
    manifest = coverage.make_manifest(data, version, sha, measured_at="2026-10-04T00:00:00+00:00")
    (artifact / "coverage-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_matrix_requires_all_supported_versions_and_a_single_revision(tmp_path):
    policy = {"python_versions": ["3.10", "3.11"], "line_floor_percent": 90}
    write_artifact(tmp_path, "3.10")
    write_artifact(tmp_path, "3.11")
    manifests = coverage.validate_matrix(tmp_path, SHA, policy=policy)
    assert [item["python_version"] for item in manifests] == policy["python_versions"]


def test_matrix_rejects_missing_version(tmp_path):
    write_artifact(tmp_path, "3.10")
    with pytest.raises(coverage.CoverageError, match="matrix mismatch"):
        coverage.validate_matrix(tmp_path, SHA, policy={"python_versions": ["3.10", "3.11"], "line_floor_percent": 90})


def test_matrix_rejects_report_from_a_different_commit(tmp_path):
    write_artifact(tmp_path, "3.10", sha="b" * 40)
    with pytest.raises(coverage.CoverageError, match="expected"):
        coverage.validate_matrix(tmp_path, SHA, policy={"python_versions": ["3.10"], "line_floor_percent": 90})


def test_matrix_rejects_incompatible_coverage_versions(tmp_path):
    write_artifact(tmp_path, "3.10")
    write_artifact(tmp_path, "3.11", coverage_version="7.15.0")
    with pytest.raises(coverage.CoverageError, match="incompatible coverage.py versions"):
        coverage.validate_matrix(
            tmp_path,
            SHA,
            policy={"python_versions": ["3.10", "3.11"], "line_floor_percent": 90},
        )


def test_badges_include_independent_metrics_and_provenance(tmp_path):
    manifest = coverage.make_manifest(report(), "3.14", SHA, measured_at="2026-10-04T00:00:00+00:00")
    coverage.write_badges(manifest, tmp_path)
    assert "90.00%" in (tmp_path / "lines.svg").read_text()
    assert "75.00%" in (tmp_path / "branches.svg").read_text()
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert metadata["commit_sha"] == SHA
    assert metadata["measured_at"] == "2026-10-04T00:00:00+00:00"


def test_badge_text_is_escaped():
    svg = coverage.badge_svg('<script>', 100)
    assert "&lt;script&gt;" in svg
    assert "<script>" not in svg


def test_changeset_ledger_configures_existing_release_streams():
    config = check_changesets.load_config()
    assert set(config["release_streams"]) == {"pifanctl", "pifanctl-chart", "pifanctl-operator"}
    entries = check_changesets.validate(ROOT / ".changeset", config)
    assert {path.name for path in entries} >= {"branch-coverage-v1.md"}


def test_changeset_rejects_unknown_release_stream():
    with pytest.raises(check_changesets.ChangesetError, match="unknown release stream"):
        check_changesets.parse_entry(
            '---\n"unknown": patch\n---\n\nFeature(testing): Coverage\n\nAdd a release summary.',
            streams={"pifanctl"}, bump_types={"patch", "minor", "major"},
            categories={"Feature", "Fix"},
        )


def test_ci_matrix_matches_policy_and_keeps_line_gate_separate():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())
    policy = coverage.load_policy()
    test_job = workflow["jobs"]["test"]
    assert test_job["strategy"]["matrix"]["python"] == policy["python_versions"]
    run_commands = "\n".join(step.get("run", "") for step in test_job["steps"])
    assert "--cov-branch" in run_commands
    assert "--cov-fail-under" not in run_commands
    assert policy["line_floor_percent"] == 90


def test_coverage_actions_remain_outside_the_arm_runner():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())
    assert workflow["jobs"]["test"]["runs-on"] == "ubuntu-26.04"
    assert "if" in workflow["jobs"]["publish-badges"]
    assert "github.event_name == 'push'" in workflow["jobs"]["publish-badges"]["if"]
    assert workflow["jobs"]["publish-badges"]["permissions"]["contents"] == "write"
    publisher_run = "\n".join(
        step.get("run", "") for step in workflow["jobs"]["publish-badges"]["steps"]
    )
    assert "--output assets/coverage" in publisher_run
    assert "git push origin HEAD:main" in publisher_run
    assert "coverage-badges" not in publisher_run
    for readme in ("README.md", "README-ko.md"):
        content = (ROOT / readme).read_text()
        assert "assets/coverage/lines.svg" in content
        assert "assets/coverage/branches.svg" in content
    assert workflow["jobs"]["image"]["runs-on"]["labels"] == "r4spi-microk8s"
    codecov_job = workflow["jobs"]["codecov"]
    assert "github.ref == 'refs/heads/main'" in codecov_job["if"]
    assert "github.event.pull_request.head.repo.full_name == github.repository" in codecov_job["if"]
    assert "github.actor != 'dependabot[bot]'" in codecov_job["if"]
    assert codecov_job["permissions"] == {"contents": "read"}
    codecov_step = codecov_job["steps"][-1]
    assert codecov_step["with"]["token"] == "${{ secrets.CODECOV_TOKEN }}"
    assert codecov_step["uses"] == "codecov/codecov-action@0fb7174895f61a3b6b78fc075e0cd60383518dac"
