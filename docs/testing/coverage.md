# Python coverage

CI measures every application file in `sources/` on Python 3.14. Line and
branch floors are both 100%, checked independently using exact counts. A missing
report or branch denominator cannot pass the gate. Coverage includes the legacy
software paths still shipped in the application.

The measurement core is explicitly `ctrace` in `.coveragerc`. Coverage.py defaults
to `sysmon` on Python 3.14. Cross-measuring the same suite showed different
branch accounting for generator exhaustion and exception transitions. Pinning
one supported core keeps local, CI and badge measurements consistent without
changing the source set or adding coverage exclusions. See the
[coverage.py core documentation](https://coverage.readthedocs.io/en/7.16.2/config.html#run-core)
and the [meaningful coverage audit](coverage-audit.md).

## Run locally

`pytest`, `pytest-cov`, and `coverage` are pinned in
`sources/requirements.dev.txt`, separate from the application runtime
dependencies. Install that project-level development requirements file locally
with `python -m pip install -r sources/requirements.dev.txt`. CI installs the
same file before running the coverage command below:

```sh
python -m pytest --cov=sources --cov-config=.coveragerc --cov-branch \
  --cov-report=term-missing --cov-report=xml:coverage.xml \
  --cov-report=json:coverage.json --cov-report=html:coverage-html
python scripts/coverage_metrics.py report --report coverage.json --python "$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
```

The JSON report includes exact line and branch counts. `coverage-html/` shows
missing branch destinations. A zero-branch source set is reported as `N/A`.

Run `python scripts/check_changesets.py` to validate the pending v1 release
ledger. Changesets record proposed version-stream updates; app and chart version
files remain the actual release sources until a reviewed release change
consumes an entry.

## CI and Codecov

Every matrix job saves its JSON, XML, HTML and a manifest containing the tested
revision, Python version, coverage.py version, counts and timestamp. The
`Coverage quality` check requires one valid report from every supported Python
version at the same revision. It applies the 100% line and branch floors independently of
the coverage.py combined total.

Python 3.14 is the canonical Codecov report because the default runtime image
uses Python 3.14. Codecov receives this report once per workflow run. Its project
and patch statuses require 100% coverage with zero tolerance. Missing head reports
fail; uploads do not carry forward old flag data. Codecov upload errors fail the
authorized upload job, and local matrix quality checks remain mandatory.

Repository owners must enable the pifanctl repository in Codecov for PR
annotations and Codecov's native project view. Main and same-repository PR
uploads use the repository-scoped `CODECOV_TOKEN` Actions secret. Fork and
Dependabot PRs do not upload because GitHub withholds repository secrets.
Upload errors fail the upload job; the local coverage gates also remain required.
The first OIDC upload in PR #43 returned `Repository not found`. The workflow
now uses the configured repository upload token instead.

## Coverage badges

After a successful main CI run, the publisher updates
`assets/coverage/lines.svg`, `assets/coverage/branches.svg` and
`assets/coverage/metadata.json` in the repository. The metadata identifies the
exact main commit and measurement time. The publisher checks that main has not
advanced before updating the assets. A failed run retains the last successful
badges and their original measurement metadata. Asset-only pushes are excluded
from the main CI trigger. Fork pull requests can produce reports and artifacts
but cannot publish badges. The README uses Codecov's official main-branch status
badge for the canonical Python 3.14 report. The line and branch SVGs remain
available as detailed coverage assets.

## Interpreting branch coverage

Branch coverage counts source-to-destination paths for conditional code. It is
not complete Boolean condition coverage, MC/DC, concurrency proof or physical
fan validation. Keep selected safety scenarios explicit in tests and validate
hardware and fail-open behavior separately. Do not add coverage exclusions to obtain a green result. Mock only hardware,
remote IO, unavailable faults or scheduling that cannot be tested safely and
deterministically. Pure model/planner/control functions must run unchanged.

The per-version branch baseline is intentionally measured before a threshold is
chosen. Update `coverage-policy.json` in a reviewed change after checking the
report artifacts. Never infer branch coverage from an earlier line-only result.

## Normal results and repeated warnings

Codecov keeps a complete PR summary with project, patch, flag and file results.
The default comment behavior updates one report as the head changes. Both head
and base reports are required. Native `codecov/project` and `codecov/patch`
checks enforce the configured targets; a passing 95% patch does not mean 100%
coverage. Actual partial branches remain visible and require review.

The project score uses Codecov hit/partial/miss classifications and differs from
coverage.py's separately calculated line and branch percentages. Always label
these metrics explicitly. Fix meaningful missing scenarios when reviewing them;
never exclude a line merely to improve the displayed percentage.

Reports compare tested source revisions. Automatic main coverage-badge commits
only update `assets/coverage` and do not trigger a recursive CI run. The publisher
runs the canonical Python 3.14 suite again on the actual newly created commit,
then uploads the fresh XML with that commit SHA. It never relabels the previous
source commit's XML. This supplies the missing base report that caused historical
one-commit main lag warnings. If no badge commit is created, no extra test/upload
is needed. Publication or upload failures remain visible in the publisher job.

Fork and Dependabot uploads remain intentionally excluded from secret-bearing
upload jobs. Their local test/matrix checks still run; never treat an absent
Codecov check as affirmative coverage evidence. Required checks in GitHub branch
protection are a separate repository setting.

References: [Codecov status configuration](https://docs.codecov.com/docs/commit-status)
and [PR summary comments](https://docs.codecov.com/docs/pull-request-comments).
