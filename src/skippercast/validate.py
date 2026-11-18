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
    "shore-habitat": "shore-habitat.schema.json",
    "forecast-index": "forecast-index.schema.json",
    "forecast-manifest": "forecast-manifest.schema.json",
    "forecast-tile": "forecast-tile.schema.json",
    "fleet-region": "fleet-region.schema.json",
    "fleet-profile": "fleet-profile.schema.json",

    'coast-recipe-v1': 'coast-recipe-v1.schema.json',
    'coastal-discovery-lead-v1': 'coastal-discovery-lead-v1.schema.json',
    'coastal-terrain-only-input-v1': 'coastal-terrain-only-input-v1.schema.json',
    'coastal-terrain-only-render-v1': 'coastal-terrain-only-render-v1.schema.json',
    'coastal-terrain-only-science-review-v1': 'coastal-terrain-only-science-review-v1.schema.json',
    'private-mapping-input-v2': 'private-mapping-input-v2.schema.json',
    'render-handoff-v2.1': 'render-handoff-v2.1.schema.json',
    'vertical-v1': 'vertical-v1.schema.json',
    'coast-recipe-v1': 'coast-recipe-v1.schema.json',
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
            yield ValidationError(f"value does not match {patrn!r}")  # never echo the rejected value

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


_RULES = {  # schema rule -> wording built only from the schema's own limit, never from the document
    "type": "{s} is not of type {v!r}",
    "enum": "{s} is not one of {v!r}",
    "const": "{s} does not equal {v!r}",
    "pattern": "{s} does not match {v!r}",
    "format": "{s} is not a valid {v!r}",
    "minLength": "{s} is too short (minimum length {v})",
    "maxLength": "{s} is too long (maximum length {v})",
    "minItems": "array is too short (minimum {v} items)",
    "maxItems": "array is too long (maximum {v} items)",
    "minProperties": "object has too few properties (minimum {v})",
    "maxProperties": "object has too many properties (maximum {v})",
    "minimum": "{s} is less than minimum of {v}",
    "maximum": "{s} is greater than maximum of {v}",
    "exclusiveMinimum": "{s} is not greater than {v}",
    "exclusiveMaximum": "{s} is not less than {v}",
    "multipleOf": "{s} is not a multiple of {v}",
    "uniqueItems": "array has non-unique elements",
}


def _declared_keys(error):
    """Property names the schema itself declares along the failing rule's path (safe to show)."""
    path, keys, i = list(error.absolute_schema_path), set(), 0
    while i < len(path):
        if path[i] == "properties" and i + 1 < len(path) and isinstance(path[i + 1], str):
            keys.add(path[i + 1])
            i += 2
        elif path[i] in ("patternProperties", "dependentSchemas") and i + 1 < len(path):
            i += 2  # the next step is a pattern or dependency name, not a property
        else:
            i += 1
    return keys


def _location(error):
    """Field path: array positions and schema-declared names; document-supplied keys become <key>."""
    declared = _declared_keys(error)
    parts = []
    for step in error.absolute_path:
        if isinstance(step, int) and not isinstance(step, bool):
            parts.append(str(step))
        else:
            parts.append(step if isinstance(step, str) and step in declared else "<key>")
    return "/".join(parts) or "(root)"


def _unexpected_count(error):
    schema, instance = error.schema, error.instance
    if not isinstance(schema, dict) or not isinstance(instance, dict):
        return None
    known, patterns = schema.get("properties") or {}, schema.get("patternProperties") or {}
    return sum(1 for key in instance if key not in known and not any(_compiled(p).search(key) for p in patterns))


def _describe(error):
    """The failed schema rule in words, without the rejected value or any document-supplied key."""
    rule, limit = error.validator, error.validator_value
    subject = "property name" if "propertyNames" in error.absolute_schema_path else "value"
    if rule == "required":  # the name comes from the schema's `required` list
        return error.message
    if rule == "additionalProperties":
        count = _unexpected_count(error)
        return "additional properties are not allowed" + (f" ({count} unexpected)" if count is not None else "")
    if rule in _RULES:
        return _RULES[rule].format(s=subject, v=limit)[:300]
    return f"{subject} does not satisfy schema rule {rule!r}"


def errors(kind, document, directory=SCHEMA_DIR):
    """Field-level validation errors (rule and safe location; never the rejected value), sorted by location; empty when valid."""
    if kind == "feed":
        kind = detect_feed(document)
    found = validator(kind, directory).iter_errors(document)
    rows = []
    def order(e):  # array positions compare as numbers (2 before 10), before keys; message breaks ties
        return [(0, p) if isinstance(p, int) and not isinstance(p, bool) else (1, str(p)) for p in e.absolute_path], _describe(e)
    for error in sorted(found, key=order):
        rows.append(f"{_location(error)}: {_describe(error)}")
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
            detail = "Duplicate JSON key (name withheld)" if str(error).startswith("Duplicate JSON key:") else error
            print(f"{path}: {type(error).__name__}: {detail}", file=sys.stderr)
            status = 1
            continue
        if problems:
            status = 1
            print(f"{path}: {len(problems)} schema error(s)", file=sys.stderr)
            for problem in problems[:50]:
                print(f"  {problem}", file=sys.stderr)
            if len(problems) > 50:
                print(f"  ... {len(problems) - 50} more", file=sys.stderr)
        else:
            print(f"{path}: valid {detect_feed(document) if args.kind == 'feed' else args.kind}")
    return status


if __name__ == "__main__":
    sys.exit(main())
