"""
The release scripts run in CI where they cannot be tried by hand, and one of
them already broke the main build once, so they are tested with stand-ins for
docker, gh and helm.
"""
import os
import pathlib
import re
import stat
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import check_version_bump as bump  # noqa: E402

pytestmark = pytest.mark.skipif(os.name != "posix", reason="shell scripts")

TAG = re.compile(r"^ghcr\.io/jyje/pifanctl:[A-Za-z0-9_][A-Za-z0-9_.-]*$")


def shim(directory: pathlib.Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text("#!/usr/bin/env bash\n" + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def bin_dir(tmp_path):
    directory = tmp_path / "bin"
    directory.mkdir()
    return directory


def run(script: str, bin_dir, env: dict, cwd=ROOT, *args):
    full = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(cwd), **env}
    return subprocess.run([str(ROOT / "scripts" / script), *args], capture_output=True, text=True,
                          env=full, cwd=cwd)


# --- image tags --------------------------------------------------------------

def image_tags(bin_dir, exists: bool, **env):
    shim(bin_dir, "docker", "exit 0\n" if exists else "exit 1\n")
    return run("image-tags.sh", bin_dir, {"IMAGE": "ghcr.io/jyje/pifanctl", "SHORT_SHA": "abc1234", **env})


def test_every_output_line_is_a_valid_tag_even_when_the_release_exists(bin_dir):
    # The regression: a notice printed to stdout became part of the tag list
    # and the build failed with "invalid reference format".
    result = image_tags(bin_dir, exists=True, TAG_LATEST="true", TAG_RELEASE="true", VERSION="0.2.0")
    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert lines == ["ghcr.io/jyje/pifanctl:abc1234", "ghcr.io/jyje/pifanctl:latest"]
    assert all(TAG.match(line) for line in lines)
    assert "already exists" in result.stderr


def test_a_new_release_adds_the_version_tag(bin_dir):
    result = image_tags(bin_dir, exists=False, TAG_LATEST="true", TAG_RELEASE="true", VERSION="0.3.0")
    assert result.stdout.splitlines() == [
        "ghcr.io/jyje/pifanctl:abc1234", "ghcr.io/jyje/pifanctl:latest", "ghcr.io/jyje/pifanctl:v0.3.0"]


def test_branch_builds_only_get_the_commit_tag(bin_dir):
    result = image_tags(bin_dir, exists=False)
    assert result.stdout.splitlines() == ["ghcr.io/jyje/pifanctl:abc1234"]


def test_a_release_tag_needs_a_version(bin_dir):
    result = image_tags(bin_dir, exists=False, TAG_RELEASE="true")
    assert result.returncode != 0


# --- git tag and GitHub release ----------------------------------------------

@pytest.fixture
def repo(tmp_path, bin_dir):
    work = tmp_path / "work"
    (work / "sources" / "pifanctl").mkdir(parents=True)
    (work / "charts" / "pifanctl").mkdir(parents=True)
    (work / "sources" / "pifanctl" / "__init__.py").write_text('__version__ = "0.3.0"\n')
    (work / "charts" / "pifanctl" / "Chart.yaml").write_text("name: pifanctl\nversion: 0.1.3\nappVersion: \"0.3.0\"\n")
    # Ignore the developer's global git config: signing, hooks and default
    # branch settings must not decide whether this fixture builds.
    isolated = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    for command in (["init", "-q"], ["add", "."], ["commit", "-qm", "x"],
                    ["tag", "v0.2.0"], ["tag", "v0.0.1"], ["tag", "chart-v0.1.2"], ["tag", "other"]):
        subprocess.run(["git", *command], cwd=work, check=True, capture_output=True, env=isolated)
    log = tmp_path / "gh.log"
    shim(bin_dir, "gh", f'echo "$@" >> {log}\n[ "$1 $2" = "release view" ] && exit "${{GH_VIEW_EXIT:-1}}"\nexit 0\n')
    shim(bin_dir, "docker", 'exit "${PUBLISHED:-0}"\n')
    shim(bin_dir, "helm", 'exit "${PUBLISHED:-0}"\n')
    return work, log


ENV = {"GITHUB_SHA": "deadbeef", "GITHUB_REPOSITORY": "jyje/pifanctl", "GITHUB_REPOSITORY_OWNER": "jyje",
       "GH_TOKEN": "x"}


def release(repo, bin_dir, kind, **env):
    work, log = repo
    result = run("release.sh", bin_dir, {**ENV, **env}, work, kind)
    return result, (log.read_text() if log.exists() else "")


def test_app_release_is_created_from_the_previous_version_tag(repo, bin_dir):
    result, log = release(repo, bin_dir, "app")
    assert result.returncode == 0, result.stderr
    create = [line for line in log.splitlines() if line.startswith("release create")][0]
    assert "release create v0.3.0" in create
    assert "--target deadbeef" in create and "--generate-notes" in create
    assert "--notes-start-tag v0.2.0" in create  # not v0.0.1, not the chart tag
    assert "--latest=false" not in create


def test_chart_release_is_not_marked_latest_and_uses_chart_tags(repo, bin_dir):
    result, log = release(repo, bin_dir, "chart")
    assert result.returncode == 0, result.stderr
    create = [line for line in log.splitlines() if line.startswith("release create")][0]
    assert "release create chart-v0.1.3" in create
    assert "--notes-start-tag chart-v0.1.2" in create
    assert "--latest=false" in create


def test_an_existing_release_is_left_alone(repo, bin_dir):
    result, log = release(repo, bin_dir, "app", GH_VIEW_EXIT="0")
    assert result.returncode == 0
    assert "release create" not in log


def test_nothing_is_released_before_it_is_published(repo, bin_dir):
    result, log = release(repo, bin_dir, "app", PUBLISHED="1")
    assert result.returncode == 1
    assert "not published yet" in result.stdout
    assert "release create" not in log


def test_the_first_release_has_no_start_tag(repo, bin_dir):
    work, log = repo
    subprocess.run(["git", "tag", "-d", "chart-v0.1.2"], cwd=work, check=True, capture_output=True)
    result, text = release(repo, bin_dir, "chart")
    assert result.returncode == 0
    assert "--notes-start-tag" not in text


def test_alpha_image_never_moves_latest(bin_dir):
    result = image_tags(bin_dir, exists=False, TAG_LATEST='true', TAG_RELEASE='true', VERSION='1.0.0-alpha.1')
    assert result.returncode == 0
    assert not any(t.endswith(':latest') for t in result.stdout.splitlines())
    assert 'v1.0.0-alpha.1' in result.stdout


def test_alpha_release_is_prerelease(repo, bin_dir):
    work, _ = repo
    (work / 'sources/pifanctl/__init__.py').write_text('__version__ = "1.0.0-alpha.1"\n')
    result, text = release(repo, bin_dir, 'app')
    assert result.returncode == 0
    assert '--prerelease' in text and '--latest=false' in text


def test_operator_chart_has_distinct_release_tag(repo, bin_dir):
    work, _ = repo
    path = work / 'charts/pifanctl-operator'; path.mkdir()
    (path / 'Chart.yaml').write_text('version: 0.1.0-alpha.1\n')
    result, text = release(repo, bin_dir, 'chart', CHART_NAME='pifanctl-operator')
    assert result.returncode == 0, result.stderr
    assert 'release create operator-chart-v0.1.0-alpha.1' in text
    assert '--prerelease' in text


# --- version bump check ------------------------------------------------------

APP = ["sources/pifanctl/control.py"]
CHART = ["charts/pifanctl/values.yaml"]
CHART_FILE = "charts/pifanctl/Chart.yaml"
OPERATOR_CHART_FILE = "charts/pifanctl-operator/Chart.yaml"
OLD_CHARTS = {CHART_FILE: "0.1.0", OPERATOR_CHART_FILE: "0.1.0"}
NEW_CHARTS = dict(OLD_CHARTS)


def test_a_docs_only_change_needs_no_version():
    assert bump.check(["README.md", "tests/test_cli.py", "docs/x.md"], "0.2.0", "0.2.0", OLD_CHARTS, NEW_CHARTS) == []


def test_changing_the_application_requires_a_new_version():
    errors = bump.check(APP, "0.2.0", "0.2.0", OLD_CHARTS, NEW_CHARTS)
    assert len(errors) == 1 and "__version__" in errors[0]


def test_changing_the_cli_entry_point_counts_as_the_application():
    assert bump.check(["sources/main.py"], "0.2.0", "0.2.0", OLD_CHARTS, NEW_CHARTS)


def test_changing_the_chart_requires_a_new_chart_version():
    errors = bump.check(CHART, "0.2.0", "0.2.0", OLD_CHARTS, NEW_CHARTS)
    assert len(errors) == 1 and "chart" in errors[0]


def test_chart_test_value_sets_do_not_count_as_the_chart():
    assert bump.check(["charts/pifanctl/ci/default-values.yaml"], "0.2.0", "0.2.0", OLD_CHARTS, NEW_CHARTS) == []


def test_a_proper_release_passes():
    changed_charts = {**OLD_CHARTS, CHART_FILE: "0.1.1"}
    assert bump.check(APP + CHART + [CHART_FILE], "0.2.0", "0.3.0", OLD_CHARTS, changed_charts) == []


def test_app_version_can_advance_without_a_chart_release():
    assert bump.check(APP, "0.2.0", "0.3.0", OLD_CHARTS, NEW_CHARTS) == []


def test_chart_versions_advance_independently():
    changed = ["charts/pifanctl-operator/templates/extra-resources.yaml"]
    bumped = {**OLD_CHARTS, OPERATOR_CHART_FILE: "0.1.1"}
    assert bump.check(changed, "0.2.0", "0.2.0", OLD_CHARTS, bumped) == []


def test_each_changed_chart_requires_its_own_version_bump():
    changed = ["charts/pifanctl-operator/templates/extra-resources.yaml"]
    errors = bump.check(changed, "0.2.0", "0.2.0", OLD_CHARTS, NEW_CHARTS)
    assert len(errors) == 1 and OPERATOR_CHART_FILE in errors[0]


def test_bumping_one_chart_does_not_require_bumping_the_other():
    changed = ["charts/pifanctl-operator/templates/extra-resources.yaml"]
    bumped = {**OLD_CHARTS, OPERATOR_CHART_FILE: "0.1.1"}
    assert bump.check(changed, "0.2.0", "0.2.0", OLD_CHARTS, bumped) == []


def test_chart_release_workflow_publishes_only_the_v1_operator_chart():
    workflow = (ROOT / '.github/workflows/release-chart.yaml').read_text()
    assert 'CHART_NAME: pifanctl-operator' in workflow
    assert 'charts/pifanctl-operator/**' in workflow
    assert 'charts/pifanctl/**' not in workflow
    assert "sed -n 's/^appVersion: //p'" in workflow
    assert 'helm show chart "charts/${CHART_NAME}"' in workflow


def test_versions_are_read_from_the_files():
    assert bump.app_version('"""x"""\n__version__ = "1.2.3"\n') == "1.2.3"
    assert bump.chart_version("name: x\nversion: 0.1.2\nappVersion: \"0.2.0\"\n") == "0.1.2"
    assert bump.chart_version("version: '0.4.0'\n") == "0.4.0"


@pytest.mark.parametrize('python_version,release,expected', [
    ('3.14', 'false', 'abc1234'), ('3.12', 'false', 'abc1234-py312'),
    ('3.12', 'true', 'abc1234-py312'), ('3.13', 'true', None), ('4.0', 'false', None),
])
def test_python_variant_tags(tmp_path, python_version, release, expected):
    import yaml
    workflow = yaml.safe_load((ROOT / '.github/workflows/_build-image.yaml').read_text())
    job = workflow['jobs']['build-and-testing']
    script = next(s['run'] for s in job['steps'] if s.get('id') == 'tags')
    (tmp_path / 'sources/pifanctl').mkdir(parents=True)
    (tmp_path / 'sources/pifanctl/__init__.py').write_text('__version__ = "1.0.0-alpha.1"\n')
    (tmp_path / 'scripts').mkdir()
    shim(tmp_path / 'scripts', 'image-tags.sh', 'echo "${IMAGE}:${SHORT_SHA}"\necho "${IMAGE}:v${VERSION}"\n')
    output = tmp_path / 'output'
    env = {**os.environ, 'PYTHON_VERSION': python_version, 'TAG_LATEST': 'false',
           'TAG_RELEASE': release, 'GITHUB_SHA': 'abc123456789', 'GITHUB_OUTPUT': str(output),
           'IMAGE': 'ghcr.io/jyje/pifanctl-issue'}
    result = subprocess.run(['bash', '-c', script], env=env, cwd=tmp_path, capture_output=True, text=True)
    if expected is None:
        assert result.returncode != 0
        assert not output.exists()
    else:
        assert result.returncode == 0, result.stderr
        assert (tmp_path / 'sources/version').read_text().strip() == expected
        assert 'short_sha=' + expected in output.read_text()
        assert 'ghcr.io/jyje/pifanctl-issue:' + expected in output.read_text()
        variant = '' if python_version == '3.14' else '-py' + python_version.replace('.', '')
        assert 'v1.0.0-alpha.1' + variant in output.read_text()
    build = next(s for s in job['steps'] if s.get('uses', '').startswith('docker/build-push-action@'))
    assert build['with']['build-args'] == 'PYTHON_VERSION=${{ inputs.python-version }}'


def test_main_release_requires_canonical_and_compatibility_images():
    import yaml
    workflow = yaml.safe_load((ROOT / '.github/workflows/build-image-main.yaml').read_text())
    jobs = workflow['jobs']
    assert jobs['build-compatibility']['with']['python-version'] == '3.12'
    assert jobs['build-compatibility']['with']['tag-release'] is True
    assert jobs['build-compatibility']['with']['tag-latest'] is False
    assert set(jobs['release']['needs']) == {'build', 'build-compatibility'}
    assert "needs.build-compatibility.result == 'success'" in jobs['release']['if']


@pytest.mark.parametrize('exists', [False, True])
def test_compatibility_release_tag_is_immutable_and_never_latest(bin_dir, exists):
    result = image_tags(bin_dir, exists=exists, TAG_LATEST='false',
                        TAG_RELEASE='true', VERSION='1.0.0-py312')
    assert result.returncode == 0
    expected = ['ghcr.io/jyje/pifanctl:abc1234']
    if not exists:
        expected.append('ghcr.io/jyje/pifanctl:v1.0.0-py312')
    assert result.stdout.splitlines() == expected
    assert ':latest' not in result.stdout
