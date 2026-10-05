"""Validate SkipperCast configuration and feed files against the JSON Schemas in schemas/.

    python -m skippercast.validate <kind> <file> [<file> ...]
    python -m skippercast validate feed var/live/latest.json

Kinds map to schemas/<kind>.schema.json; `feed` picks daily-feed, live-feed or
intelligence-feed from the document's shape. Exit status: 0 valid, 1 invalid,
2 when the optional `jsonschema` package is missing (core runtime stays
dependency-free; install requirements-test.txt).

Writers call check(kind, document) before publishing (contracts.atomic_json
does it when given kind=): a document that does not match its schema raises
ContractError and is never written. check() is a no-op when jsonschema is not
installed or when SKIPPERCAST_VALIDATE=off (an emergency switch for a schema
bug that would otherwise block a correct feed).

Patterns use ECMA-262 anchors: `$` matches only at the end of the string, as
in browsers and zod, not before a trailing newline as Python's re does.

The schemas are the shape contract shared by Python, the Worker and the
browser. Semantic cross-references (a region's sources exist in the catalog,
legal bindings match the registry) stay in platform.contracts and
pipeline.regulations.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import logging
import os
from pathlib import Path
import re
import sys

from .platform.contracts import REPO, ContractError, read_json

__all__ = ["KINDS", "ContractError", "MissingDependency", "available", "check", "detect_feed",
           "enabled", "errors", "validator"]

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
    "launch-points": "launch-points.schema.json",
    "forecast-index": "forecast-index.schema.json",
    "forecast-manifest": "forecast-manifest.schema.json",
    "forecast-tile": "forecast-tile.schema.json",
    "fleet-region": "fleet-region.schema.json",
    "fleet-profile": "fleet-profile.schema.json",
}
INSTALL_HINT = "JSON Schema validation needs the optional 'jsonschema' package: pip install -r requirements-test.txt"
SWITCH = "SKIPPERCAST_VALIDATE"
OFF = frozenset({"off", "0", "false", "no"})
LOG = logging.getLogger("skippercast.validate")


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


def ecma_pattern(pattern):
    """Python regex with ECMA-262 `$`: end of input only (Python's `$` also matches before a final newline)."""
    out, escaped, in_class = [], False, False
    for char in pattern:
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "[" and not in_class:
            in_class = True
        elif char == "]" and in_class:
            in_class = False
        elif char == "$" and not in_class:
            out.append(r"\Z")
            continue
        out.append(char)
    return "".join(out)


@lru_cache(maxsize=None)
def _compiled(pattern):
    return re.compile(ecma_pattern(pattern))


@lru_cache(maxsize=None)
def _validator(kind, directory):
    from jsonschema import Draft202012Validator, ValidationError, validators
    from referencing import Registry, Resource

    def pattern(validator, patrn, instance, schema):
        if validator.is_type(instance, "string") and not _compiled(patrn).search(instance):
            yield ValidationError(f"{instance!r} does not match {patrn!r}")

    Strict = validators.extend(Draft202012Validator, {"pattern": pattern})
    registry = Registry().with_resources((ident, Resource.from_contents(schema))
                                         for ident, schema in schemas(directory).items())
    schema = read_json(directory / KINDS[kind])
    Draft202012Validator.check_schema(schema)
    return Strict(schema, registry=registry)


def available():
    """True when the optional jsonschema (and referencing) packages can be imported."""
    try:
        import jsonschema  # noqa: F401
        import referencing  # noqa: F401
    except ImportError:
        return False
    return True


def enabled(environ=None):
    """False only when SKIPPERCAST_VALIDATE is off/0/false/no."""
    environ = os.environ if environ is None else environ
    return (environ.get(SWITCH) or "").strip().lower() not in OFF


_warned = set()


def check(kind, document, *, environ=None, directory=SCHEMA_DIR):
    """Raise ContractError unless the document matches its schema.

    Returns True when it was validated, False when validation was skipped
    because jsonschema is not installed or SKIPPERCAST_VALIDATE=off. Callers
    validate before their first write so a bad shape never publishes.
    """
    if not enabled(environ):
        reason = f"{SWITCH}=off"
    elif not available():
        reason = "jsonschema is not installed"
    else:
        if kind == "feed":
            try:
                kind = detect_feed(document)
            except ValueError as error:
                raise ContractError(str(error)) from None
        problems = errors(kind, document, directory)
        if problems:
            shown = "; ".join(problems[:5]) + (f"; ... {len(problems) - 5} more" if len(problems) > 5 else "")
            raise ContractError(f"{kind} does not match schemas/{KINDS[kind]} ({len(problems)} error(s)): {shown}")
        return True
    if reason not in _warned:  # once per process, so a skipped check is visible in job logs
        _warned.add(reason)
        LOG.warning("schema validation skipped: %s", reason)
    return False


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
