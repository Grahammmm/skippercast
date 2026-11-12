"""Static, offline dependency-closure report for an explicit manifest of JSON Schema files.

    python3 scripts/coast_diagnostics/schema_closure.py --manifest M --input-root R --out O

The manifest (sc-schema-closure-input-v1) lists at most 128 staged schema files by normalized
relative POSIX path with their expected SHA256. Only those files are read, after path ancestry,
file type, size and aggregate size are checked; each file's hash is verified before parsing.

For every true Draft 2020-12 schema location the tool records declared $id / $anchor /
$dynamicAnchor values and every $ref / $dynamicRef occurrence (with its JSON Pointer), then
resolves each reference ONLY against resources declared inside the manifest documents. Nothing
is fetched: identifiers and references are data, never filesystem or network authority. $schema
values are reported as dialect text and never followed.

The report (sc-schema-closure-v1) carries input pins, sorted nodes, references, edges, cycles and
findings with execution_allowed=false. Exit status: 0 fully resolved static closure, 1 unresolved,
unsupported (UNVERIFIED dynamic resolution) or conflicting closure, 2 unsafe or malformed input
(nothing is written). Cycles and unused schemas are informational. This is not instance
validation, not proof of semantic compatibility and not permission to change CI.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys

REPORT_SCHEMA = "sc-schema-closure-v1"
MANIFEST_SCHEMA = "sc-schema-closure-input-v1"
ERROR_SCHEMA = "sc-schema-closure-error-v1"
MAX_FILES = 128
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4096
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_DEPTH = 256
SYNTHETIC_BASE = "urn:sc-schema-closure:path:"

# Draft 2020-12 (plus the older tuple/dependencies forms) keywords whose values are subschemas.
SINGLE = ("additionalItems", "additionalProperties", "contains", "contentSchema", "else", "if", "items", "not",
          "propertyNames", "then", "unevaluatedItems", "unevaluatedProperties")
ARRAYS = ("allOf", "anyOf", "oneOf", "prefixItems", "items")
MAPS = ("$defs", "definitions", "dependentSchemas", "patternProperties", "properties", "dependencies")
REF_KEYWORDS = ("$ref", "$dynamicRef")

ERROR_CODES = (
    "aliasing_id", "ambiguous_resource", "duplicate_anchor", "duplicate_id", "invalid_fragment",
    "invalid_percent_escape", "invalid_reference", "malformed_anchor", "malformed_dialect",
    "malformed_dynamic_anchor", "malformed_id", "malformed_reference", "missing_anchor",
    "missing_pointer_target", "pointer_target_not_schema", "unbound_file_reference",
    "unbound_relative_id", "unbound_relative_reference", "unresolved_resource",
)
UNVERIFIED_CODES = ("dynamic_resolution_unverified", "promoted_scope_unverified")
INFO_CODES = ("cycle", "reference_outside_schema_location", "unused_schema")

# Grammar patterns are applied with fullmatch only (a "$" anchor would accept a trailing newline).
URI = re.compile(r"(?:([^:/?#]+):)?(?://([^/?#]*))?([^?#]*)(?:\?([^#]*))?(?:#(.*))?", re.S)
SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*")
BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")
BAD_CHARS = re.compile(r"[\x00-\x20\x7f\"<>\\^`{|}]")
ANCHOR = re.compile(r"[A-Za-z_][-A-Za-z0-9._]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
INDEX = re.compile(r"0|[1-9][0-9]*")
UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")


class ClosureInputError(Exception):
    """Unsafe or malformed input: the CLI exits 2 and writes nothing."""

    def __init__(self, code, detail):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail = code, detail


class _DuplicateKey(ValueError):
    pass


class _NonFinite(ValueError):
    pass


# ---------------------------------------------------------------- URI handling (RFC 3986, no I/O)

def _split(uri):
    scheme, authority, path, query, fragment = URI.fullmatch(uri).groups()
    if scheme is not None and not SCHEME.fullmatch(scheme):
        scheme, path = None, uri.split("#", 1)[0].split("?", 1)[0]
    return scheme, authority, path, query, fragment


def _join(scheme, authority, path, query, fragment=None):
    text = ""
    if scheme is not None:
        text += scheme + ":"
    if authority is not None:
        text += "//" + authority
    text += path
    if query is not None:
        text += "?" + query
    if fragment is not None:
        text += "#" + fragment
    return text


def _remove_dots(path):
    output = []
    segments = path.split("/")
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == ".":
            if last:
                output.append("")
        elif segment == "..":
            if len(output) > 1 or (output and output[0] != ""):
                output.pop()
            if last:
                output.append("")
        else:
            output.append(segment)
    result = "/".join(output)
    if path.startswith("/") and not result.startswith("/"):
        result = "/" + result
    return result


def _hierarchical(scheme, authority, path):
    return authority is not None or path.startswith("/")


def _resolve(base, reference):
    """RFC 3986 section 5.2 resolution; returns (target or None, unbound flag)."""
    rs, ra, rp, rq, rf = _split(reference)
    bs, ba, bp, bq, _ = _split(base)
    if rs is not None:
        return _join(rs, ra, _remove_dots(rp) if _hierarchical(rs, ra, rp) else rp, rq, rf), False
    if ra is not None:
        return _join(bs, ra, _remove_dots(rp), rq, rf), False
    if rp == "":
        return _join(bs, ba, bp, rq if rq is not None else bq, rf), False
    if not _hierarchical(bs, ba, bp):
        return None, True
    if rp.startswith("/"):
        path = _remove_dots(rp)
    elif ba is not None and bp == "":
        path = _remove_dots("/" + rp)
    else:
        path = _remove_dots(bp[: bp.rfind("/") + 1] + rp)
    return _join(bs, ba, path, rq, rf), False


def _normalize_percent(text):
    def fix(match):
        char = chr(int(match.group(1), 16))
        return char if char in UNRESERVED else "%" + match.group(1).upper()
    return re.sub(r"%([0-9A-Fa-f]{2})", fix, text)


def _canonical(uri):
    """Canonical resource key (no fragment): case-folded scheme/host, unreserved escapes decoded."""
    scheme, authority, path, query, _ = _split(uri)
    if scheme is not None:
        scheme = scheme.lower()
    if authority is not None:
        user, at, host = authority.rpartition("@")
        authority = _normalize_percent(user) + at + _normalize_percent(host).lower()
    path = _normalize_percent(path)
    if _hierarchical(scheme, authority, path):
        path = _remove_dots(path)
    if query is not None:
        query = _normalize_percent(query)
    return _join(scheme, authority, path, query)


def _escape(token):
    return str(token).replace("~", "~0").replace("/", "~1")


def _decode_fragment(fragment):
    """Percent-decode a (BAD_PERCENT-validated) fragment exactly once; None if not strict UTF-8."""
    raw = bytearray()
    index = 0
    try:
        while index < len(fragment):
            char = fragment[index]
            if char == "%":
                raw.append(int(fragment[index + 1:index + 3], 16))
                index += 3
            else:
                raw.extend(char.encode("utf-8"))
                index += 1
        return raw.decode("utf-8")
    except (UnicodeError, ValueError):
        return None


def _pointer_tokens(pointer):
    tokens = []
    for token in pointer.split("/")[1:]:
        if re.search(r"~(?![01])", token):
            return None
        tokens.append(token.replace("~1", "/").replace("~0", "~"))
    return tokens


# ---------------------------------------------------------------- input safety

def _check_logical_path(path):
    if not isinstance(path, str):
        raise ClosureInputError("manifest_malformed", "files[].path must be a string")
    parts = path.split("/")
    if (not path or path.startswith("/") or "\\" in path or re.search(r"[\x00-\x1f\x7f]", path)
            or any(part in ("", ".", "..") for part in parts) or not path.endswith(".json")):
        raise ClosureInputError("path_unsafe", f"logical path is not a normalized relative POSIX .json path: {path!r}")


def _validate_manifest(manifest):
    if not isinstance(manifest, dict) or set(manifest) != {"schema", "files"}:
        raise ClosureInputError("manifest_malformed", "manifest must have exactly 'schema' and 'files'")
    if manifest["schema"] != MANIFEST_SCHEMA:
        raise ClosureInputError("manifest_malformed", f"manifest schema must be {MANIFEST_SCHEMA}")
    files = manifest["files"]
    if not isinstance(files, list) or not files:
        raise ClosureInputError("manifest_malformed", "files must be a non-empty list")
    if len(files) > MAX_FILES:
        raise ClosureInputError("manifest_too_many_files", f"{len(files)} entries exceed the {MAX_FILES}-file cap")
    rows, folded = [], set()
    for row in files:
        if not isinstance(row, dict) or set(row) != {"path", "sha256"}:
            raise ClosureInputError("manifest_malformed", "each files row must have exactly 'path' and 'sha256'")
        if not isinstance(row["sha256"], str) or not SHA256.fullmatch(row["sha256"]):
            raise ClosureInputError("manifest_malformed", "sha256 must be 64 lower-case hex characters")
        _check_logical_path(row["path"])
        key = row["path"].casefold()
        if key in folded:
            raise ClosureInputError("path_duplicate", f"duplicate (case-insensitive) logical path {row['path']!r}")
        folded.add(key)
        rows.append((row["path"], row["sha256"]))
    return sorted(rows)


def _lstat(path, missing_code="missing_file"):
    try:
        return os.lstat(path)
    except FileNotFoundError:
        raise ClosureInputError(missing_code, f"{path} does not exist") from None
    except OSError as error:
        raise ClosureInputError("path_unsafe", f"{path}: {error.strerror}") from None


def _check_ancestors(path, symlink_code, missing_code, other_code):
    """lstat EVERY proper ancestor of the absolute `path`, top down, before any read/mkdir/write.

    Each must be an existing real directory; a symlink anywhere in the chain is refused.
    """
    current = os.sep
    for part in [p for p in path.split(os.sep)[:-1] if p]:
        current = os.path.join(current, part)
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            raise ClosureInputError(missing_code, f"ancestor {current} does not exist") from None
        except OSError as error:
            raise ClosureInputError(other_code, f"ancestor {current}: {error.strerror}") from None
        if stat.S_ISLNK(info.st_mode):
            raise ClosureInputError(symlink_code, f"symlinked ancestor {current}")
        if not stat.S_ISDIR(info.st_mode):
            raise ClosureInputError(other_code, f"non-directory ancestor {current}")


def _check_file(root, logical):
    """Ancestry, type and size checks for one manifest file BEFORE any read."""
    current = root
    parts = logical.split("/")
    for part in parts[:-1]:
        current = os.path.join(current, part)
        info = _lstat(current)
        if stat.S_ISLNK(info.st_mode):
            raise ClosureInputError("symlink_in_path", f"symlinked directory in ancestry of {logical!r}")
        if not stat.S_ISDIR(info.st_mode):
            raise ClosureInputError("path_unsafe", f"non-directory in ancestry of {logical!r}")
    leaf = os.path.join(current, parts[-1])
    info = _lstat(leaf)
    if stat.S_ISLNK(info.st_mode):
        raise ClosureInputError("symlink_in_path", f"{logical!r} is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise ClosureInputError("not_regular_file", f"{logical!r} is not a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise ClosureInputError("file_too_large", f"{logical!r} has {info.st_size} bytes > {MAX_FILE_BYTES}")
    return leaf, info


def _read_checked(path, info, limit):
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise ClosureInputError("path_unsafe", f"cannot open {path}: {error.strerror}") from None
    try:
        opened = os.fstat(fd)
        if (not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)
                or opened.st_size != info.st_size):
            raise ClosureInputError("path_unsafe", f"{path} changed between check and open")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, min(65536, limit + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > limit:
                raise ClosureInputError("file_too_large", f"{path} grew beyond {limit} bytes")
        data = b"".join(chunks)
    finally:
        os.close(fd)
    if len(data) != info.st_size:
        raise ClosureInputError("path_unsafe", f"{path} changed size while reading")
    return data


def _reject_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise _DuplicateKey(key)
        seen[key] = value
    return seen


def _reject_constant(name):
    raise _NonFinite(name)


def _strict_unicode(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def parse_json_bytes(data, label):
    """Strict JSON: UTF-8, no duplicate keys, no NaN/Infinity, no lone surrogates, bounded depth."""
    try:
        text = data.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_reject_duplicates, parse_constant=_reject_constant)
    except _DuplicateKey as error:
        raise ClosureInputError("json_duplicate_key", f"{label}: duplicate key {error.args[0]!r}") from None
    except _NonFinite as error:
        raise ClosureInputError("json_nonfinite", f"{label}: non-finite number {error.args[0]}") from None
    except RecursionError:
        raise ClosureInputError("json_too_deep", f"{label}: nesting too deep") from None
    except (UnicodeDecodeError, ValueError) as error:
        raise ClosureInputError("json_malformed", f"{label}: {error}") from None
    stack = [(value, 0)]
    while stack:
        node, depth = stack.pop()
        if depth > MAX_DEPTH:
            raise ClosureInputError("json_too_deep", f"{label}: nesting deeper than {MAX_DEPTH}")
        if isinstance(node, str):
            if not _strict_unicode(node):
                raise ClosureInputError("json_invalid_unicode", f"{label}: string with a lone surrogate escape")
        elif isinstance(node, dict):
            for key in node:
                if not _strict_unicode(key):
                    raise ClosureInputError("json_invalid_unicode", f"{label}: key with a lone surrogate escape")
            stack.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            stack.extend((child, depth + 1) for child in node)
    return value


# ---------------------------------------------------------------- analysis

def _finding(code, source_path, pointer, reference=None, resolution_target=None, detail=None):
    severity = "error" if code in ERROR_CODES else "unverified" if code in UNVERIFIED_CODES else "info"
    return {"code": code, "severity": severity, "source_path": source_path, "pointer": pointer,
            "reference": reference, "resolution_target": resolution_target, "detail": detail}


def _schema_children(node, pointer):
    for key in sorted(node):
        value = node[key]
        child = pointer + "/" + _escape(key)
        if key in MAPS and isinstance(value, dict):
            for name in sorted(value):
                sub = value[name]
                yield (sub, child + "/" + _escape(name), isinstance(sub, (dict, bool)))
        elif key in ARRAYS and isinstance(value, list):
            for index, sub in enumerate(value):
                yield (sub, f"{child}/{index}", isinstance(sub, (dict, bool)))
        elif key in SINGLE and isinstance(value, (dict, bool)):
            yield (value, child, True)
        elif not (key in REF_KEYWORDS or key in ("$id", "$schema", "$anchor", "$dynamicAnchor")):
            yield (value, child, False)
        elif isinstance(value, (dict, list)):
            yield (value, child, False)


class _State:
    def __init__(self):
        self.resources = {}       # canonical uri -> list of (path, pointer, raw, kind, synthetic)
        self.anchors = {}         # (canonical uri, name) -> list of (path, pointer, dynamic)
        self.node_rows = 0        # declared (non-synthetic) $id resources
        self.anchor_rows = 0
        self.occurrences = {}     # (path, pointer) -> occurrence; a schema-location record wins
        self.dialects = []
        self.findings = []
        self.schema_nodes = set()
        self.containment = []     # (parent node, child node)
        self.documents = {}
        self.base_at = {}         # (path, pointer) -> base URI in effect at a non-schema object/boolean


def _cap(count, what):
    """The frozen 4096-row bound, enforced as each emitted collection grows (typed exit 2)."""
    if count > MAX_ROWS:
        raise ClosureInputError("row_cap_exceeded", f"more than {MAX_ROWS} {what} rows")


def _add_finding(state, row):
    state.findings.append(row)
    _cap(len(state.findings), "finding")


def _add_occurrence(state, occurrence):
    key = (occurrence["source_path"], occurrence["pointer"])
    old = state.occurrences.get(key)
    if old is not None and (occurrence["outside"] or not old["outside"]):
        return False
    state.occurrences[key] = occurrence
    _cap(len(state.occurrences), "reference")
    return True


def _walk(state, path, start, start_pointer, start_base, promoted):
    """Walk one schema location and everything below it. Returns occurrence keys added/upgraded.

    `promoted` marks an object that is a schema only because a resolved JSON Pointer reached it
    from outside the keyword structure. Validators enter such an object with the enclosing base;
    identifiers and anchors declared inside it are not registered resources there, so they are
    reported as promoted_scope_unverified (UNVERIFIED) instead of being registered or ignored.
    """
    changed = []
    stack = [(start, start_pointer, start_base, True, None)]
    while stack:
        node, pointer, base, is_schema, parent = stack.pop()
        here = (path, pointer)
        if here in state.schema_nodes:
            continue
        if not is_schema:
            if isinstance(node, (dict, bool)):
                state.base_at.setdefault(here, base)
            if isinstance(node, list):
                for index in range(len(node) - 1, -1, -1):
                    stack.append((node[index], f"{pointer}/{index}", base, False, None))
            elif isinstance(node, dict):
                for keyword in REF_KEYWORDS:
                    if keyword in node:
                        where = pointer + "/" + _escape(keyword)
                        reference = node[keyword] if isinstance(node[keyword], str) else None
                        if _add_occurrence(state, {"source_path": path, "pointer": where, "keyword": keyword,
                                                   "reference": reference, "base": base, "outside": True,
                                                   "node": None}):
                            changed.append((path, where))
                for key in sorted(node, reverse=True):
                    stack.append((node[key], pointer + "/" + _escape(key), base, False, None))
            continue
        state.schema_nodes.add(here)
        if parent is not None:
            state.containment.append((parent, here))
        if not isinstance(node, dict):
            continue
        if promoted:
            for keyword in ("$id", "$anchor", "$dynamicAnchor"):
                if keyword in node:
                    value = node[keyword]
                    _add_finding(state, _finding(
                        "promoted_scope_unverified", path, pointer + "/" + keyword,
                        value if isinstance(value, str) else None,
                        detail=f"{keyword} inside an object reached only by JSON Pointer is not a registered "
                               "resource or anchor; its resolution scope is UNVERIFIED"))
        if "$id" in node and not promoted:
            value, where = node["$id"], pointer + "/$id"
            target = None
            if (isinstance(value, str) and not BAD_CHARS.search(value) and not BAD_PERCENT.search(value)
                    and _split(value)[4] in (None, "")):
                target, unbound = _resolve(base, value)
                if unbound:
                    _add_finding(state, _finding("unbound_relative_id", path, where, value,
                                                 detail="relative $id under a non-hierarchical base"))
                    target = None
            else:
                _add_finding(state, _finding("malformed_id", path, where, value if isinstance(value, str) else None,
                                             detail="$id must be a valid URI-reference without a non-empty fragment"))
            if target is not None:
                raw = _join(*_split(target)[:4])
                kind = "document" if pointer == "" else "embedded"
                state.resources.setdefault(_canonical(raw), []).append((path, pointer, raw, kind, False))
                state.node_rows += 1
                _cap(state.node_rows, "node")
                base = raw
        if "$schema" in node:
            value = node["$schema"]
            if isinstance(value, str):
                state.dialects.append({"source_path": path, "pointer": pointer + "/$schema", "dialect": value})
                _cap(len(state.dialects), "dialect")
            else:
                _add_finding(state, _finding("malformed_dialect", path, pointer + "/$schema",
                                             detail="$schema must be a string"))
        for keyword, code, dynamic in (("$anchor", "malformed_anchor", False),
                                       ("$dynamicAnchor", "malformed_dynamic_anchor", True)):
            if keyword in node and not promoted:
                value = node[keyword]
                if isinstance(value, str) and ANCHOR.fullmatch(value):
                    key = (_canonical(base), value)
                    state.anchors.setdefault(key, []).append((path, pointer, dynamic))
                    state.anchor_rows += 1
                    _cap(state.anchor_rows, "anchor")
                else:
                    _add_finding(state, _finding(code, path, pointer + "/" + keyword,
                                                 value if isinstance(value, str) else None,
                                                 detail="anchor must fully match [A-Za-z_][-A-Za-z0-9._]*"))
        for keyword in REF_KEYWORDS:
            if keyword in node:
                value = node[keyword]
                where = pointer + "/" + _escape(keyword)
                if _add_occurrence(state, {"source_path": path, "pointer": where, "keyword": keyword,
                                           "reference": value if isinstance(value, str) else None,
                                           "malformed": not isinstance(value, str), "base": base,
                                           "outside": False, "node": here}):
                    changed.append((path, where))
        children = list(_schema_children(node, pointer))
        for child, child_pointer, child_is_schema in reversed(children):
            stack.append((child, child_pointer, base, child_is_schema, here if child_is_schema else None))
    return changed


def _array_index(token, length):
    """Return the in-range index named by a JSON Pointer token, else None.

    The digit count is compared with the (bounded) array length before any int()
    conversion, so arbitrarily long decimal tokens never reach the interpreter's
    integer-string digit limit; they are simply out of range.
    """
    if not INDEX.fullmatch(token) or len(token) > len(str(length)):
        return None
    index = int(token)
    return index if index < length else None


def _locate(document, tokens):
    node = document
    for token in tokens:
        index = _array_index(token, len(node)) if isinstance(node, list) else None
        if isinstance(node, dict) and token in node:
            node = node[token]
        elif index is not None:
            node = node[index]
        else:
            return False, None
    return True, node


def _resolve_reference(occurrence, state):
    """Classify one occurrence. Returns {classification, resolution_target, edge, finding}."""
    path, pointer, reference = occurrence["source_path"], occurrence["pointer"], occurrence["reference"]
    keyword = occurrence["keyword"]

    def fail(code, target=None, detail=None):
        return {"classification": code, "resolution_target": target, "edge": None,
                "finding": _finding(code, path, pointer, reference, target, detail)}

    if occurrence["outside"]:
        return {"classification": "outside_schema_location", "resolution_target": None, "edge": None,
                "finding": _finding("reference_outside_schema_location", path, pointer, reference,
                                    detail="reference keyword in a non-schema location (data, not followed)")}
    if occurrence.get("malformed"):
        return fail("malformed_reference", detail=f"{keyword} must be a string")
    if BAD_CHARS.search(reference):
        return fail("invalid_reference", detail="whitespace, control or disallowed character")
    if BAD_PERCENT.search(reference):
        return fail("invalid_percent_escape", detail="percent sign not followed by two hex digits")
    scheme = _split(reference)[0]
    target, unbound = _resolve(occurrence["base"], reference)
    if unbound:
        return fail("unbound_relative_reference", detail="relative reference under a non-hierarchical base")
    target_scheme = _split(target)[0]
    if (scheme or target_scheme or "").lower() == "file":
        return fail("unbound_file_reference", detail="file references are never read")
    resource_uri = _join(*_split(target)[:4])
    fragment = _split(target)[4]
    entries = state.resources.get(_canonical(resource_uri), [])
    if len(entries) > 1:
        return fail("ambiguous_resource", detail=f"{len(entries)} manifest resources declare {resource_uri}")
    if not entries or (entries[0][4] and entries[0][0] != path):
        return fail("unresolved_resource", detail=f"no manifest resource declares {resource_uri}")
    res_path, res_pointer = entries[0][0], entries[0][1]
    document = state.documents[res_path]
    _, resource_node = _locate(document, _pointer_tokens(res_pointer) if res_pointer else [])
    dynamic = False
    if fragment in (None, ""):
        target_pointer = res_pointer
    else:
        # Decode the (escape-validated) fragment exactly once, THEN dispatch pointer vs anchor.
        decoded = _decode_fragment(fragment)
        if decoded is None:
            return fail("invalid_fragment", detail="fragment is not valid percent-encoded UTF-8")
        if decoded.startswith("/"):
            tokens = _pointer_tokens(decoded)
            if tokens is None:
                return fail("invalid_fragment", detail="fragment is not a valid JSON Pointer")
            target_pointer = res_pointer + "".join("/" + _escape(t) for t in tokens)
            found, node = _locate(resource_node, tokens)
            if not found:
                return fail("missing_pointer_target", {"path": res_path, "pointer": target_pointer})
            if not isinstance(node, (dict, bool)):
                return fail("pointer_target_not_schema", {"path": res_path, "pointer": target_pointer})
        else:
            if not ANCHOR.fullmatch(decoded):
                return fail("invalid_fragment", detail="plain-name fragment must fully match the anchor grammar")
            found = state.anchors.get((_canonical(resource_uri), decoded), [])
            if not found:
                return fail("missing_anchor", detail=f"anchor {decoded!r} not declared in {resource_uri}")
            locations = sorted({(p, q) for p, q, _ in found})
            if len(locations) > 1:
                return fail("ambiguous_resource", detail=f"anchor {decoded!r} declared at {len(locations)} locations")
            target_pointer = locations[0][1]
            dynamic = keyword == "$dynamicRef" and any(d for _, _, d in found)
    target = {"path": res_path, "pointer": target_pointer}
    edge = {"source_path": path, "pointer": pointer, "keyword": keyword, "reference": reference,
            "target_path": res_path, "target_pointer": target_pointer,
            "status": "unverified_dynamic" if dynamic else "resolved"}
    if dynamic:
        return {"classification": "unverified_dynamic", "resolution_target": target, "edge": edge,
                "finding": _finding("dynamic_resolution_unverified", path, pointer, reference, target,
                                    "dynamic-scope resolution is runtime dependent; only the static initial "
                                    "target is shown (UNVERIFIED)")}
    return {"classification": "resolved", "resolution_target": target, "edge": edge, "finding": None}


def _strongly_connected(nodes, adjacency):
    """Iterative Tarjan; returns SCCs as sorted lists."""
    index_of, low, on_stack, stack, result, counter = {}, {}, set(), [], [], 0
    for start in sorted(nodes):
        if start in index_of:
            continue
        work = [(start, iter(sorted(adjacency.get(start, ()))))]
        index_of[start] = low[start] = counter
        counter += 1
        stack.append(start)
        on_stack.add(start)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index_of:
                    index_of[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    on_stack.add(child)
                    work.append((child, iter(sorted(adjacency.get(child, ())))))
                    advanced = True
                    break
                if child in on_stack:
                    low[node] = min(low[node], index_of[child])
            if advanced:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] == index_of[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                result.append(sorted(component))
    return result


def _sort_key_finding(row):
    target = row["resolution_target"] or {}
    return (row["source_path"], row["pointer"], row["code"], row["reference"] or "",
            target.get("path", ""), target.get("pointer", ""), row["detail"] or "")


def inspect_closure(manifest, input_root):
    """Return the sc-schema-closure-v1 report for an explicit manifest under an explicit root.

    Raises ClosureInputError for unsafe or malformed input (exit 2 in the CLI).
    """
    rows = _validate_manifest(manifest)
    root = os.path.abspath(os.fspath(input_root))
    _check_ancestors(root, "input_root_unsafe", "input_root_unsafe", "input_root_unsafe")
    info = _lstat(root, "input_root_unsafe")
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ClosureInputError("input_root_unsafe", "input root must be an existing directory, not a symlink")
    checked, total = [], 0
    for logical, expected in rows:
        leaf, leaf_info = _check_file(root, logical)
        total += leaf_info.st_size
        if total > MAX_TOTAL_BYTES:
            raise ClosureInputError("aggregate_too_large", f"manifest files exceed {MAX_TOTAL_BYTES} bytes")
        checked.append((logical, expected, leaf, leaf_info))
    state = _State()
    pins = []
    for logical, expected, leaf, leaf_info in checked:
        data = _read_checked(leaf, leaf_info, MAX_FILE_BYTES)
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise ClosureInputError("hash_mismatch", f"{logical!r} sha256 {actual} != manifest {expected}")
        pins.append({"path": logical, "sha256": actual, "bytes": len(data)})
        document = parse_json_bytes(data, logical)
        if not isinstance(document, (dict, bool)):
            raise ClosureInputError("not_a_schema", f"{logical!r} is neither a JSON object nor a boolean schema")
        state.documents[logical] = document
    for logical in sorted(state.documents):
        base = SYNTHETIC_BASE + logical
        state.resources.setdefault(base, []).append((logical, "", base, "document", True))
        _walk(state, logical, state.documents[logical], "", base, False)

    # Resolve every occurrence. A resolved JSON Pointer that lands on an object outside the
    # keyword structure makes that object a schema: walk it (worklist, each location at most
    # once, so cycles terminate) and resolve the references it contains, until nothing changes.
    outcomes = {}
    pending = sorted(state.occurrences)
    while pending:
        reached = set()
        for key in pending:
            outcome = _resolve_reference(state.occurrences[key], state)
            outcomes[key] = outcome
            edge = outcome["edge"]
            if edge is not None and (edge["target_path"], edge["target_pointer"]) not in state.schema_nodes:
                reached.add((edge["target_path"], edge["target_pointer"]))
        changed = set()
        for target_path, target_pointer in sorted(reached):
            if (target_path, target_pointer) in state.schema_nodes:
                continue
            _, node = _locate(state.documents[target_path], _pointer_tokens(target_pointer))
            base = state.base_at[(target_path, target_pointer)]
            changed.update(_walk(state, target_path, node, target_pointer, base, True))
        pending = sorted(changed)

    findings = list(state.findings)
    nodes = []
    for uri, entries in sorted(state.resources.items()):
        for path, pointer, raw, kind, synthetic in entries:
            if not synthetic:
                nodes.append({"path": path, "pointer": pointer, "id": raw, "kind": kind})
        if len(entries) > 1:
            code = "aliasing_id" if len({e[2] for e in entries}) > 1 else "duplicate_id"
            for path, pointer, raw, kind, synthetic in entries:
                findings.append(_finding(code, path, pointer + "/$id" if not synthetic else pointer, raw,
                                         detail=f"{len(entries)} declarations share canonical id {uri}"))
    for (uri, name), entries in sorted(state.anchors.items()):
        if len({(p, q) for p, q, _ in entries}) > 1:
            for path, pointer, dynamic in entries:
                findings.append(_finding("duplicate_anchor", path, pointer + ("/$dynamicAnchor" if dynamic else "/$anchor"),
                                         name, detail=f"anchor {name!r} declared more than once in {uri}"))
    anchors = sorted({(p, q, name, dyn) for (uri, name), entries in state.anchors.items() for p, q, dyn in entries})

    references, edges = [], []
    for key in sorted(state.occurrences):
        occurrence, outcome = state.occurrences[key], outcomes[key]
        references.append({"source_path": occurrence["source_path"], "pointer": occurrence["pointer"],
                           "keyword": occurrence["keyword"], "reference": occurrence["reference"],
                           "classification": outcome["classification"],
                           "resolution_target": outcome["resolution_target"]})
        if outcome["finding"] is not None:
            findings.append(outcome["finding"])
        if outcome["edge"] is not None:
            edges.append((occurrence["node"], outcome["edge"]))

    adjacency = {}
    graph_nodes = set(state.schema_nodes)
    for parent, child in state.containment:
        adjacency.setdefault(parent, set()).add(child)
    for source, edge in edges:
        target = (edge["target_path"], edge["target_pointer"])
        graph_nodes.add(target)
        adjacency.setdefault(source, set()).add(target)
    cycles = []
    for component in _strongly_connected(graph_nodes, adjacency):
        members = set(component)
        if len(component) == 1 and component[0] not in adjacency.get(component[0], ()):
            continue
        inner = sorted(({"source_path": e["source_path"], "pointer": e["pointer"], "target_path": e["target_path"],
                         "target_pointer": e["target_pointer"]} for s, e in edges
                        if s in members and (e["target_path"], e["target_pointer"]) in members),
                       key=lambda r: (r["source_path"], r["pointer"]))
        documents = sorted({p for p, _ in component})
        cycles.append({"documents": documents, "edges": inner, "schema_locations": len(component)})
        first = inner[0]
        findings.append(_finding("cycle", first["source_path"], first["pointer"], None,
                                 {"path": first["target_path"], "pointer": first["target_pointer"]},
                                 f"reference cycle through {len(inner)} edge(s) in {len(documents)} document(s); "
                                 "informational, not invalid"))
    cycles.sort(key=lambda c: (c["edges"][0]["source_path"], c["edges"][0]["pointer"]))

    referenced = {e["target_path"] for _, e in edges if e["target_path"] != e["source_path"]}
    for path in sorted(state.documents):
        if path not in referenced:
            findings.append(_finding("unused_schema", path, "", None,
                                     detail="no other manifest document references this schema"))
    if len(findings) > MAX_ROWS:
        raise ClosureInputError("row_cap_exceeded", f"{len(findings)} findings exceed {MAX_ROWS}")

    edge_rows = sorted((e for _, e in edges), key=lambda e: (e["source_path"], e["pointer"]))
    document_edges = {}
    for edge in edge_rows:
        if edge["source_path"] != edge["target_path"]:
            key = (edge["source_path"], edge["target_path"])
            document_edges[key] = document_edges.get(key, 0) + 1
    findings.sort(key=_sort_key_finding)
    by_code = {}
    for row in findings:
        by_code[row["code"]] = by_code.get(row["code"], 0) + 1
    blocking = [f for f in findings if f["severity"] in ("error", "unverified")]
    canonical_pins = json.dumps(pins, sort_keys=True, separators=(",", ":")).encode()
    report = {
        "schema": REPORT_SCHEMA,
        "execution_allowed": False,
        "review_required": True,
        "status": "open" if blocking else "closed",
        "exit_code": 1 if blocking else 0,
        "scope": "static reference closure of manifest-listed JSON Schemas only; not instance validation, "
                 "semantic compatibility or CI permission",
        "input": {"manifest_schema": MANIFEST_SCHEMA, "files": pins,
                  "files_digest": hashlib.sha256(canonical_pins).hexdigest()},
        "limits": {"max_files": MAX_FILES, "max_file_bytes": MAX_FILE_BYTES, "max_total_bytes": MAX_TOTAL_BYTES,
                   "max_rows": MAX_ROWS, "max_output_bytes": MAX_OUTPUT_BYTES, "max_depth": MAX_DEPTH},
        "dialects": sorted(state.dialects, key=lambda d: (d["source_path"], d["pointer"])),
        "nodes": sorted(nodes, key=lambda n: (n["path"], n["pointer"], n["id"])),
        "anchors": [{"path": p, "pointer": q, "name": n, "dynamic": d} for p, q, n, d in anchors],
        "references": references,
        "edges": edge_rows,
        "document_edges": [{"source_path": s, "target_path": t, "count": c}
                           for (s, t), c in sorted(document_edges.items())],
        "cycles": cycles,
        "findings": findings,
        "counts": {"files": len(pins), "resources": len(nodes), "references": len(references),
                   "edges": len(edge_rows), "resolved": sum(e["status"] == "resolved" for e in edge_rows),
                   "unverified": sum(e["status"] == "unverified_dynamic" for e in edge_rows),
                   "cycles": len(cycles), "findings_by_code": dict(sorted(by_code.items()))},
    }
    return report


def serialize(report):
    """Deterministic, bounded serialization; non-finite numbers are refused."""
    text = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"
    if len(text.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ClosureInputError("output_too_large", f"report exceeds {MAX_OUTPUT_BYTES} bytes")
    return text


def _load_manifest_file(path):
    path = os.path.abspath(path)
    _check_ancestors(path, "symlink_in_path", "missing_file", "path_unsafe")
    info = _lstat(path)
    if stat.S_ISLNK(info.st_mode):
        raise ClosureInputError("symlink_in_path", "manifest is a symlink")
    if not stat.S_ISREG(info.st_mode):
        raise ClosureInputError("not_regular_file", "manifest is not a regular file")
    if info.st_size > MAX_FILE_BYTES:
        raise ClosureInputError("file_too_large", "manifest exceeds the per-file cap")
    return parse_json_bytes(_read_checked(path, info, MAX_FILE_BYTES), "manifest")


def _check_output(path):
    """Every ancestor must be a real directory (no symlink anywhere) and the report must be new."""
    path = os.path.abspath(path)
    _check_ancestors(path, "output_unsafe", "output_unsafe", "output_unsafe")
    try:
        os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        raise ClosureInputError("output_exists", "output already exists; reports are never overwritten")
    return path


def _write_new(path, text):
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        raise ClosureInputError("output_exists", "output appeared before write; not overwritten") from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Static offline JSON Schema dependency-closure report.")
    parser.add_argument("--manifest", required=True, help="sc-schema-closure-input-v1 JSON file")
    parser.add_argument("--input-root", required=True, help="directory the manifest paths are relative to")
    parser.add_argument("--out", required=True, help="new report file (never overwritten)")
    args = parser.parse_args(argv)
    try:
        out = _check_output(args.out)
        manifest = _load_manifest_file(args.manifest)
        report = inspect_closure(manifest, args.input_root)
        text = serialize(report)
        _write_new(out, text)
    except ClosureInputError as error:
        print(json.dumps({"schema": ERROR_SCHEMA, "code": error.code, "detail": error.detail,
                          "execution_allowed": False, "exit_code": 2}, sort_keys=True), file=sys.stderr)
        return 2
    counts = report["counts"]
    print(f"{report['status']}: {counts['references']} references, {counts['edges']} edges, "
          f"{len(report['findings'])} findings; exit {report['exit_code']} (REVIEW REQUIRED)")
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
