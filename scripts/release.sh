#!/usr/bin/env bash
# Creates the git tag and GitHub release for a version that is already
# published, once. Safe to run on every push to main.
#
#   scripts/release.sh app   -> v<__version__>,         needs the image
#   scripts/release.sh chart -> chart-v<Chart.yaml version>, needs the chart
#
# Environment: GITHUB_SHA, GH_TOKEN, GITHUB_REPOSITORY, GITHUB_REPOSITORY_OWNER
set -euo pipefail

kind="${1:?usage: release.sh app|chart}"
image="ghcr.io/${GITHUB_REPOSITORY}"

case "${kind}" in
  app)
    version="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' sources/pifanctl/__init__.py)"
    tag="v${version}"
    pattern='v[0-9]*'
    title="pifanctl ${tag}"
    published() { docker buildx imagetools inspect "${image}:${tag}" >/dev/null 2>&1; }
    ;;
  chart)
    version="$(sed -n "s/^version: *['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" charts/pifanctl/Chart.yaml)"
    tag="chart-v${version}"
    pattern='chart-v*'
    title="Helm chart ${version}"
    published() {
      helm show chart "oci://ghcr.io/${GITHUB_REPOSITORY_OWNER}/charts/pifanctl" --version "${version}" >/dev/null 2>&1
    }
    ;;
  *) echo "unknown kind: ${kind}" >&2; exit 2 ;;
esac

[ -n "${version}" ] || { echo "could not read the ${kind} version" >&2; exit 1; }

if gh release view "${tag}" >/dev/null 2>&1; then
  echo "${tag} is already released"
  exit 0
fi

if ! published; then
  echo "::error::${tag} is not published yet, so it is not released"
  exit 1
fi

previous="$(git tag --list "${pattern}" --sort=-v:refname | grep -v -x "${tag}" | head -n1 || true)"
args=(--target "${GITHUB_SHA}" --title "${title}" --generate-notes)
[ -z "${previous}" ] || args+=(--notes-start-tag "${previous}")
[ "${kind}" = "app" ] || args+=(--latest=false)

gh release create "${tag}" "${args[@]}"
echo "released ${tag}"
