"""Compare two frozen sc-rights-observation-v1 envelopes (docs/engineering/sc_rights_delta.md).

Pure, offline diagnostic. It reports raw rights/attribution field changes between two
observations of rows produced by skippercast.seafloor.rights.source_rights/feature_rights.
It never decides whether a change is legally better, infers public-domain status, retrieves
a policy, renders HTML or grants permission: every report carries semantic_approval=false,
publication_allowed=false and permission_effect="none".

    python3 scripts/coast_diagnostics/rights_delta.py --left A.json --right B.json --out NEW.json
        [--left-sha256 HEX] [--right-sha256 HEX]

Exit status: 0 COMPARED, 3 UNVERIFIED (report written, no delta), 2 INVALID (also usage
errors; nothing written), 4 REFUSED (path, type, size, hash or output-exists; nothing written).
"""
import argparse
import hashlib
import json
import os
import re
import stat
import sys

OBSERVATION_SCHEMA = "sc-rights-observation-v1"
DELTA_SCHEMA = "sc-rights-delta-v1"
MODULE_PATH = "src/skippercast/seafloor/rights.py"
PRODUCER_FUNCTIONS = frozenset({"source_rights", "feature_rights"})
SOURCE_USES = frozenset({"noncommercial", "for-profit"})
ENVELOPE_FIELDS = ("schema", "producer", "source_use", "rows", "canonical_rows_sha256")
PRODUCER_FIELDS = ("code_commit", "module_path", "module_sha256", "function")
# Exactly the keys source_rights emits. Anything else (an approval flag, a reviewer, a
# publication switch) is an unknown authority-bearing field and makes the input INVALID.
ROW_FIELDS = frozenset({"source_id", "license", "source_url", "policy_url", "attribution", "notice",
                        "commercial_use", "navigation_use", "reviewed_on"})
# Removing one of these is reported as an explicit diff and flagged; it is never a grant.
TERM_FIELDS = frozenset({"license", "policy_url", "attribution", "notice", "commercial_use",
                         "navigation_use", "reviewed_on"})
INPUT_FILE_CAP = 2 * 1024 * 1024
AGGREGATE_INPUT_CAP = 16 * 1024 * 1024
ROW_CAP = 4096
OUTPUT_CAP = 8 * 1024 * 1024
EXIT_COMPARED, EXIT_INVALID, EXIT_UNVERIFIED, EXIT_REFUSED = 0, 2, 3, 4
_HEX40 = re.compile(r"[0-9a-f]{40}")
_HEX64 = re.compile(r"[0-9a-f]{64}")


class InvalidJSON(ValueError):
    """Duplicate keys, nonfinite numbers, bad UTF-8 or malformed JSON."""


class Refused(Exception):
    """A filesystem or bound check refused the operation before any read or write."""


# ---------------------------------------------------------------- strict JSON

def _no_duplicates(pairs):
    seen = {}
    for key, value in pairs:
        if key in seen:
            raise InvalidJSON("duplicate object key")
        seen[key] = value
    return seen


def _no_constant(name):
    raise InvalidJSON(f"nonfinite number {name}")


def parse_json_strict(data):
    """Parse UTF-8 JSON bytes, rejecting duplicate keys and NaN/Infinity."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidJSON("input is not UTF-8") from error
    try:
        return json.loads(text, object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except InvalidJSON:
        raise
    except ValueError as error:
        raise InvalidJSON("malformed JSON") from error


def serialize_json(value):
    """Deterministic, ASCII-only JSON bytes (raw strings escaped, nonfinite values forbidden)."""
    return json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"


def canonical_rows_sha256(rows):
    """SHA-256 of sorted-key compact UTF-8 JSON of rows plus one LF (not the enclosing file)."""
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode("utf-8") + b"\n").hexdigest()


def build_observation(rows, *, producer, source_use):
    """Wrap producer rows in a new sc-rights-observation-v1 envelope (no attestation implied)."""
    rows = [dict(row) for row in rows]
    return {"schema": OBSERVATION_SCHEMA, "producer": dict(producer), "source_use": source_use,
            "rows": rows, "canonical_rows_sha256": canonical_rows_sha256(rows)}


# ---------------------------------------------------------------- validation

def _unknown_keys(mapping, allowed):
    """Keys outside the frozen allowlist (sorted). A seam for the acceptance mutation control."""
    return sorted(str(key) for key in mapping if key not in allowed)


def _same_value(a, b):
    """Exact, type-strict equality. Credit and notice strings are never normalized."""
    return type(a) is type(b) and a == b


def _producer_state(producer):
    """'absent', 'incomplete' or 'complete' (shape errors are reported separately as INVALID)."""
    if producer is None:
        return "absent"
    if isinstance(producer, dict) and not all(k in producer for k in PRODUCER_FIELDS):
        return "incomplete"
    return "complete"


def _validate(envelope, side):
    """Return (errors, view). view holds the fields comparison needs when there are no errors."""
    errors = []

    def error(code, pointer=""):
        errors.append({"side": side, "code": code, "pointer": pointer})

    if not isinstance(envelope, dict):
        error("ENVELOPE_NOT_OBJECT")
        return errors, None
    for key in _unknown_keys(envelope, ENVELOPE_FIELDS):
        error("UNKNOWN_FIELD", "/" + _escape_pointer(key))
    for key in ("schema", "rows", "canonical_rows_sha256"):
        if key not in envelope:
            error("ENVELOPE_FIELD_MISSING", "/" + key)
    if "schema" in envelope and envelope["schema"] != OBSERVATION_SCHEMA:
        error("SCHEMA_UNSUPPORTED", "/schema")

    producer = envelope.get("producer")
    if producer is not None:
        if not isinstance(producer, dict):
            error("PRODUCER_INVALID", "/producer")
        else:
            for key in _unknown_keys(producer, PRODUCER_FIELDS):
                error("UNKNOWN_FIELD", "/producer/" + _escape_pointer(key))
            checks = {"code_commit": lambda v: isinstance(v, str) and bool(_HEX40.fullmatch(v)),
                      "module_path": lambda v: v == MODULE_PATH,
                      "module_sha256": lambda v: isinstance(v, str) and bool(_HEX64.fullmatch(v)),
                      "function": lambda v: isinstance(v, str) and v in PRODUCER_FUNCTIONS}
            for key, check in checks.items():
                if key in producer and not check(producer[key]):
                    error("PRODUCER_INVALID", "/producer/" + key)
    source_use = envelope.get("source_use")
    if source_use is not None and not (isinstance(source_use, str) and source_use in SOURCE_USES):
        error("SOURCE_USE_INVALID", "/source_use")

    digest = envelope.get("canonical_rows_sha256")
    if "canonical_rows_sha256" in envelope and not (isinstance(digest, str) and _HEX64.fullmatch(digest)):
        error("CANONICAL_ROWS_SHA256_INVALID", "/canonical_rows_sha256")

    rows = envelope.get("rows")
    by_id, order = {}, []
    if "rows" in envelope:
        if not isinstance(rows, list):
            error("ROWS_NOT_ARRAY", "/rows")
            rows = None
        elif len(rows) > ROW_CAP:
            error("ROW_CAP_EXCEEDED", "/rows")
            rows = None
    if isinstance(rows, list):
        for index, row in enumerate(rows):
            base = f"/rows/{index}"
            if not isinstance(row, dict):
                error("ROW_NOT_OBJECT", base)
                continue
            for key in _unknown_keys(row, ROW_FIELDS):
                error("UNKNOWN_FIELD", base + "/" + _escape_pointer(key))
            source_id = row.get("source_id")
            if not isinstance(source_id, str) or not source_id:
                error("SOURCE_ID_INVALID", base + "/source_id")
                continue
            for key, value in row.items():
                if not (value is None or isinstance(value, (str, bool))):
                    error("ROW_VALUE_UNSUPPORTED", base + "/" + _escape_pointer(str(key)))
                elif isinstance(value, str) and not _encodable(value):
                    error("ROW_TEXT_NOT_UTF8", base + "/" + _escape_pointer(str(key)))
            if not _encodable(source_id):
                continue
            if source_id in by_id:
                error("DUPLICATE_SOURCE_ID", base + "/source_id")
                continue
            by_id[source_id] = row
            order.append(source_id)
        if not errors and isinstance(digest, str) and canonical_rows_sha256(rows) != digest:
            error("CANONICAL_ROWS_SHA256_MISMATCH", "/canonical_rows_sha256")
    if errors:
        return errors, None
    return [], {"producer": producer, "producer_state": _producer_state(producer),
                "producer_present": "producer" in envelope and producer is not None,
                "source_use": source_use, "rows": by_id, "order": order, "digest": digest}


def _encodable(text):
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _escape_pointer(token):
    return token.replace("~", "~0").replace("/", "~1")


def _pin(view, envelope):
    return {"schema": envelope.get("schema"), "producer": view["producer"],
            "source_use": view["source_use"], "canonical_rows_sha256": view["digest"],
            "row_count": len(view["order"]), "file_sha256": None}


def _field_change(source_id, pointer, before_present, before, after_present, after):
    return {"source_id": source_id, "pointer": pointer, "before_present": before_present,
            "before": before if before_present else None, "after_present": after_present,
            "after": after if after_present else None}


def _binding_mismatches(left, right):
    """Producer subfield and source_use differences between two validated views."""
    rows = []
    lp = left["producer"] if isinstance(left["producer"], dict) else {}
    rp = right["producer"] if isinstance(right["producer"], dict) else {}
    for key in PRODUCER_FIELDS:
        lhas, rhas = key in lp, key in rp
        if lhas != rhas or (lhas and not _same_value(lp[key], rp[key])):
            rows.append({"pointer": "/producer/" + key, "before_present": lhas, "before": lp.get(key),
                         "after_present": rhas, "after": rp.get(key)})
    lu, ru = left["source_use"], right["source_use"]
    if (lu is None) != (ru is None) or (lu is not None and not _same_value(lu, ru)):
        rows.append({"pointer": "/source_use", "before_present": lu is not None, "before": lu,
                     "after_present": ru is not None, "after": ru})
    return rows


def _report(status, **fields):
    report = {"schema": DELTA_SCHEMA, "status": status, "comparable": status == "COMPARED",
              "semantic_approval": False, "publication_allowed": False, "permission_effect": "none",
              "coverage_claim": "observed-rows-only", "changes": None}
    report.update(fields)
    return report


# ---------------------------------------------------------------- public API

def compare_rights(left_envelope, right_envelope):
    """Compare two parsed sc-rights-observation-v1 envelopes; returns an sc-rights-delta-v1 dict.

    INVALID (either side) outranks UNVERIFIED (absent/incomplete/mismatched producer binding
    or source_use), which outranks COMPARED. Inputs are never mutated.
    """
    left_errors, left = _validate(left_envelope, "left")
    right_errors, right = _validate(right_envelope, "right")
    if left_errors or right_errors:
        return _report("INVALID", errors=left_errors + right_errors)

    reasons = []
    for side, view in (("LEFT", left), ("RIGHT", right)):
        if view["producer_state"] == "absent":
            reasons.append(f"{side}_PRODUCER_ABSENT")
        elif view["producer_state"] == "incomplete":
            reasons.append(f"{side}_PRODUCER_INCOMPLETE")
        if view["source_use"] is None:
            reasons.append(f"{side}_SOURCE_USE_ABSENT")
    mismatches = _binding_mismatches(left, right)
    if left["producer_state"] == right["producer_state"] == "complete" and any(
            m["pointer"].startswith("/producer/") for m in mismatches):
        reasons.append("PRODUCER_MISMATCH")
    if left["source_use"] is not None and right["source_use"] is not None and any(
            m["pointer"] == "/source_use" for m in mismatches):
        reasons.append("SOURCE_USE_MISMATCH")

    notes = [{"side": side, "code": "EMPTY_OBSERVATION"}
             for side, view in (("left", left), ("right", right)) if not view["order"]]
    folded = {}
    for source_id in sorted(set(left["rows"]) | set(right["rows"])):
        folded.setdefault(source_id.casefold(), []).append(source_id)
    notes += [{"code": "SOURCE_ID_CASE_VARIANT", "source_ids": ids} for _, ids in sorted(folded.items())
              if len(ids) > 1]
    common = dict(input_pins={"left": _pin(left, left_envelope), "right": _pin(right, right_envelope)},
                  binding_mismatches=mismatches, unverified_reasons=reasons,
                  row_counts={"left": len(left["order"]), "right": len(right["order"])}, notes=notes)
    if reasons:
        return _report("UNVERIFIED", sources_added=None, sources_removed=None, review_flags=[],
                       row_order_changed=None, changed=None, **common)

    changes, flags = [], []
    added = sorted(set(right["rows"]) - set(left["rows"]))
    removed = sorted(set(left["rows"]) - set(right["rows"]))
    for source_id in sorted(set(left["rows"]) | set(right["rows"])):
        before = left["rows"].get(source_id)
        after = right["rows"].get(source_id)
        if after is None:
            flags.append({"source_id": source_id, "pointer": "", "code": "SOURCE_REMOVED_NOT_A_GRANT"})
        keys = (set(before or {}) | set(after or {})) - {"source_id"}
        for key in sorted(keys):
            bhas = before is not None and key in before
            ahas = after is not None and key in after
            if bhas and ahas and _same_value(before[key], after[key]):
                continue
            pointer = "/" + _escape_pointer(key)
            changes.append(_field_change(source_id, pointer, bhas, before.get(key) if bhas else None,
                                         ahas, after.get(key) if ahas else None))
            if bhas and not ahas and key in TERM_FIELDS:
                flags.append({"source_id": source_id, "pointer": pointer, "code": "TERM_FIELD_REMOVED_NOT_A_GRANT"})
    changes.sort(key=lambda c: (c["source_id"], c["pointer"]))
    flags.sort(key=lambda f: (f["source_id"], f["pointer"], f["code"]))
    shared = [s for s in left["order"] if s in right["rows"]]
    shared_right = [s for s in right["order"] if s in left["rows"]]
    return _report("COMPARED", changes=changes, changed=bool(changes or added or removed), sources_added=added,
                   sources_removed=removed, review_flags=flags,
                   row_order_changed=shared != shared_right, **common)


# ---------------------------------------------------------------- bounded file I/O

def _has_parent_reference(raw_path):
    """True when the supplied path has a '..' component.

    Lexical normalization (os.path.abspath) would cancel such a component together with
    whatever precedes it, which may be a symlink, before ancestry is checked. These paths
    are refused outright rather than resolved.
    """
    return os.pardir in os.fsdecode(raw_path).split(os.sep)


def _admit_path(raw_path):
    """Reject '..' components, then return the absolute path for ancestry checking."""
    if _has_parent_reference(raw_path):
        raise Refused("path has a '..' component")
    return os.path.abspath(raw_path)


def _check_ancestry(path):
    """Refuse a symlink at the root, any intermediate component or the leaf."""
    current = os.path.abspath(os.sep)
    for part in path.split(os.sep)[1:]:
        if not part:
            continue
        current = os.path.join(current, part)
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            return False
        if stat.S_ISLNK(mode):
            raise Refused("symlink in path")
    return True


def read_bounded(raw_path, expected_sha256=None, *, budget):
    """Read one staged regular file after ancestry/type/size checks; returns (bytes, sha256)."""
    path = _admit_path(raw_path)
    if not _check_ancestry(path):
        raise Refused("input missing")
    info = os.lstat(path)
    if not stat.S_ISREG(info.st_mode):
        raise Refused("input is not a regular file")
    if info.st_size > INPUT_FILE_CAP:
        raise Refused("input exceeds per-file cap")
    if info.st_size > budget[0]:
        raise Refused("inputs exceed aggregate cap")
    if expected_sha256 is not None and not (isinstance(expected_sha256, str) and _HEX64.fullmatch(expected_sha256)):
        raise Refused("expected sha256 is not 64 lowercase hex")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise Refused("input changed identity during open")
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > INPUT_FILE_CAP or total > budget[0]:
                raise Refused("input grew past cap while reading")
            chunks.append(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    budget[0] -= len(data)
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256:
        raise Refused("input sha256 does not match the expected hash")
    return data, digest


def write_new(raw_path, data):
    """Create a new report file: validated parent, no symlinks, no overwrite, bounded bytes."""
    if len(data) > OUTPUT_CAP:
        raise Refused("report exceeds output cap")
    path = _admit_path(raw_path)
    parent = os.path.dirname(path)
    if not _check_ancestry(parent) or not stat.S_ISDIR(os.lstat(parent).st_mode):
        raise Refused("output parent is not an existing directory")
    try:
        os.lstat(path)
    except FileNotFoundError:
        pass
    else:
        raise Refused("output already exists")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
        os.fsync(fd)
    finally:
        os.close(fd)


def _diagnostic(status, detail):
    sys.stderr.write(json.dumps({"schema": DELTA_SCHEMA, "status": status, "detail": detail},
                                sort_keys=True, ensure_ascii=True) + "\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare two sc-rights-observation-v1 envelopes.")
    parser.add_argument("--left", required=True)
    parser.add_argument("--right", required=True)
    parser.add_argument("--out", required=True, help="new report file (never overwritten)")
    parser.add_argument("--left-sha256")
    parser.add_argument("--right-sha256")
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:
        return EXIT_INVALID if exit_.code else EXIT_COMPARED
    budget = [AGGREGATE_INPUT_CAP]
    try:
        _admit_path(args.out)  # refuse a '..' output path before any input is read
        left_bytes, left_sha = read_bounded(args.left, args.left_sha256, budget=budget)
        right_bytes, right_sha = read_bounded(args.right, args.right_sha256, budget=budget)
    except (Refused, OSError) as error:
        _diagnostic("REFUSED", str(error) if isinstance(error, Refused) else type(error).__name__)
        return EXIT_REFUSED
    try:
        left_doc, right_doc = parse_json_strict(left_bytes), parse_json_strict(right_bytes)
    except InvalidJSON as error:
        _diagnostic("INVALID", str(error))
        return EXIT_INVALID
    report = compare_rights(left_doc, right_doc)
    if report["status"] == "INVALID":
        sys.stderr.write(serialize_json(report).decode("ascii"))
        return EXIT_INVALID
    report["input_pins"]["left"]["file_sha256"] = left_sha
    report["input_pins"]["right"]["file_sha256"] = right_sha
    report["input_pins"]["left"]["file_bytes"] = len(left_bytes)
    report["input_pins"]["right"]["file_bytes"] = len(right_bytes)
    try:
        write_new(args.out, serialize_json(report))
    except (Refused, OSError) as error:
        _diagnostic("REFUSED", str(error) if isinstance(error, Refused) else type(error).__name__)
        return EXIT_REFUSED
    return EXIT_COMPARED if report["status"] == "COMPARED" else EXIT_UNVERIFIED


if __name__ == "__main__":
    raise SystemExit(main())
