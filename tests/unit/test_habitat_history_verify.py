"""C1–C3: verify local history bytes before a manifest can refer to them."""

import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from skippercast.pipeline.habitat_history_verify import verify_history

REGION = "fixture-region"
LAYER = {
    "id": "sst-analysis",
    "fields": ["latitude", "longitude", "temperature_c", "analysis_error_c"],
    "resolution_degrees": [0.125, 0.125],
}
BOUNDS = [0, 0, 1, 1]
SAMPLE = "1970-01-02T00:00:00Z"
EPOCH = 86400
TILE_PATH = "habitat-history/sst-0123456789abcdef.json"


def _tile(epoch=EPOCH):
    return {
        "schema_version": 1,
        "region_id": REGION,
        "layer_id": LAYER["id"],
        "fields": LAYER["fields"],
        "resolution_degrees": LAYER["resolution_degrees"],
        "bounds": BOUNDS,
        "frames": [{"time": epoch, "cells": [[0.5, 0.5, 14.0, 0.2], [0, 0, None, True]]}],
    }


def _write(target: Path, data: bytes, name: str = TILE_PATH) -> dict:
    path = target / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(data)
    return {"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "bounds": BOUNDS}


def _check(target: Path, *refs: dict, sample: str = SAMPLE) -> list[tuple[str, str]]:
    return verify_history(target, REGION, LAYER, [{"sample_at": sample, "tiles": list(refs)}])


def test_c1_accepts_empty_history(tmp_path):
    # An initial run with no history should not invent a refusal.
    assert verify_history(tmp_path, REGION, LAYER, []) == []


def test_c1_keeps_passed_day_and_does_not_mutate_run(tmp_path):
    data = json.dumps(_tile()).encode()
    ref = _write(tmp_path, data)
    path = tmp_path / ref["path"]
    history = [{"sample_at": SAMPLE, "tiles": [ref]}, {"sample_at": "1970-01-01T00:00:00Z", "tiles": [ref]}]
    history_before = json.dumps(history)
    before = (tuple(tmp_path.rglob("*")), path.read_bytes(), path.stat().st_mtime_ns)

    # Reusing the first day's tile cannot satisfy the second day or rewrite it.
    assert verify_history(tmp_path, REGION, LAYER, history) == [("1970-01-01T00:00:00Z", "frames")]
    assert (tuple(tmp_path.rglob("*")), path.read_bytes(), path.stat().st_mtime_ns) == before
    assert json.dumps(history) == history_before


def test_c1_reports_all_refused_days_in_supplied_order(tmp_path):
    # Do not sort by time, deduplicate, or stop after the first bad day.
    days = [
        {"sample_at": SAMPLE, "tiles": [{"path": "invalid"}]},
        {"sample_at": "1970-01-01T00:00:00Z", "tiles": [{"path": TILE_PATH}]},
        {"sample_at": SAMPLE, "tiles": [{"path": TILE_PATH}]},
    ]
    assert verify_history(tmp_path, REGION, LAYER, days) == [
        (SAMPLE, "path"), ("1970-01-01T00:00:00Z", "missing"), (SAMPLE, "missing"),
    ]


@pytest.mark.parametrize("name", [None, "../sst-0123456789abcdef.json", TILE_PATH + "\n", TILE_PATH.upper()])
def test_c2_rejects_bad_path_before_lookup(tmp_path, name):
    assert _check(tmp_path, {"path": name}) == [(SAMPLE, "path")]


def test_c2_missing_ref_file(tmp_path):
    assert _check(tmp_path, {"path": TILE_PATH}) == [(SAMPLE, "missing")]


@pytest.mark.parametrize("change,reason", [({"bytes": 99, "sha256": "wrong"}, "bytes"), ({"sha256": "wrong"}, "sha256")])
def test_c2_checks_length_then_hash_before_decoding(tmp_path, change, reason):
    # Deliberately broken JSON must not hide a length or digest failure.
    ref = _write(tmp_path, b"{")
    assert _check(tmp_path, ref | change) == [(SAMPLE, reason)]


def test_c2_stops_at_first_bad_ref_not_first_or_last_ref(tmp_path):
    valid = _write(tmp_path, json.dumps(_tile()).encode())
    missing = {"path": "habitat-history/missing-0123456789abcdef.json"}
    # A passing first tile does not certify the day, and later failures do not replace the reason.
    assert _check(tmp_path, valid, missing, {"path": "invalid"}) == [(SAMPLE, "missing")]


@pytest.mark.parametrize("data", [b"{", b"[]", b'{"schema_version":NaN}'])
def test_c2_rejects_authenticated_non_object_or_invalid_json(tmp_path, data):
    assert _check(tmp_path, _write(tmp_path, data)) == [(SAMPLE, "identity")]


@pytest.mark.parametrize("change", [
    {"schema_version": True}, {"schema_version": 2}, {"region_id": "other-region"},
    {"layer_id": "chlorophyll-observation"}, {"fields": LAYER["fields"][::-1]},
    {"resolution_degrees": [0.125, 0.25]},
])
def test_c2_rejects_identity_and_grid_changes(tmp_path, change):
    # The expected digest cannot substitute for layer, schema or grid agreement.
    ref = _write(tmp_path, json.dumps(_tile() | change).encode())
    assert _check(tmp_path, ref) == [(SAMPLE, "identity")]


def test_c2_rejects_bounds_that_disagree_with_ref(tmp_path):
    ref = _write(tmp_path, json.dumps(_tile()).encode())
    assert _check(tmp_path, ref | {"bounds": [0, 0, 2, 2]}) == [(SAMPLE, "identity")]


@pytest.mark.parametrize("bounds", [None, [1, 0, 0, 1], [0, 0, 1], [False, 0, 1, 1], [0, 0, 181, 1]])
def test_c2_rejects_missing_or_invalid_tile_bounds_without_ref_bounds(tmp_path, bounds):
    # Omitting the ref bounds skips only the comparison, not the tile's own box validation.
    tile = _tile()
    if bounds is None:
        del tile["bounds"]
    else:
        tile["bounds"] = bounds
    ref = _write(tmp_path, json.dumps(tile).encode())
    del ref["bounds"]
    assert _check(tmp_path, ref) == [(SAMPLE, "identity")]


@pytest.mark.parametrize("ref_bounds", [True, False])
def test_c2_accepts_valid_tile_bounds_with_or_without_ref_bounds(tmp_path, ref_bounds):
    ref = _write(tmp_path, json.dumps(_tile()).encode())
    if not ref_bounds:
        del ref["bounds"]
    assert _check(tmp_path, ref) == []


@pytest.mark.parametrize("frames", [None, [], [0], [{"time": EPOCH - 1, "cells": []}],
                                    [{"time": EPOCH, "cells": {}}], _tile()["frames"] * 2])
def test_c2_requires_exactly_the_selected_frame_and_cell_list(tmp_path, frames):
    ref = _write(tmp_path, json.dumps(_tile() | {"frames": frames}).encode())
    assert _check(tmp_path, ref) == [(SAMPLE, "frames")]


@pytest.mark.parametrize("row", [None, [0, 0, 14], [False, 0, 14, 0], [0, None, 14, 0],
                                 [0, 0, "14", 0], [0, 0, {}, 0], [0, 0, [], 0]])
def test_c2_rejects_bad_rows_even_after_a_good_row(tmp_path, row):
    tile = _tile()
    tile["frames"][0]["cells"].append(row)
    assert _check(tmp_path, _write(tmp_path, json.dumps(tile).encode())) == [(SAMPLE, "frames")]


def test_c2_rejects_json_number_overflow_in_row(tmp_path):
    data = json.dumps(_tile()).replace("14.0", "1e400").encode()
    assert _check(tmp_path, _write(tmp_path, data)) == [(SAMPLE, "frames")]


@pytest.mark.parametrize("sample", [
    "1970-01-02", "1970-01-02T00:00:00", "1970-02-30T00:00:00Z", "1970-01-02T24:00:00Z",
    "1970-01-02T00:00:00.1234Z", "1970-01-02T00:00:00+00:60", "1970-01-02T00:00:00+24:00",
])
def test_c3_rejects_bad_sample_before_any_read(tmp_path, sample):
    # A valid path makes a premature read observable, even if an I/O error would be swallowed.
    with patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected tile read")):
        assert _check(tmp_path, {"path": TILE_PATH}, sample=sample) == [(sample, "sample_at")]


@pytest.mark.parametrize("sample,epoch", [
    ("1970-01-01T19:00:00.125-05:00", 86400.125),
    ("1970-01-02T02:00:00.001+02:00", 86400.001),
    ("1969-12-31T23:59:59.999Z", -0.001),
    ("0000-01-01T00:00:00Z", -62167219200),
])
def test_c3_handles_offsets_milliseconds_and_calendar_range(tmp_path, sample, epoch):
    # The browser compares the resulting epoch seconds, not the nominal local time or whole seconds.
    ref = _write(tmp_path, json.dumps(_tile(epoch)).encode())
    assert _check(tmp_path, ref, sample=sample) == []
