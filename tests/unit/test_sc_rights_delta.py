"""SC-RIGHTS-DELTA: compare two frozen sc-rights-observation-v1 envelopes (docs/engineering/sc_rights_delta.md).

Plain test_* functions with no pytest fixtures or imports, so the existing pytest discovery
collects them and scripts/accept_sc_rights_delta.py can run the same functions in-process.
Name prefixes map to the card's acceptance rows: test_a1_* focused, test_a2_* producer
contract, test_a3_* negative and preservation. Every path derives from this file.
"""
import copy
import hashlib
import json
import os
import stat
import tempfile
from datetime import date
from pathlib import Path

from scripts.coast_diagnostics import rights_delta as rd
from skippercast.seafloor import rights

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "sc_rights_delta"
PIN_COMMIT = "59fca09b2cc7f5c81a4796902504e263d7f06960"
PIN_MODULE_SHA256 = "7411657fefaea64f73bbd566ba1d37eb0f4d787b83a2afcec117d882e579ee0d"
FIXED_TODAY = date(2026, 10, 24)
# Written out literally (not imported from rights.py) so the producer constant is checked
# against an independent frozen copy of the exact CSUMB credit.
EXACT_CSUMB_CREDIT = ("Data used in this study were acquired, processed, archived, and distributed "
                      "by the Seafloor Mapping Lab of California State University Monterey Bay.")
EXACT_CSUMB_NOTICE = ("Public noncommercial use only; for-profit use requires express CSUMB SFML "
                      "permission. Not for navigation.")


# ---------------------------------------------------------------- helpers (independent of rd)

def _canonical_rows_sha256(rows):
    body = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(body.encode("utf-8") + b"\n").hexdigest()


def _producer(**changes):
    value = {"code_commit": PIN_COMMIT, "module_path": "src/skippercast/seafloor/rights.py",
             "module_sha256": PIN_MODULE_SHA256, "function": "source_rights"}
    value.update(changes)
    return value


def _row(source_id="src-a", **changes):
    value = {"source_id": source_id, "license": "public-domain-us-gov",
             "source_url": "https://example.invalid/" + source_id,
             "policy_url": "https://example.invalid/terms/" + source_id,
             "attribution": "Synthetic survey credit for " + source_id,
             "notice": "Original US government data; retain source attribution and survey limitations."}
    value.update(changes)
    return value


def _csumb_row(source_id="csumb-a", **changes):
    value = {"source_id": source_id, "license": "csumb-public-use-noncommercial",
             "source_url": "https://example.invalid/" + source_id,
             "policy_url": "https://csumb.edu/undersea/sfml-data-library/",
             "attribution": EXACT_CSUMB_CREDIT, "notice": EXACT_CSUMB_NOTICE,
             "commercial_use": "permission-required", "navigation_use": False,
             "reviewed_on": "2026-03-01"}
    value.update(changes)
    return value


def _envelope(rows, *, producer="default", source_use="noncommercial", drop=(), digest=None):
    value = {"schema": "sc-rights-observation-v1",
             "producer": _producer() if producer == "default" else producer,
             "source_use": source_use, "rows": rows,
             "canonical_rows_sha256": digest or _canonical_rows_sha256(rows)}
    for key in drop:
        value.pop(key)
    return value


def _changes_by(report):
    return {(c["source_id"], c["pointer"]): c for c in report["changes"]}


def _expect_invalid(left, right, code):
    report = rd.compare_rights(left, right)
    if report["status"] != "INVALID":
        raise AssertionError(f"expected INVALID {code}, got {report['status']}")
    codes = [e["code"] for e in report["errors"]]
    if code not in codes:
        raise AssertionError(f"expected error {code}, got {codes}")
    assert report["changes"] is None and report["semantic_approval"] is False
    assert report["publication_allowed"] is False
    return report


def _fresh_dir():
    return Path(tempfile.mkdtemp(prefix="sc_rights_delta_"))


def _write(path, data):
    path.write_bytes(data if isinstance(data, bytes) else json.dumps(data, sort_keys=True, indent=2).encode() + b"\n")
    return path


def _cli(left_path, right_path, out_path, *extra):
    return rd.main(["--left", str(left_path), "--right", str(right_path), "--out", str(out_path), *extra])


# ---------------------------------------------------------------- A1 focused

def test_a1_unchanged_rows_give_no_changes():
    rows = [_row("src-a"), _csumb_row("csumb-a")]
    report = rd.compare_rights(_envelope(rows), _envelope(copy.deepcopy(rows)))
    assert report["schema"] == "sc-rights-delta-v1"
    assert report["status"] == "COMPARED" and report["comparable"] is True
    assert report["changes"] == [] and report["sources_added"] == [] and report["sources_removed"] == []
    assert report["changed"] is False
    assert report["row_counts"] == {"left": 2, "right": 2}


def test_a1_changed_credit_notice_license_policy_url_are_never_hidden():
    left = [_row("src-a")]
    cases = {"/attribution": "Different credit", "/notice": "Different notice",
             "/license": "some-other-license", "/policy_url": "https://example.invalid/new-terms"}
    for pointer, new in cases.items():
        right = [_row("src-a", **{pointer[1:]: new})]
        report = rd.compare_rights(_envelope(left), _envelope(right))
        assert report["status"] == "COMPARED" and report["changed"] is True, pointer
        assert report["changes"] == [{"source_id": "src-a", "pointer": pointer,
                                      "before_present": True, "before": left[0][pointer[1:]],
                                      "after_present": True, "after": new}], pointer


def test_a1_policy_url_missing_empty_and_null_are_distinct():
    missing = _row("src-a")
    missing.pop("policy_url")
    shapes = {"missing": missing, "empty": _row("src-a", policy_url=""), "null": _row("src-a", policy_url=None)}
    for a in shapes:
        for b in shapes:
            report = rd.compare_rights(_envelope([shapes[a]]), _envelope([shapes[b]]))
            if a == b:
                assert report["changes"] == [], (a, b)
                continue
            change = _changes_by(report)[("src-a", "/policy_url")]
            assert change["before_present"] is (a != "missing"), (a, b)
            assert change["after_present"] is (b != "missing"), (a, b)
            assert change["before"] == {"missing": None, "empty": "", "null": None}[a]
            assert change["after"] == {"missing": None, "empty": "", "null": None}[b]
            assert len(report["changes"]) == 1


def test_a1_differing_source_use_is_unverified_and_visible():
    rows = [_csumb_row()]
    report = rd.compare_rights(_envelope(rows), _envelope(rows, source_use="for-profit"))
    assert report["status"] == "UNVERIFIED" and report["comparable"] is False
    assert report["changes"] is None and report["sources_added"] is None
    assert "SOURCE_USE_MISMATCH" in report["unverified_reasons"]
    assert {"pointer": "/source_use", "before_present": True, "before": "noncommercial",
            "after_present": True, "after": "for-profit"} in report["binding_mismatches"]
    assert report["publication_allowed"] is False and report["semantic_approval"] is False


def test_a1_removed_restrictions_are_explicit_diffs_never_grants():
    before = _csumb_row()
    after = _csumb_row()
    for key in ("commercial_use", "navigation_use", "reviewed_on"):
        after.pop(key)
    report = rd.compare_rights(_envelope([before]), _envelope([after]))
    assert report["status"] == "COMPARED"
    changes = _changes_by(report)
    assert changes[("csumb-a", "/commercial_use")] == {
        "source_id": "csumb-a", "pointer": "/commercial_use", "before_present": True,
        "before": "permission-required", "after_present": False, "after": None}
    assert changes[("csumb-a", "/navigation_use")]["before"] is False
    assert changes[("csumb-a", "/navigation_use")]["after_present"] is False
    assert changes[("csumb-a", "/reviewed_on")]["after_present"] is False
    flagged = {(f["source_id"], f["pointer"], f["code"]) for f in report["review_flags"]}
    for key in ("commercial_use", "navigation_use", "reviewed_on"):
        assert ("csumb-a", "/" + key, "TERM_FIELD_REMOVED_NOT_A_GRANT") in flagged
    assert report["permission_effect"] == "none"
    assert report["publication_allowed"] is False and report["semantic_approval"] is False


def test_a1_navigation_false_to_true_is_a_raw_change_not_a_grant():
    report = rd.compare_rights(_envelope([_csumb_row()]), _envelope([_csumb_row(navigation_use=True)]))
    change = _changes_by(report)[("csumb-a", "/navigation_use")]
    assert change["before"] is False and change["after"] is True
    assert report["permission_effect"] == "none" and report["publication_allowed"] is False


def test_a1_added_and_removed_sources_are_retained_with_every_field():
    left = [_row("src-a"), _row("src-b")]
    right = [_row("src-a"), _csumb_row("src-c")]
    report = rd.compare_rights(_envelope(left), _envelope(right))
    assert report["sources_added"] == ["src-c"] and report["sources_removed"] == ["src-b"]
    changes = _changes_by(report)
    for key, value in left[1].items():
        if key == "source_id":
            continue
        assert changes[("src-b", "/" + key)] == {"source_id": "src-b", "pointer": "/" + key,
                                                 "before_present": True, "before": value,
                                                 "after_present": False, "after": None}
    for key, value in right[1].items():
        if key == "source_id":
            continue
        assert changes[("src-c", "/" + key)]["after"] == value
        assert changes[("src-c", "/" + key)]["before_present"] is False
    assert ("src-b", "/source_id") not in changes
    assert ("src-b", "", "SOURCE_REMOVED_NOT_A_GRANT") in {
        (f["source_id"], f["pointer"], f["code"]) for f in report["review_flags"]}


def test_a1_changes_are_sorted_by_source_id_then_pointer():
    left = [_row("b"), _row("a")]
    right = [_row("a", notice="n2", attribution="c2"), _row("b", license="l2")]
    report = rd.compare_rights(_envelope(left), _envelope(right))
    keys = [(c["source_id"], c["pointer"]) for c in report["changes"]]
    assert keys == [("a", "/attribution"), ("a", "/notice"), ("b", "/license")]


def test_a1_duplicate_source_ids_are_invalid():
    rows = [_row("src-a"), _row("src-a", attribution="other")]
    report = _expect_invalid(_envelope(rows), _envelope([_row("src-a")]), "DUPLICATE_SOURCE_ID")
    assert {"side": "left", "code": "DUPLICATE_SOURCE_ID", "pointer": "/rows/1/source_id"} in report["errors"]


def test_a1_unsupported_shapes_are_invalid():
    good = _envelope([_row()])
    cases = []
    cases.append(("ENVELOPE_NOT_OBJECT", ["not", "an", "object"]))
    cases.append(("SCHEMA_UNSUPPORTED", dict(good, schema="sc-rights-observation-v2")))
    cases.append(("ENVELOPE_FIELD_MISSING", _envelope([_row()], drop=("rows",))))
    cases.append(("ENVELOPE_FIELD_MISSING", _envelope([_row()], drop=("canonical_rows_sha256",))))
    cases.append(("ROWS_NOT_ARRAY", dict(good, rows={"src-a": _row()})))
    rows = ["text-row"]
    cases.append(("ROW_NOT_OBJECT", _envelope(rows)))
    rows = [{k: v for k, v in _row().items() if k != "source_id"}]
    cases.append(("SOURCE_ID_INVALID", _envelope(rows)))
    cases.append(("SOURCE_ID_INVALID", _envelope([_row("")])))
    cases.append(("SOURCE_ID_INVALID", _envelope([dict(_row(), source_id=7)])))
    cases.append(("SOURCE_ID_INVALID", _envelope([dict(_row(), source_id=None)])))
    cases.append(("ROW_VALUE_UNSUPPORTED", _envelope([_row(attribution=["a", "b"])])))
    cases.append(("ROW_VALUE_UNSUPPORTED", _envelope([_row(attribution={"text": "x"})])))
    cases.append(("ROW_VALUE_UNSUPPORTED", _envelope([_row(reviewed_on=20260301)])))
    cases.append(("ROW_VALUE_UNSUPPORTED", _envelope([_row(reviewed_on=1.5)])))
    cases.append(("CANONICAL_ROWS_SHA256_MISMATCH", _envelope([_row()], digest="0" * 64)))
    cases.append(("CANONICAL_ROWS_SHA256_INVALID", _envelope([_row()], digest="ABC")))
    cases.append(("SOURCE_USE_INVALID", _envelope([_row()], source_use="commercial")))
    cases.append(("ROW_CAP_EXCEEDED", _envelope([_row(f"s{i:05d}") for i in range(rd.ROW_CAP + 1)])))
    for code, bad in cases:
        _expect_invalid(bad, good, code)
        _expect_invalid(good, bad, code)


MALFORMED_SOURCE_USES = ([], {}, ["noncommercial"], {"use": "noncommercial"}, 7, 1.5, True, False, "",
                         "Noncommercial", "for profit")


def test_a1_malformed_source_use_is_invalid_in_api_and_cli():
    """Containers and scalars outside the two profiles are INVALID on either side, never an exception."""
    rows = [_row()]
    good = _envelope(rows)
    work = _fresh_dir()
    good_path = _write(work / "good.json", good)
    for index, value in enumerate(MALFORMED_SOURCE_USES):
        bad = _envelope(rows, source_use=value)
        for left, right, side in ((bad, good, "left"), (good, bad, "right")):
            report = _expect_invalid(left, right, "SOURCE_USE_INVALID")
            assert {"side": side, "code": "SOURCE_USE_INVALID", "pointer": "/source_use"} in report["errors"], value
        bad_path = _write(work / f"bad-{index}.json", bad)
        for left_path, right_path in ((bad_path, good_path), (good_path, bad_path)):
            out = work / f"out-{index}.json"
            assert _cli(left_path, right_path, out) == 2, value
            assert not out.exists(), value
    # Preserved controls: both valid profiles compare; missing and null stay UNVERIFIED.
    for profile in ("noncommercial", "for-profit"):
        assert rd.compare_rights(_envelope(rows, source_use=profile),
                                 _envelope(rows, source_use=profile))["status"] == "COMPARED"
    for absent in (_envelope(rows, source_use=None), _envelope(rows, drop=("source_use",))):
        report = rd.compare_rights(good, absent)
        assert report["status"] == "UNVERIFIED" and "RIGHT_SOURCE_USE_ABSENT" in report["unverified_reasons"]


def test_a1_membership_only_changes_set_changed():
    """Adding or removing a source_id-only row is a change even with no field diffs."""
    bare = [{"source_id": "bare"}]
    added = rd.compare_rights(_envelope([]), _envelope(bare))
    assert added["status"] == "COMPARED" and added["sources_added"] == ["bare"]
    assert added["changes"] == [] and added["changed"] is True
    removed = rd.compare_rights(_envelope(bare), _envelope([]))
    assert removed["sources_removed"] == ["bare"] and removed["changes"] == [] and removed["changed"] is True
    same = rd.compare_rights(_envelope(bare), _envelope(copy.deepcopy(bare)))
    assert same["changes"] == [] and same["sources_added"] == [] and same["sources_removed"] == []
    assert same["changed"] is False


def test_a1_row_cap_boundary_is_accepted():
    rows = [{"source_id": f"s{i:05d}"} for i in range(rd.ROW_CAP)]
    report = rd.compare_rights(_envelope(rows), _envelope(rows))
    assert report["status"] == "COMPARED" and report["row_counts"]["left"] == rd.ROW_CAP


def test_a1_empty_inputs_give_a_truthful_empty_report():
    report = rd.compare_rights(_envelope([]), _envelope([]))
    assert report["status"] == "COMPARED" and report["changes"] == []
    assert report["row_counts"] == {"left": 0, "right": 0}
    assert report["coverage_claim"] == "observed-rows-only"
    assert {"side": "left", "code": "EMPTY_OBSERVATION"} in report["notes"]
    assert {"side": "right", "code": "EMPTY_OBSERVATION"} in report["notes"]
    one_side = rd.compare_rights(_envelope([]), _envelope([_row()]))
    assert one_side["sources_added"] == ["src-a"]
    assert {"side": "left", "code": "EMPTY_OBSERVATION"} in one_side["notes"]


def test_a1_input_pins_are_carried():
    left, right = _envelope([_row()]), _envelope([_row(notice="n")])
    report = rd.compare_rights(left, right)
    assert report["input_pins"]["left"]["canonical_rows_sha256"] == left["canonical_rows_sha256"]
    assert report["input_pins"]["right"]["canonical_rows_sha256"] == right["canonical_rows_sha256"]
    assert report["input_pins"]["left"]["producer"] == _producer()
    assert report["input_pins"]["left"]["source_use"] == "noncommercial"
    assert report["input_pins"]["left"]["file_sha256"] is None


def test_a1_compare_does_not_mutate_inputs():
    left, right = _envelope([_row()]), _envelope([_row(notice="n")])
    left_copy, right_copy = copy.deepcopy(left), copy.deepcopy(right)
    rd.compare_rights(left, right)
    assert left == left_copy and right == right_copy


# ---------------------------------------------------------------- A2 producer contract

def _producer_rows(name):
    document = rd.parse_json_strict((FIXTURES / name).read_bytes())
    return [rights.source_rights(row, use="noncommercial", today=FIXED_TODAY) for row in document["rows"]]


def _measured_producer():
    module_file = Path(rights.__file__).resolve()
    digest = hashlib.sha256(module_file.read_bytes()).hexdigest()
    return _producer(module_sha256=digest)


def test_a2_actual_source_rights_reproduces_the_frozen_rows():
    for side in ("left", "right"):
        frozen = rd.parse_json_strict((FIXTURES / f"observation_{side}.json").read_bytes())
        produced = _producer_rows(f"producer_inputs_{side}.json")
        assert produced == frozen["rows"], side
        assert _canonical_rows_sha256(produced) == frozen["canonical_rows_sha256"], side
    csumb = [r for r in _producer_rows("producer_inputs_left.json") if r["source_id"] == "synthetic-csumb-a"]
    assert csumb[0]["attribution"] == EXACT_CSUMB_CREDIT
    assert csumb[0]["notice"] == EXACT_CSUMB_NOTICE
    assert csumb[0]["navigation_use"] is False and csumb[0]["commercial_use"] == "permission-required"


def test_a2_frozen_observation_bytes_are_bound_to_the_measured_producer():
    measured = _measured_producer()
    for side in ("left", "right"):
        frozen_bytes = (FIXTURES / f"observation_{side}.json").read_bytes()
        frozen = rd.parse_json_strict(frozen_bytes)
        assert frozen["producer"] == _producer(), side
        fresh = rd.build_observation(_producer_rows(f"producer_inputs_{side}.json"),
                                     producer=measured, source_use="noncommercial")
        if measured["module_sha256"] == PIN_MODULE_SHA256:
            assert rd.serialize_json(fresh) == frozen_bytes, side
            assert rd.compare_rights(frozen, fresh)["status"] == "COMPARED"
        else:
            # A later rights.py is a different producer: the frozen observation must not
            # silently compare against it, even though its rows may be unchanged.
            report = rd.compare_rights(frozen, fresh)
            assert report["status"] == "UNVERIFIED" and "PRODUCER_MISMATCH" in report["unverified_reasons"]


def test_a2_feature_rights_rows_match_source_rights_rows():
    document = rd.parse_json_strict((FIXTURES / "producer_inputs_left.json").read_bytes())
    sources = {row["id"]: row for row in document["rows"]}
    # feature_rights uses date.today(); the fixture review date is in the past, so this is stable.
    listed = rights.feature_rights(list(reversed(list(sources))), sources)
    assert listed == sorted(_producer_rows("producer_inputs_left.json"), key=lambda r: r["source_id"])
    observation = rd.build_observation(listed, producer=_producer(function="feature_rights"),
                                       source_use="noncommercial")
    assert rd.compare_rights(observation, observation)["changes"] == []


def test_a2_frozen_cli_report_bytes():
    out = _fresh_dir() / "delta.json"
    left, right = FIXTURES / "observation_left.json", FIXTURES / "observation_right.json"
    code = _cli(left, right, out, "--left-sha256", hashlib.sha256(left.read_bytes()).hexdigest(),
                "--right-sha256", hashlib.sha256(right.read_bytes()).hexdigest())
    assert code == 0
    assert out.read_bytes() == (FIXTURES / "expected_delta.json").read_bytes()


def test_a2_frozen_delta_content():
    report = rd.parse_json_strict((FIXTURES / "expected_delta.json").read_bytes())
    changes = _changes_by(report)
    assert report["status"] == "COMPARED" and report["sources_added"] == ["synthetic-usgov-c"]
    assert report["sources_removed"] == ["synthetic-usgov-b"]
    assert changes[("synthetic-csumb-a", "/reviewed_on")]["before"] == "2026-03-01"
    assert changes[("synthetic-csumb-a", "/reviewed_on")]["after"] == "2026-09-15"
    assert changes[("synthetic-usgov-a", "/attribution")]["after"] == "Synthetic NOAA  survey fixture"
    assert changes[("synthetic-usgov-a", "/policy_url")]["after"] == ""
    assert changes[("synthetic-usgov-c", "/attribution")]["after"] == "Synthetic USGS survey fixture <b>bold</b>"
    assert ("synthetic-csumb-a", "/attribution") not in changes
    for side in ("left", "right"):
        path = FIXTURES / f"observation_{side}.json"
        assert report["input_pins"][side]["file_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------- A3 negative and preservation

def test_a3_missing_producer_with_identical_rows_is_unverified():
    rows = [_row()]
    for left, right, reason in ((_envelope(rows, drop=("producer",)), _envelope(rows), "LEFT_PRODUCER_ABSENT"),
                                (_envelope(rows), _envelope(rows, producer=None), "RIGHT_PRODUCER_ABSENT")):
        report = rd.compare_rights(left, right)
        assert report["status"] == "UNVERIFIED" and reason in report["unverified_reasons"]
        assert report["changes"] is None


def test_a3_partial_producer_with_identical_rows_is_unverified():
    rows = [_row()]
    partial = _producer()
    partial.pop("module_sha256")
    report = rd.compare_rights(_envelope(rows, producer=partial), _envelope(rows))
    assert report["status"] == "UNVERIFIED" and "LEFT_PRODUCER_INCOMPLETE" in report["unverified_reasons"]
    assert {"pointer": "/producer/module_sha256", "before_present": False, "before": None,
            "after_present": True, "after": PIN_MODULE_SHA256} in report["binding_mismatches"]


def test_a3_missing_source_use_is_unverified():
    rows = [_row()]
    report = rd.compare_rights(_envelope(rows), _envelope(rows, drop=("source_use",)))
    assert report["status"] == "UNVERIFIED" and "RIGHT_SOURCE_USE_ABSENT" in report["unverified_reasons"]


def test_a3_mismatched_producer_with_identical_rows_is_unverified():
    rows = [_row(), _csumb_row()]
    for key, value in (("module_sha256", "a" * 64), ("code_commit", "b" * 40), ("function", "feature_rights")):
        report = rd.compare_rights(_envelope(rows), _envelope(rows, producer=_producer(**{key: value})))
        assert report["status"] == "UNVERIFIED", key
        assert "PRODUCER_MISMATCH" in report["unverified_reasons"], key
        assert report["changes"] is None, key
        assert {"pointer": "/producer/" + key, "before_present": True, "before": _producer()[key],
                "after_present": True, "after": value} in report["binding_mismatches"], key


def test_a3_malformed_or_extended_producer_is_invalid():
    rows = [_row()]
    good = _envelope(rows)
    for code, producer in (("PRODUCER_INVALID", _producer(code_commit=PIN_COMMIT.upper())),
                           ("PRODUCER_INVALID", _producer(module_sha256="z" * 64)),
                           ("PRODUCER_INVALID", _producer(module_path="src/skippercast/seafloor/other.py")),
                           ("PRODUCER_INVALID", _producer(function="check_deployment")),
                           ("PRODUCER_INVALID", "producer-as-text"),
                           ("UNKNOWN_FIELD", _producer(reviewed_by="legal"))):
        _expect_invalid(_envelope(rows, producer=producer), good, code)


def test_a3_unknown_authority_bearing_fields_are_invalid():
    good = _envelope([_row()])
    _expect_invalid(_envelope([_row(publication_allowed=True)]), good, "UNKNOWN_FIELD")
    _expect_invalid(_envelope([_row(legal_approval="approved")]), good, "UNKNOWN_FIELD")
    _expect_invalid(dict(good, semantic_approval=True), good, "UNKNOWN_FIELD")


def test_a3_source_ids_differing_only_in_case_are_distinct_sources():
    report = rd.compare_rights(_envelope([_row("Src-A")]), _envelope([_row("src-a")]))
    assert report["status"] == "COMPARED"
    assert report["sources_added"] == ["src-a"] and report["sources_removed"] == ["Src-A"]
    assert {"code": "SOURCE_ID_CASE_VARIANT", "source_ids": ["Src-A", "src-a"]} in report["notes"]
    both = rd.compare_rights(_envelope([_row("Src-A"), _row("src-a")]), _envelope([_row("Src-A"), _row("src-a")]))
    assert both["status"] == "COMPARED" and both["changes"] == []


def test_a3_whitespace_or_case_only_credit_change_is_reported():
    """Exact regression for a comparator that normalizes credit/notice text."""
    before = _csumb_row(attribution=EXACT_CSUMB_CREDIT, notice=EXACT_CSUMB_NOTICE)
    after = _csumb_row(attribution=EXACT_CSUMB_CREDIT.replace("Seafloor Mapping", "Seafloor  Mapping") + " ",
                       notice=EXACT_CSUMB_NOTICE.replace("Not for navigation.", "not for navigation."))
    report = rd.compare_rights(_envelope([before]), _envelope([after]))
    changes = _changes_by(report)
    assert set(changes) == {("csumb-a", "/attribution"), ("csumb-a", "/notice")}
    assert changes[("csumb-a", "/attribution")]["after"] == after["attribution"]
    assert changes[("csumb-a", "/notice")]["before"] == EXACT_CSUMB_NOTICE


def test_a3_malicious_display_strings_are_kept_raw_and_escaped():
    hostile = "<script>alert(1)</script>\x1b[2J\u202e\u0000\r\n\"quoted\" \\ end"
    out = _fresh_dir() / "delta.json"
    work = out.parent
    left = _write(work / "left.json", _envelope([_row()]))
    right = _write(work / "right.json", _envelope([_row(attribution=hostile, notice="</textarea>{{x}}${y}")]))
    assert _cli(left, right, out) == 0
    raw = out.read_bytes()
    assert all(b == 0x0A or 0x20 <= b < 0x7F for b in raw)
    assert b"\\u202e" in raw and b"\\u001b" in raw and b"\\u0000" in raw
    report = rd.parse_json_strict(raw)
    assert _changes_by(report)[("src-a", "/attribution")]["after"] == hostile


def test_a3_reordered_rows_give_no_field_changes_but_are_recorded():
    rows = [_row("a"), _row("b")]
    report = rd.compare_rights(_envelope(rows), _envelope(list(reversed(rows))))
    assert report["status"] == "COMPARED" and report["changes"] == []
    assert report["row_order_changed"] is True
    assert (report["input_pins"]["left"]["canonical_rows_sha256"]
            != report["input_pins"]["right"]["canonical_rows_sha256"])
    same = rd.compare_rights(_envelope(rows), _envelope(rows))
    assert same["row_order_changed"] is False


def test_a3_duplicate_json_keys_and_nonfinite_values_are_invalid_without_output():
    work = _fresh_dir()
    good = _write(work / "good.json", _envelope([_row()]))
    body = json.dumps(_envelope([_row()]), sort_keys=True)
    cases = {"dup-top.json": body.replace('"schema":', '"schema": "x", "schema":', 1),
             "dup-row.json": body.replace('"attribution":', '"attribution": "hidden", "attribution":', 1),
             "nan.json": body.replace('"notice": "', '"nan": NaN, "notice": "', 1),
             "inf.json": body.replace('"notice": "', '"inf": -Infinity, "notice": "', 1),
             "not-json.json": body[:-3],
             "bad-utf8.json": None}
    for name, text in cases.items():
        data = b'{"schema": "\xff"}' if text is None else text.encode()
        assert data != body.encode(), name
        bad = _write(work / name, data)
        out = work / ("out-" + name)
        assert _cli(bad, good, out) == 2, name
        assert not out.exists(), name
        assert _cli(good, bad, out) == 2, name
        assert not out.exists(), name
        assert bad.read_bytes() == data, name


def test_a3_lone_surrogate_text_is_invalid():
    rows = [_row(attribution="\ud800")]
    bad = {"schema": "sc-rights-observation-v1", "producer": _producer(), "source_use": "noncommercial",
           "rows": rows, "canonical_rows_sha256": "0" * 64}
    _expect_invalid(bad, _envelope([_row()]), "ROW_TEXT_NOT_UTF8")


def test_a3_unverified_cli_exit_and_report():
    work = _fresh_dir()
    left = _write(work / "left.json", _envelope([_row()]))
    right = _write(work / "right.json", _envelope([_row()], source_use="for-profit"))
    out = work / "delta.json"
    assert _cli(left, right, out) == 3
    report = rd.parse_json_strict(out.read_bytes())
    assert report["status"] == "UNVERIFIED" and report["changes"] is None


def test_a3_symlink_fifo_and_special_inputs_are_refused():
    work = _fresh_dir()
    good = _write(work / "good.json", _envelope([_row()]))
    link = work / "link.json"
    os.symlink(good, link)
    linked_dir = work / "linked-dir"
    os.symlink(work, linked_dir)
    fifo = work / "fifo.json"
    os.mkfifo(fifo)
    directory = work / "a-directory"
    directory.mkdir()
    for bad in (link, linked_dir / "good.json", fifo, directory, work / "missing.json"):
        out = work / "out.json"
        assert _cli(bad, good, out) == 4, bad
        assert _cli(good, bad, out) == 4, bad
        assert not out.exists(), bad
    assert stat.S_ISFIFO(os.lstat(fifo).st_mode)


def _load_runner():
    import importlib.util
    path = REPO / "scripts" / "accept_sc_rights_delta.py"
    spec = importlib.util.spec_from_file_location("sc_rights_delta_runner_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _cancelled_symlink_tree():
    """work/link -> work/elsewhere/deep, so link/.. is physically work/elsewhere, lexically work."""
    work = _fresh_dir()
    deep = work / "elsewhere" / "deep"
    deep.mkdir(parents=True)
    os.symlink(deep, work / "link")
    good = _write(work / "good.json", _envelope([_row()]))
    _write(work / "elsewhere" / "good.json", _envelope([_row(notice="physical target")]))
    prior = _write(work / "prior.json", b"prior evidence\n")
    return work, good, prior


def _snapshot(root):
    return sorted((str(p.relative_to(root)), p.is_symlink() or p.is_dir() or p.read_bytes())
                  for p in root.rglob("*"))


def test_a3_cancelled_symlink_component_paths_are_refused():
    """A symlink or '..' component cancelled by lexical normalization must not evade refusal."""
    work, good, prior = _cancelled_symlink_tree()
    before = _snapshot(work)
    cwd = os.getcwd()
    try:
        os.chdir(work)
        bad_inputs = (str(work / "link" / ".." / "good.json"), os.path.join("link", "..", "good.json"),
                      str(work / "elsewhere" / ".." / "good.json"), os.path.join(".", "..", work.name, "good.json"))
        for bad in bad_inputs:
            out = work / "out.json"
            assert _cli(bad, good, out) == 4, bad
            assert _cli(good, bad, out) == 4, bad
            assert not out.exists(), bad
        bad_outputs = (str(work / "link" / ".." / "through.json"), os.path.join("link", "..", "through.json"),
                       str(work / "link" / ".." / "prior.json"), os.path.join("elsewhere", "..", "through.json"))
        for bad in bad_outputs:
            assert _cli(good, good, bad) == 4, bad
            assert not (work / "through.json").exists() and not (work / "elsewhere" / "through.json").exists()
        assert prior.read_bytes() == b"prior evidence\n"
        assert _snapshot(work) == before

        runner = _load_runner()
        for bad in (str(work / "link" / ".." / "run-abs"), os.path.join("link", "..", "run-rel")):
            try:
                runner.make_run_root(bad)
            except SystemExit as refusal:
                assert "refused" in str(refusal.code), bad
            else:
                raise AssertionError(f"runner admitted cancelled run root {bad}")
        assert _snapshot(work) == before

        # Ordinary absolute and relative paths still work.
        assert _cli(str(good), "good.json", str(work / "ok-abs.json")) == 0
        assert _cli("good.json", str(good), "ok-rel.json") == 0
        assert (work / "ok-abs.json").is_file() and (work / "ok-rel.json").is_file()
        made = runner.make_run_root("run-ok")
        assert made == work / "run-ok" and (made / "tmp").is_dir()
    finally:
        os.chdir(cwd)


def test_a3_oversized_input_is_refused_before_parsing():
    work = _fresh_dir()
    good = _write(work / "good.json", _envelope([_row()]))
    big = _write(work / "big.json", b" " * (rd.INPUT_FILE_CAP + 1))
    out = work / "out.json"
    assert _cli(big, good, out) == 4 and not out.exists()
    edge = _write(work / "edge.json", rd.serialize_json(_envelope([_row()])).ljust(rd.INPUT_FILE_CAP, b" "))
    assert _cli(edge, good, out) == 0 and out.exists()


def test_a3_expected_hash_mismatch_is_refused():
    work = _fresh_dir()
    good = _write(work / "good.json", _envelope([_row()]))
    out = work / "out.json"
    assert _cli(good, good, out, "--left-sha256", "0" * 64) == 4 and not out.exists()
    assert _cli(good, good, out, "--right-sha256", "not-a-hash") == 4 and not out.exists()


def test_a3_existing_or_symlinked_output_is_refused_and_unchanged():
    work = _fresh_dir()
    good = _write(work / "good.json", _envelope([_row()]))
    existing = _write(work / "existing.json", b"previous report\n")
    assert _cli(good, good, existing) == 4
    assert existing.read_bytes() == b"previous report\n"
    target = work / "real-out"
    target.mkdir()
    link_dir = work / "out-link"
    os.symlink(target, link_dir)
    assert _cli(good, good, link_dir / "delta.json") == 4
    assert list(target.iterdir()) == []
    dangling = work / "dangling.json"
    os.symlink(work / "nowhere.json", dangling)
    assert _cli(good, good, dangling) == 4
    assert not (work / "nowhere.json").exists()
    assert _cli(good, good, work / "no-such-dir" / "delta.json") == 4


def test_a3_output_is_deterministic_json_only():
    work = _fresh_dir()
    left = _write(work / "left.json", _envelope([_row("b"), _row("a")]))
    right = _write(work / "right.json", _envelope([_row("a", notice="n")]))
    first, second = work / "one.json", work / "two.json"
    assert _cli(left, right, first) == 0 and _cli(left, right, second) == 0
    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"}\n")
    report = rd.parse_json_strict(first.read_bytes())
    assert report["input_pins"]["left"]["file_sha256"] == hashlib.sha256(left.read_bytes()).hexdigest()
    assert report["semantic_approval"] is False and report["publication_allowed"] is False
