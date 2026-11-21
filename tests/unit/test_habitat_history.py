"""C1–C5: offline coverage of the observed-history producer contract."""

import pytest

from skippercast.pipeline.habitat_history import HistoryUpdate, entry_problem, next_history


_CURRENT = "2026-11-20T00:00:00Z"
_OLDER = "2026-11-18T12:00:00Z"
_EMPTY = HistoryUpdate([], frozenset(), [])


def _ref(index=0, **fields):
    return {"path": f"habitat-history/sst-analysis-{index:016x}.json", "sha256": "a" * 64,
            "bytes": 1, **fields}


def _day(sample_at=_OLDER, index=0):
    return {"sample_at": sample_at, "tiles": [_ref(index)]}


def test_c1_single_result_with_all_three_fields():
    day = _day()
    # Catch returning only the history or a separate second value to unpack.
    assert next_history([None], day, _CURRENT) == HistoryUpdate(
        [day], frozenset({_ref()["path"]}), [(0, "not-object")],
    )


@pytest.mark.parametrize("entry, problem", [
    (None, "not-object"), ([], "not-object"), ({}, "sample_at"),
    ({"sample_at": _OLDER}, "tiles"),
    ({"sample_at": _OLDER, "tiles": ()}, "tiles"),
    ({"sample_at": _OLDER, "tiles": {}}, "tiles"),
    ({"sample_at": _OLDER, "tiles": []}, "tiles"),
    ({"sample_at": _OLDER, "tiles": [_ref(i) for i in range(65)]}, "tiles"),
    ({"sample_at": _OLDER, "tiles": [_ref(i) for i in range(64)]}, None),
    ({"sample_at": _OLDER, "tiles": [_ref(), _ref(bytes=2)]}, "duplicate-path"),
    ({"sample_at": _OLDER, "tiles": [_ref(), _ref(1)], "extra": True}, None),
])
def test_c2_entry_shape_tile_count_and_duplicate_paths(entry, problem):
    # Catch accepting empty/oversize tile arrays or comparing entire refs for uniqueness.
    assert entry_problem(entry) == problem


@pytest.mark.parametrize("sample, problem", [
    (_OLDER, None), ("2026-11-18T12:00:00-08:00", None),
    ("2026-11-18T12:00:00+05:30", None), ("2026-11-18T12:00:00+23:59", None),
    ("2024-02-29T00:00:00.1Z", None), ("2024-02-29T00:00:00.12Z", None),
    ("0000-02-29T23:59:59.123Z", None),
    (None, "sample_at"), (123, "sample_at"),
    ("2026-11-18", "sample_at"), ("2026-11-18T12:00Z", "sample_at"),
    ("2026-11-18T12:00:00", "sample_at"), ("2026-11-18 12:00:00Z", "sample_at"),
    ("2026-11-18T12:00:00z", "sample_at"), ("2026-11-18T12:00:00Z\n", "sample_at"),
    ("２０２６-11-18T12:00:00Z", "sample_at"),
    ("2026-2-18T12:00:00Z", "sample_at"), ("2026-11-8T12:00:00Z", "sample_at"),
    ("2026-11-18T1:00:00Z", "sample_at"), ("2026-11-18T12:00:00+0530", "sample_at"),
    ("2026-11-18T12:00:00+24:00", "sample_at"), ("2026-11-18T12:00:00-08:60", "sample_at"),
    ("2026-11-18T24:00:00Z", "sample_at"), ("2026-11-18T12:60:00Z", "sample_at"),
    ("2026-11-18T12:00:60Z", "sample_at"), ("2026-11-18T12:00:00.Z", "sample_at"),
    ("2026-11-18T12:00:00.1234Z", "sample_at"),
    ("2026-02-29T12:00:00Z", "sample_at"), ("2026-04-31T12:00:00Z", "sample_at"),
    ("2026-13-01T12:00:00Z", "sample_at"), ("2026-11-00T12:00:00Z", "sample_at"),
])
def test_c2_timestamp_uses_reader_grammar_and_calendar(sample, problem):
    # Catch permissive ISO parsers and rejecting a valid browser timezone or year.
    assert entry_problem(_day(sample)) == problem


@pytest.mark.parametrize("ref, problem", [
    (_ref(), None), (_ref(bounds=[-180, -90, 180, 90]), None),
    (_ref(bounds=[-1.25, -0.5, 1.75, 0.5]), None),
    (_ref(bytes=1.0), None), (_ref(bytes=5_000_000), None),
    ([], "tile-ref"), ({}, "tile-ref"),
    ({k: v for k, v in _ref().items() if k != "path"}, "tile-ref"),
    ({k: v for k, v in _ref().items() if k != "sha256"}, "tile-ref"),
    ({k: v for k, v in _ref().items() if k != "bytes"}, "tile-ref"),
    (_ref(path=3), "tile-ref"),
    (_ref(path="habitat-tiles/sst-0000000000000000.json"), "tile-ref"),
    (_ref(path="habitat-history/../sst-0000000000000000.json"), "tile-ref"),
    (_ref(path="habitat-history/SST-0000000000000000.json"), "tile-ref"),
    (_ref(path="habitat-history/-0000000000000000.json"), "tile-ref"),
    (_ref(path="habitat-history/sst-000000000000000.json"), "tile-ref"),
    (_ref(path="habitat-history/sst-g000000000000000.json"), "tile-ref"),
    (_ref(path="habitat-history/sst-0000000000000000.json.bak"), "tile-ref"),
    (_ref(sha256=5), "tile-ref"), (_ref(sha256="a" * 63), "tile-ref"),
    (_ref(sha256="a" * 65), "tile-ref"), (_ref(sha256="A" * 64), "tile-ref"),
    (_ref(sha256="g" * 64), "tile-ref"),
    (_ref(bytes=True), "tile-ref"), (_ref(bytes=False), "tile-ref"),
    (_ref(bytes=1.5), "tile-ref"), (_ref(bytes="1"), "tile-ref"),
    (_ref(bytes=0), "tile-ref"), (_ref(bytes=5_000_001), "tile-ref"),
    (_ref(bytes=float("nan")), "tile-ref"), (_ref(bytes=float("inf")), "tile-ref"),
    (_ref(bounds=None), "tile-ref"), (_ref(bounds=(-1, -1, 1, 1)), "tile-ref"),
    (_ref(bounds=[-1, -1, 1]), "tile-ref"), (_ref(bounds=[-1, -1, 1, 1, 2]), "tile-ref"),
    (_ref(bounds=["-1", -1, 1, 1]), "tile-ref"), (_ref(bounds=[False, -1, 1, 1]), "tile-ref"),
    (_ref(bounds=[float("nan"), -1, 1, 1]), "tile-ref"),
    (_ref(bounds=[-1, -1, float("inf"), 1]), "tile-ref"),
    (_ref(bounds=[-1, -1, -1, 1]), "tile-ref"), (_ref(bounds=[1, -1, -1, 1]), "tile-ref"),
    (_ref(bounds=[-1, -1, 1, -1]), "tile-ref"), (_ref(bounds=[-1, 1, 1, -1]), "tile-ref"),
    (_ref(bounds=[-181, -1, 1, 1]), "tile-ref"), (_ref(bounds=[-1, -91, 1, 1]), "tile-ref"),
    (_ref(bounds=[-1, -1, 181, 1]), "tile-ref"), (_ref(bounds=[-1, -1, 1, 91]), "tile-ref"),
])
def test_c2_tile_reference_acceptance(ref, problem):
    # Catch URL/hash widening, Python bool/int confusion, and weakened box checks.
    assert entry_problem({"sample_at": _OLDER, "tiles": [ref]}) == problem


@pytest.mark.parametrize("previous", [[], None, {}, "not a list", (_day(),)])
def test_c3_no_candidates(previous):
    # Catch coercing a non-list previous value into candidate rows.
    assert next_history(previous, None, _CURRENT) == _EMPTY


def test_c3_discard_ignores_previous_and_outgoing():
    # Reset must not retain valid old data or report rejected rows from the old manifest.
    assert next_history([_day(), None], _day(index=1), _CURRENT, discard=True) == _EMPTY


@pytest.mark.parametrize("sample", [_CURRENT, "2026-11-20T00:00:00.001Z"])
def test_c3_outgoing_must_be_strictly_older(sample):
    # Catch accepting the current instant or truncating subsecond comparisons.
    assert next_history([], _day(sample), _CURRENT) == HistoryUpdate(
        [], frozenset(), [(-1, "not-older")],
    )


def test_c3_first_valid_candidate_wins_across_timezone_spellings():
    # Catch deduplication by spelling/date, previous overriding outgoing, or invalid rows claiming an instant.
    outgoing = _day()
    earlier = _day("2026-11-18T12:00:00.001+00:00", 4)
    previous = [_day("2026-11-18T12:00:00+00:00", 1), _day("2026-11-18T04:00:00-08:00", 2),
                _day("2026-11-18T17:30:00+05:30", 3), {**earlier, "tiles": []}, earlier,
                _day("2026-11-18T12:00:00.001Z", 5)]
    assert next_history(previous, outgoing, _CURRENT) == HistoryUpdate(
        [earlier, outgoing], frozenset({_ref()["path"], _ref(4)["path"]}),
        [(0, "duplicate-day"), (1, "duplicate-day"), (2, "duplicate-day"),
         (3, "tiles"), (5, "duplicate-day")],
    )


def test_c3_invalid_outgoing_and_invalid_history_are_reported():
    # Catch exceptions on malformed candidates or the wrong index/reason on projection.
    previous = [{}, {**_day(), "tiles": [None]}, {**_day(), "tiles": [_ref(), _ref()]}, _day(_CURRENT)]
    assert next_history(previous, False, _CURRENT) == HistoryUpdate(
        [], frozenset(), [(-1, "not-object"), (0, "sample_at"), (1, "tile-ref"),
                          (2, "duplicate-path"), (3, "not-older")],
    )


def test_c4_projects_a_shallow_copy_without_mutating_input():
    # Catch leaking extra entry keys, cloning the tile list, or trimming the input in place.
    day = _day()
    outgoing = {**day, "discard_me": True}
    result = next_history([], outgoing, _CURRENT)
    assert result == HistoryUpdate([day], frozenset({_ref()["path"]}), [])
    assert outgoing == {**day, "discard_me": True}
    assert result.history[0] is not outgoing
    assert result.history[0]["tiles"] is outgoing["tiles"]


@pytest.mark.parametrize("include_eighth", [False, True])
def test_c4_sort_before_trimming_and_keep_only_referenced_paths(include_eighth):
    # Catch dropping the eighth input instead of the oldest instant, or leaking its paths.
    rows = [_day(f"2026-11-{day:02d}T00:00:00Z", day) for day in range(10, 18)]
    rows[7]["tiles"].append(_ref(11))  # Shared across days, not a duplicate within a day.
    prior = [rows[i] for i in (3, 1, 2, 6, 4, 5)] + [None, rows[7]]
    if include_eighth:
        prior.insert(3, rows[0])
    result = next_history(prior, None, _CURRENT)
    assert result == HistoryUpdate(
        rows[:0:-1], frozenset(_ref(day)["path"] for day in range(11, 18)),
        [(3, "beyond-7"), (7, "not-object")] if include_eighth else [(6, "not-object")],
    )


@pytest.mark.parametrize("current", [None, 1, "2026-02-29T00:00:00Z", "2026-11-20T00:00Z",
                                     "2026-11-20T00:00:00+00:60", "2026-11-20T00:00:00.0000Z"])
@pytest.mark.parametrize("discard", [False, True])
def test_c5_invalid_current_raises_even_on_discard(current, discard):
    # Catch accepting invalid current times or bypassing validation on reset.
    with pytest.raises(ValueError) as exc:
        next_history([], None, current, discard=discard)
    assert (exc.type, str(exc.value)) == (ValueError, "current_sample_at")


@pytest.mark.parametrize("current", [_CURRENT, "2026-11-19T16:00:00-08:00", "2026-11-20T05:30:00+05:30"])
def test_c5_valid_current_offsets_resolve_to_same_cutoff(current):
    # Catch comparing against local wall-clock time instead of the offset-adjusted instant.
    just_before = _day("2026-11-19T23:59:59.999Z")
    assert next_history([_day(_CURRENT)], just_before, current) == HistoryUpdate(
        [just_before], frozenset({_ref()["path"]}), [(0, "not-older")],
    )
