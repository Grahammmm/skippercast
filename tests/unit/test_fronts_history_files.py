"""Offline contracts at the SST fronts history filesystem boundary."""

import json
import os
from hashlib import sha256

import pytest

from skippercast.pipeline.fronts_history_files import (
    FrontsHistoryError,
    FrontsHistoryWrite,
    write_fronts_history,
)


DAY = "2026-11-08"
LIVE = "sst-fronts.json"
INDEX = "sst-fronts/index.json"
SOURCE = b'{ "region_id": "test-region", "layer_id": "sst-fronts", "fronts": [] }\r\n'


@pytest.fixture
def region(tmp_path):
    region_dir = tmp_path / "test-region"
    region_dir.mkdir()
    return region_dir


def _put(region, relative_path, content):
    path = region / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _tree(region):
    # Include directory entries as well as file bytes, to catch an early mkdir.
    return {
        path.relative_to(region).as_posix(): None if path.is_dir() else path.read_bytes()
        for path in region.rglob("*")
    }


def _record(day, content):
    return {"date": day, "path": f"sst-fronts/{day}.json", "sha256": sha256(content).hexdigest()}


def _index_bytes(index):
    return (json.dumps(index, separators=(",", ":")) + "\n").encode()


@pytest.mark.parametrize("content", [
    None,
    b"{",
    b"\xff",
    b"[]",
    b'{"region_id":"other-region","layer_id":"sst-fronts"}',
    b'{"region_id":"test-region","layer_id":"other-layer"}',
    b'{"region_id":"test-region","layer_id":"sst-fronts","value":NaN}',
    b'{"region_id":"test-region","layer_id":"sst-fronts","value":Infinity}',
    b'{"region_id":"test-region","layer_id":"sst-fronts","value":-Infinity}',
], ids=["missing", "malformed", "bad-encoding", "not-object", "wrong-region", "wrong-layer",
        "nan", "infinity", "negative-infinity"])
def test_c1_invalid_live_document_leaves_existing_history_untouched(region, content):
    """C1: Reject bad live input before a dated file or index can be changed."""
    _put(region, INDEX, b"[]\n")
    _put(region, "sst-fronts/2026-11-07.json", SOURCE)
    if content is not None:
        _put(region, LIVE, content)
    before = _tree(region)

    with pytest.raises(FrontsHistoryError) as error:
        write_fronts_history(region, DAY, DAY)

    assert type(error.value) is FrontsHistoryError
    assert isinstance(error.value, ValueError)
    assert _tree(region) == before


def test_c2_first_write_copies_exact_source_bytes(region):
    """C2: Re-serializing the source would lose its original whitespace and CRLF."""
    _put(region, LIVE, SOURCE)
    row = _record(DAY, SOURCE)

    result = write_fronts_history(str(region), DAY, DAY)

    assert type(result) is FrontsHistoryWrite
    assert result == FrontsHistoryWrite([row], True, (), ())
    assert _tree(region) == {
        LIVE: SOURCE, "sst-fronts": None, row["path"]: SOURCE, INDEX: _index_bytes([row]),
    }


def test_c2_same_bytes_rerun_does_not_touch_dated_file(region):
    """C2: A byte-only comparison would miss an unnecessary rewrite of the dated file."""
    _put(region, LIVE, SOURCE)
    row = _record(DAY, SOURCE)
    dated = _put(region, row["path"], SOURCE)
    _put(region, INDEX, _index_bytes([row]))
    os.utime(dated, (1_700_000_000, 1_700_000_000))
    before_metadata = (dated.stat().st_ino, dated.stat().st_mtime_ns)
    before = _tree(region)

    assert write_fronts_history(region, DAY, DAY) == FrontsHistoryWrite([row], False, (), ())
    assert (dated.stat().st_ino, dated.stat().st_mtime_ns) == before_metadata
    assert _tree(region) == before


def test_c2_different_bytes_refuse_without_repairing_index(region):
    """C2: Equivalent JSON is not identical bytes; refuse even if the index needs repair."""
    _put(region, LIVE, SOURCE)
    _put(region, _record(DAY, SOURCE)["path"], SOURCE.strip())
    _put(region, INDEX, b"not json")
    before = _tree(region)

    with pytest.raises(FrontsHistoryError) as error:
        write_fronts_history(region, DAY, DAY)

    assert type(error.value) is FrontsHistoryError
    assert _tree(region) == before


def test_c3_indexes_second_day_newest_first(region):
    """C3: A writer that rebuilds from just the live file would lose the earlier row."""
    first = _record(DAY, SOURCE)
    _put(region, first["path"], SOURCE)
    _put(region, INDEX, _index_bytes([first]))
    second_day = "2026-11-09"
    second_source = SOURCE.strip()
    _put(region, LIVE, second_source)
    second = _record(second_day, second_source)
    index = [second, first]

    assert write_fronts_history(region, second_day, second_day) == FrontsHistoryWrite(index, True, (), ())
    assert _tree(region) == {
        LIVE: second_source, "sst-fronts": None, first["path"]: SOURCE,
        second["path"]: second_source, INDEX: _index_bytes(index),
    }


@pytest.mark.parametrize(("previous", "dropped"), [
    (b"[", ((-1, "unreadable"),)),
    (b"\xff", ((-1, "unreadable"),)),
    (b"{}", ((-1, "not a list"),)),
    (b"[null,{}]", ((0, "not a dict"), (1, "bad date"))),
], ids=["invalid-json", "bad-encoding", "wrong-shape", "bad-rows"])
def test_c3_reports_previous_index_failures_and_rewrites_pointer(region, previous, dropped):
    """C3: Distinguish decoder failures from the index rule's ordered drop reasons."""
    _put(region, LIVE, SOURCE)
    _put(region, INDEX, previous)
    row = _record(DAY, SOURCE)

    assert write_fronts_history(region, DAY, DAY) == FrontsHistoryWrite([row], True, (), dropped)
    assert _tree(region) == {
        LIVE: SOURCE, "sst-fronts": None, row["path"]: SOURCE, INDEX: _index_bytes([row]),
    }


@pytest.mark.parametrize(("day", "today", "keep_days"), [
    ("2026-11-01", DAY, 7),
    (DAY, DAY, 0),
    ("../2026-11-08", DAY, 7),
    (DAY, "2026-02-30", 7),
], ids=["outside-window", "bad-keep-days", "bad-day", "bad-today"])
@pytest.mark.parametrize("with_index", [False, True], ids=["no-index", "unreadable-index"])
def test_c3_propagates_rule_errors_without_creating_or_repairing_files(region, day, today, keep_days, with_index):
    """C3: Validate the rule before mkdir, dated writes, or repairing an unreadable index."""
    _put(region, LIVE, SOURCE)
    if with_index:
        _put(region, INDEX, b"[")
    before = _tree(region)

    with pytest.raises(ValueError) as error:
        write_fronts_history(region, day, today, keep_days)

    assert type(error.value) is ValueError
    assert _tree(region) == before


def test_c4_eighth_day_reports_sorted_stale_names_without_pruning(region):
    """C4: Trim the pointer, not the dated files; ignore decoys and preserve siblings."""
    previous = [_record(f"2026-11-0{n}", SOURCE) for n in range(7, 0, -1)]
    for row in previous:
        _put(region, row["path"], SOURCE)
    _put(region, INDEX, _index_bytes(previous))
    _put(region, LIVE, SOURCE)
    _put(region, "habitat-dynamics.json", b"{}\n")
    _put(region, "sst-fronts/2026-10-31.json", b"unindexed dated file")
    _put(region, "sst-fronts/2026-02-30.json", b"not a calendar date")
    _put(region, "sst-fronts/2026-10-30.json/2026-10-29.json", b"nested, not a history file")
    _put(region, "sst-fronts/index.json.tmp", b"unrelated temporary file")
    before = _tree(region)
    latest = _record(DAY, SOURCE)
    index = [latest, *previous[:-1]]

    assert write_fronts_history(region, DAY, DAY) == FrontsHistoryWrite(
        index, True, ("2026-10-31.json", "2026-11-01.json"), (),
    )
    assert _tree(region) == before | {latest["path"]: SOURCE, INDEX: _index_bytes(index)}
