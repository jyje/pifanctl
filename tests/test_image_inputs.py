import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import image_inputs  # noqa: E402


@pytest.mark.parametrize("path", [
    "sources/pifanctl/topology/kube.py",
    "sources/requirements.common.txt",
    "sources/main.py",
    "docker/all.dockerfile",
    "docker/raspi.dockerfile",
    ".dockerignore",
    ".github/workflows/ci.yaml",
])
def test_paths_that_can_change_the_image(path):
    assert image_inputs.affects_image([path])


@pytest.mark.parametrize("path", [
    ".github/dependabot.yaml",
    "renovate.json5",
    ".github/workflows/build-image-main.yaml",
    ".github/workflows/release-chart.yaml",
    "charts/pifanctl-operator/values.yaml",
    "tests/test_cli.py",
    "scripts/check_version_bump.py",
    "docs/v1/runtime.md",
    "design/v1/README.md",
    "README.md",
    "PLAN.md",
    "CHANGELOG.md",
    ".changeset/example.md",
    "assets/coverage/lines.svg",
    "sourcesx/file.py",
    "mydocker/file",
])
def test_paths_that_cannot_change_the_image(path):
    assert not image_inputs.affects_image([path])


def test_one_relevant_file_among_many_is_enough():
    assert image_inputs.affects_image(["docs/a.md", "PLAN.md", "sources/pifanctl/__init__.py"])
    assert not image_inputs.affects_image([])


# File lists of real pull requests (abridged), to keep the rules honest.
@pytest.mark.parametrize("files,expected", [
    ([".github/dependabot.yaml"], False),                                   # #101
    (["PLAN.md", "docs/v1/runtime.md"], False),                             # #99
    (["sources/pifanctl/topology/kube.py", "sources/requirements.common.txt",
      "tests/test_topology_cli.py", ".changeset/kubernetes-client-37.md"], True),  # #97
    (["charts/pifanctl-operator/templates/rbac.yaml", "docs/v1/runtime.md",
      "sources/pifanctl/topology/operator.py"], True),                      # #89
    (["sources/requirements.common.txt", "sources/requirements.dev.txt"], True),  # dependency bump
    (["renovate.json5"], False),
])
def test_real_pull_request_file_lists(files, expected):
    assert image_inputs.affects_image(files) is expected


def test_changed_files_and_main_use_the_merge_base_diff(monkeypatch, capsys):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="docs/a.md\0sources/x.py\0", stderr="")

    monkeypatch.setattr(image_inputs.subprocess, "run", fake_run)
    assert image_inputs.changed_files("origin/main") == ["docs/a.md", "sources/x.py"]
    assert calls[0] == ["git", "diff", "--name-only", "-z", "origin/main...HEAD"]
    assert image_inputs.main("origin/main") == 0
    assert capsys.readouterr().out == "image=true\n"
    monkeypatch.setattr(image_inputs, "changed_files", lambda base: ["docs/a.md"])
    image_inputs.main("origin/main")
    assert capsys.readouterr().out == "image=false\n"


def test_cli_requires_exactly_one_base_ref():
    result = subprocess.run([sys.executable, str(ROOT / "scripts/image_inputs.py")], capture_output=True, text=True)
    assert result.returncode != 0 and "image_inputs.py <base-ref>" in result.stderr


def test_ci_builds_the_image_only_after_the_inputs_check():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yaml").read_text())
    check, build = workflow["jobs"]["image-inputs"], workflow["jobs"]["image"]
    assert check["runs-on"] == "ubuntu-26.04"
    assert check["outputs"] == {"image": "${{ steps.inputs.outputs.image }}"}
    assert build["needs"] == "image-inputs"
    assert build["runs-on"]["labels"] == "r4spi-microk8s"
    assert "head.repo.full_name == github.repository" in build["if"]
    assert "needs.image-inputs.outputs.image == 'true'" in build["if"]
    assert "head.repo.full_name == github.repository" in check["if"]
