#!/usr/bin/env bash
# Prints the image tags to publish, one per line, and nothing else.
#
# Everything that is not a tag goes to stderr: this output is written straight
# into a build step's `tags` input, so a stray line becomes an invalid tag.
#
# Environment:
#   IMAGE         image name without a tag, for example ghcr.io/jyje/pifanctl
#   SHORT_SHA     commit tag
#   TAG_LATEST    "true" to also publish `latest`
#   TAG_RELEASE   "true" to also publish v<version> when it does not exist yet
#   VERSION       the application version, required with TAG_RELEASE
set -euo pipefail

: "${IMAGE:?}" "${SHORT_SHA:?}"

echo "${IMAGE}:${SHORT_SHA}"

if [ "${TAG_LATEST:-false}" = "true" ] && [[ "${VERSION:-}" != *-* ]]; then
  echo "${IMAGE}:latest"
fi

if [ "${TAG_RELEASE:-false}" = "true" ]; then
  : "${VERSION:?VERSION is required with TAG_RELEASE}"
  # A release tag is published once. Later commits of the same version only
  # move `latest` and their own commit tag.
  if docker buildx imagetools inspect "${IMAGE}:v${VERSION}" >/dev/null 2>&1; then
    echo "${IMAGE}:v${VERSION} already exists, leaving it untouched" >&2
  else
    echo "${IMAGE}:v${VERSION}"
  fi
fi
