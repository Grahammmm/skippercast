"""C1–C3: attach history before the manifest is handed to a publisher."""

import pytest

from skippercast.pipeline.habitat_history_manifest import with_history


_JAN_02 = 1735776000
_JAN_03 = 1735862400
_PAST = "2025-01-01T00:00:00Z"
_CURRENT = "2025-01-02T00:00:00Z"


def _reject(message, layer, history):
    with pytest.raises(ValueError) as error:
        with_history(layer, history)
    assert type(error.value) is ValueError
    assert error.value.args == (message,)


def test_c1_attach_to_new_dict_without_filtering_entry_content():
    # Neither tile validation nor an in-place assignment belongs here.
    layer = {"kind": "observation", "frames": [{"time": _JAN_02}], "tiles": []}
    history = [{"sample_at": _PAST, "extra": {"preserve": True}}]
    result = with_history(layer, history)
    assert result == {
        "kind": "observation", "frames": [{"time": _JAN_02}], "tiles": [],
        "history": [{"sample_at": _PAST, "extra": {"preserve": True}}],
    }
    assert result is not layer
    assert layer == {"kind": "observation", "frames": [{"time": _JAN_02}], "tiles": []}
    assert history == [{"sample_at": _PAST, "extra": {"preserve": True}}]


def test_c1_replace_rather_than_merge_history():
    layer = {"frames": [{"time": _JAN_02}], "history": [{"old": True}]}
    result = with_history(layer, [{"sample_at": _PAST}])
    assert result == {"frames": [{"time": _JAN_02}], "history": [{"sample_at": _PAST}]}
    assert layer == {"frames": [{"time": _JAN_02}], "history": [{"old": True}]}


def test_c1_empty_removes_existing_history_without_validating_forecast():
    layer = {"kind": "forecast", "history": [{"old": True}]}
    result = with_history(layer, [])
    assert result == {"kind": "forecast"}
    assert layer == {"kind": "forecast", "history": [{"old": True}]}


def test_c1_empty_without_existing_history_still_returns_a_new_dict():
    layer = {"kind": "observation"}
    result = with_history(layer, [])
    assert result == {"kind": "observation"}
    assert result is not layer


def test_c2_forecast_refusal_precedes_layer_and_entry_checks():
    _reject("forecast", {"kind": "forecast"}, [{"sample_at": "bad"}])


@pytest.mark.parametrize("layer", [{}, {"frames": {}}], ids=["absent", "not-list"])
def test_c2_frames_list_is_required_even_with_valid_fallback(layer):
    _reject("layer", {**layer, "sample_at": _CURRENT}, [{"sample_at": _PAST}])


def test_c2_uses_newest_populated_frame_not_last_frame_or_sample_at():
    # History is newer than the last listed frame and fallback, but older than the maximum.
    layer = {"frames": [{"time": _JAN_03}, {"time": _JAN_02}], "sample_at": _PAST}
    history = [{"sample_at": _CURRENT}]
    assert with_history(layer, history) == {**layer, "history": history}


@pytest.mark.parametrize(
    "sample", ["2025-01-01T19:00:00-05:00", "2025-01-02T00:00:00.001Z"],
    ids=["equal-across-offset", "one-millisecond-newer"],
)
def test_c2_rejects_history_not_strictly_older(sample):
    # Check later entries too, and compare instants rather than date labels.
    _reject("current", {"frames": [{"time": _JAN_02}]}, [{"sample_at": _PAST}, {"sample_at": sample}])


@pytest.mark.parametrize(
    "count", [
        {"valid_cells": None}, {"valid_cells": "-1"}, {}, {"valid_cells": 5},
        {"valid_cells": False}, {"valid_cells": float("nan")}, {"valid_cells": float("-inf")},
    ],
    ids=["null", "negative-string", "absent", "positive", "bool", "nan", "non-finite"],
)
def test_c2_populated_frame_overrides_later_fallback(count):
    # Treating missing/unknown counts as zero (or ignoring positives) would allow equality.
    layer = {"frames": [{"time": _JAN_02, **count}], "sample_at": "2025-01-03T00:00:00Z"}
    _reject("current", layer, [{"sample_at": _CURRENT}])


@pytest.mark.parametrize("count", [0, -3], ids=["zero", "negative"])
def test_c2_unpopulated_frame_uses_strict_instant_fallback(count):
    # If the empty frame wins, history becomes newer than current instead of older.
    layer = {"frames": [{"time": _JAN_02, "valid_cells": count}], "sample_at": "2025-01-03T00:00:00Z"}
    history = [{"sample_at": _CURRENT}]
    assert with_history(layer, history) == {**layer, "history": history}


def test_c2_date_only_fallback_uses_utc_midnight():
    layer = {"frames": [], "sample_at": "2025-01-02"}
    history = [{"sample_at": "2025-01-01T18:59:59.999-05:00"}]
    assert with_history(layer, history) == {**layer, "history": history}
    _reject("current", layer, [{"sample_at": _CURRENT}])


@pytest.mark.parametrize(
    "fallback", [None, "2025-01-02T00:00Z", "2025-02-30"],
    ids=["missing-time", "out-of-grammar", "nonexistent-day"],
)
def test_c2_unusable_fallback_reports_layer_before_bad_history(fallback):
    _reject("layer", {"frames": [], "sample_at": fallback}, [{"sample_at": "bad"}])


@pytest.mark.parametrize("frame", [{}, {"valid_cells": 0, "time": "bad"}], ids=["missing", "non-numeric"])
def test_c2_unusable_frame_time_does_not_use_fallback(frame):
    _reject("layer", {"frames": [frame], "sample_at": _CURRENT}, [{"sample_at": _PAST}])


def test_c3_accepts_positive_offset_and_preserves_input_order_and_spelling():
    # Lexical ordering, UTC rewriting or a sorting pass would break this result.
    layer = {"frames": [{"time": _JAN_02}]}
    history = [{"sample_at": "2025-01-02T01:59:59.999+02:00"}, {"sample_at": _PAST}]
    assert with_history(layer, history) == {
        "frames": [{"time": _JAN_02}],
        "history": [{"sample_at": "2025-01-02T01:59:59.999+02:00"}, {"sample_at": _PAST}],
    }


def test_c3_accepts_iso_year_zero_leap_day():
    # Python's datetime cannot directly represent a valid year-zero reader date.
    layer = {"frames": [], "sample_at": "0000-03-01"}
    history = [{"sample_at": "0000-02-29T23:59:59.999Z"}]
    assert with_history(layer, history) == {**layer, "history": history}


@pytest.mark.parametrize(
    "entry", [
        {}, {"sample_at": 1735689600}, {"sample_at": "2025-01-01"},
        {"sample_at": "2025-01-01T00:00Z"}, {"sample_at": "2025-01-01T00:00:00"},
        {"sample_at": "2025-01-01T00:00:00.0000Z"}, {"sample_at": "2025-02-30T00:00:00Z"},
        {"sample_at": "2025-01-01T00:00:00+00:60"}, {"sample_at": "2025-01-01T24:00:00Z"},
    ],
    ids=["absent", "number", "date-only", "no-seconds", "no-zone", "four-fraction-digits",
         "nonexistent-day", "invalid-offset", "invalid-hour"],
)
def test_c3_rejects_invalid_samples_before_earlier_chronology_violation(entry):
    # Reject permissive date parsers, and don't raise 'current' on the first entry.
    _reject("sample_at", {"frames": [{"time": _JAN_02}]}, [{"sample_at": _CURRENT}, entry])
