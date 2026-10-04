"""Validate pending user-facing changesets for the application and Helm charts."""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / ".changeset" / "config.json"
ENTRY = re.compile(r"^(Feature|Fix|Security|Dependency|Documentation|Deprecated|Removed)\(([a-z0-9-]+)\): .+$")


class ChangesetError(ValueError):
    """Raised when a pending changeset is incomplete or references no release stream."""


def load_config(path: Path = CONFIG) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ChangesetError(f"cannot read changeset configuration: {path}") from exc
    if not isinstance(config, dict) or config.get("schema_version") != 1:
        raise ChangesetError("unsupported changeset configuration schema")
    streams = config.get("release_streams")
    if not isinstance(streams, dict) or not streams:
        raise ChangesetError("changeset release_streams must be a non-empty object")
    for name, source in streams.items():
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+", name):
            raise ChangesetError(f"invalid release stream name: {name!r}")
        if not isinstance(source, str) or not (ROOT / source).is_file():
            raise ChangesetError(f"release stream {name!r} has no version source")
    if not isinstance(config.get("bump_types"), list) or not config["bump_types"]:
        raise ChangesetError("changeset bump_types must be a non-empty list")
    if not isinstance(config.get("categories"), list) or not config["categories"]:
        raise ChangesetError("changeset categories must be a non-empty list")
    return config


def parse_entry(text: str, *, streams: set[str], bump_types: set[str], categories: set[str]) -> dict[str, str]:
    if not text.startswith("---\n"):
        raise ChangesetError("frontmatter must start at the beginning of the file")
    try:
        _, frontmatter, body = text.split("---", maxsplit=2)
    except ValueError as exc:
        raise ChangesetError("changeset frontmatter must have closing delimiters") from exc
    payload = yaml.safe_load(frontmatter)
    if not isinstance(payload, dict) or not payload:
        raise ChangesetError("frontmatter must list at least one release stream")
    if any(name not in streams for name in payload):
        unknown = sorted(str(name) for name in payload if name not in streams)
        raise ChangesetError(f"unknown release stream(s): {', '.join(unknown)}")
    if any(level not in bump_types for level in payload.values()):
        raise ChangesetError(f"bump levels must be one of: {', '.join(sorted(bump_types))}")
    paragraphs = [part.strip() for part in body.strip().split("\n\n") if part.strip()]
    if len(paragraphs) < 2:
        raise ChangesetError("changeset body must include a category line and a release summary")
    match = ENTRY.fullmatch(paragraphs[0])
    if not match or match.group(1) not in categories:
        raise ChangesetError("first body paragraph must use an allowed Category(scope): Title")
    if not paragraphs[1].strip():
        raise ChangesetError("release summary cannot be empty")
    return {"category": match.group(1), "scope": match.group(2), "title": paragraphs[0].split(": ", 1)[1]}


def validate(directory: Path, config: dict[str, Any] | None = None) -> list[Path]:
    config = config or load_config()
    streams = set(config["release_streams"])
    bump_types = set(config["bump_types"])
    categories = set(config["categories"])
    entries = sorted(path for path in directory.glob("*.md") if path.name != "README.md")
    for path in entries:
        try:
            parse_entry(path.read_text(encoding="utf-8"), streams=streams, bump_types=bump_types, categories=categories)
        except (OSError, yaml.YAMLError) as exc:
            raise ChangesetError(f"invalid changeset {path.name}: {exc}") from exc
    return entries


def main() -> int:
    try:
        entries = validate(ROOT / ".changeset")
    except ChangesetError as exc:
        print(f"changeset error: {exc}", file=sys.stderr)
        return 1
    print(f"Validated {len(entries)} pending changeset(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
