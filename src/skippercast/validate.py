"""Validate SkipperCast configuration and feed files against the JSON Schemas in schemas/.

    python -m skippercast.validate <kind> <file> [<file> ...]
    python -m skippercast validate feed var/live/latest.json

Kinds map to schemas/<kind>.schema.json; `feed` picks daily-feed, live-feed or
intelligence-feed from the document's shape. Exit status: 0 valid, 1 invalid,
2 when the optional `jsonschema` package is missing (core runtime stays
dependency-free; install requirements-test.txt).

The schemas are the shape contract shared by Python, the Worker and the
browser. Semantic cross-references (a region's sources exist in the catalog,
legal bindings match the registry) stay in platform.contracts and
pipeline.regulations.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
import sys

from .platform.contracts import REPO, read_json

SCHEMA_DIR = REPO / "schemas"
KINDS = {
    "region": "region.schema.json",
    "source": "source.schema.json",
    "sources-catalog": "sources-catalog.schema.json",
    "data-needs": "data-needs.schema.json",
    "jurisdiction": "jurisdiction.schema.json",
    "daily-feed": "daily-feed.schema.json",
    "live-feed": "live-feed.schema.json",
    "intelligence-feed": "intelligence-feed.schema.json",
    "regions-index": "regions-index.schema.json",
    "published-regions": "published-regions.schema.json",
    "region-manifest": "region-manifest.schema.json",
    "coverage": "coverage.schema.json",
    "forecast-index": "forecast-index.schema.json",
    "forecast-manifest": "forecast-manifest.schema.json",
    "forecast-tile": "forecast-tile.schema.json",
}
INSTALL_HINT = "JSON Schema validation needs the optional 'jsonschema' package: pip install -r requirements-test.txt"


class MissingDependency(RuntimeError):
    """The optional jsonschema package is not installed."""


def schemas(directory=SCHEMA_DIR):
    """Every schema in the directory keyed by its $id."""
    loaded = {}
    for path in sorted(Path(directory).glob("*.schema.json")):
        schema = read_json(path)
        loaded[schema["$id"]] = schema
    return loaded


def validator(kind, directory=SCHEMA_DIR):
    """A Draft 2020-12 validator for one kind, resolving cross-file $refs locally (no network)."""
    try:
        import jsonschema  # noqa: F401
        import referencing  # noqa: F401
    except ImportError as error:
        raise MissingDependency(INSTALL_HINT) from error
    if kind not in KINDS:
        raise ValueError(f"Unknown kind {kind!r}; expected one of: {', '.join(sorted(KINDS))}")
    return _validator(kind, Path(directory))


@lru_cache(maxsize=None)
def _validator(kind, directory):
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    registry = Registry().with_resources((ident, Resource.from_contents(schema))
                                         for ident, schema in schemas(directory).items())
    schema = read_json(directory / KINDS[kind])
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry)


def detect_feed(document):
    """Which published feed a latest.json is, from keys only its writer emits."""
    if not isinstance(document, dict):
        raise ValueError("A feed must be a JSON object")
    shapes = {"daily-feed": "reports" in document and "report_window" in document,
              "live-feed": "schedule_minutes" in document,
              "intelligence-feed": "verification" in document}
    matches = [kind for kind, hit in shapes.items() if hit]
    if len(matches) != 1:
        raise ValueError("Cannot tell whether this is a daily, live or intelligence feed; pass the kind explicitly")
    return matches[0]


def errors(kind, document, directory=SCHEMA_DIR):
    """Human-readable validation errors, sorted by location; empty when valid."""
    if kind == "feed":
        kind = detect_feed(document)
    found = validator(kind, directory).iter_errors(document)
    rows = []
    for error in sorted(found, key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        rows.append(f"{where}: {error.message[:300]}")
    return rows


def main(argv=None):
    parser = argparse.ArgumentParser(prog="skippercast.validate", description=__doc__.splitlines()[0])
    parser.add_argument("kind", choices=sorted([*KINDS, "feed"]))
    parser.add_argument("paths", nargs="+", type=Path)
    args = parser.parse_args(argv)
    status = 0
    for path in args.paths:
        try:
            document = read_json(path)
            problems = errors(args.kind, document)
        except MissingDependency as error:
            print(error, file=sys.stderr)
            return 2
        except (OSError, ValueError) as error:  # unreadable, duplicate keys, NaN, undetectable feed
            print(f"{path}: {type(error).__name__}: {error}", file=sys.stderr)
            status = 1
            continue
        if problems:
            status = 1
            print(f"{path}: {len(problems)} schema error(s)", file=sys.stderr)
            for problem in problems[:50]:
                print(f"  {problem}", file=sys.stderr)
        else:
            print(f"{path}: valid {detect_feed(document) if args.kind == 'feed' else args.kind}")
    return status


if __name__ == "__main__":
    sys.exit(main())
