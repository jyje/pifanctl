from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github/workflows"


def load(name):
    workflow = yaml.safe_load((WORKFLOWS / name).read_text())
    workflow["triggers"] = workflow.pop(True, workflow.get("on"))  # YAML reads a bare `on` as True
    return workflow


def test_pull_request_image_build_filters_by_the_files_the_image_is_built_from():
    workflow = load("ci-image.yaml")
    assert workflow["triggers"]["pull_request"]["paths"] == [
        "sources/**", "docker/**", ".dockerignore", ".github/workflows/ci-image.yaml"]
    job = workflow["jobs"]["image"]
    assert job["name"] == "🐳 Image (ARM64, in-cluster runner)"
    assert job["runs-on"]["labels"] == "r4spi-microk8s"
    assert "head.repo.full_name == github.repository" in job["if"]
    assert workflow["permissions"] == {"contents": "read"}
    steps = "\n".join(step.get("run", "") for step in job["steps"])
    assert "python -m pifanctl.hardware_smoke" in steps


def test_the_general_ci_workflow_no_longer_builds_an_image():
    assert "image" not in load("ci.yaml")["jobs"]


def test_publish_workflows_cover_every_input_of_the_pull_request_build():
    # The pull request build and the publish builds must agree on what the image depends on.
    for name in ("build-image-main.yaml", "build-image-develop.yaml", "build-image-issue.yaml"):
        paths = load(name)["triggers"]["push"]["paths"]
        assert "sources/**" in paths and "docker/all.dockerfile" in paths
