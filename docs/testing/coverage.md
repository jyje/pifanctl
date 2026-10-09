# Python coverage

The CI measures the application in `sources/` on Python 3.14 only. It collects line and branch data in one test run, then reports both
metrics separately. The existing 90% line floor remains required for each
supported runtime. Branch coverage is reported; no branch threshold is currently
configured.

Historical baseline: an initial local macOS run passed all 255 tests on Python 3.10-3.14. Python
3.10-3.13 measured 95.71% line and 88.9734% branch coverage; Python 3.14
measured 95.69% line and 88.0228% branch coverage. The first GitHub Actions
matrix on PR #43 passed all 259 tests and measured 95.75-95.77% line and
88.2129-89.1635% branch coverage. This PR is the first CI baseline. Keep the
branch floor unset until a successful main baseline and missing-path review.

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
version at the same revision. It applies the 90% line floor independently of
the coverage.py combined total.

Python 3.14 is the canonical Codecov report because the default runtime image
uses Python 3.14. Codecov receives this report once per workflow run. Its project
and 95% patch statuses enforce the configured policy. Project coverage may drop
by at most 0.1 percentage points from the comparison base. Missing head reports
fail; uploads do not carry forward old flag data. Codecov upload errors fail the
authorized upload job, and local matrix quality checks remain mandatory.

Repository owners must enable the pifanctl repository in Codecov for PR
annotations and Codecov's native project view. Main and same-repository PR
uploads use the repository-scoped `CODECOV_TOKEN` Actions secret. Fork and
Dependabot PRs do not upload because GitHub withholds repository secrets.
Upload errors remain non-blocking; the local coverage gates stay authoritative.
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
hardware and fail-open behavior separately. Add `no cover` or `no branch`
exclusions only with a specific reviewed reason.

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
