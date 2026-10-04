# Changesets

Add one Markdown file for each user-visible application or chart change that is
intended for a pifanctl v1 prerelease or release. The frontmatter names one or
more release streams and declares a SemVer bump. The body contains the release
category, scope, short title and a concise user-facing summary.

This repository uses Python application and Helm chart versions as its release
sources. The lightweight Changesets ledger does not invoke npm, modify versions,
or replace `scripts/check_version_bump.py`. A later release change consumes the
approved entries and updates the existing version files in a reviewed commit.

## Release streams

| Changeset name | Version source |
| --- | --- |
| `pifanctl` | `sources/pifanctl/__init__.py` |
| `pifanctl-chart` | `charts/pifanctl/Chart.yaml` |
| `pifanctl-operator` | `charts/pifanctl-operator/Chart.yaml` |

Use only the configured names and `patch`, `minor` or `major`. Categories are
`Feature`, `Fix`, `Security`, `Dependency`, `Documentation`, `Deprecated` and
`Removed`. Write summaries in English. CI validates every pending entry without
requiring Node.js or a second package manifest.

Changes that only modify CI, tests, internal release tooling or unreleased
documentation normally do not need a release entry. This branch includes one
because the requested v1 coverage capability is deliberately recorded as an
unreleased v1 changeset for review.

## Example

```md
---
"pifanctl": patch
"pifanctl-chart": patch
---

Feature(testing): Branch coverage reports

Report line and branch coverage independently across supported Python versions.
```
