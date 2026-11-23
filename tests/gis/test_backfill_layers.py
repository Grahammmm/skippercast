"""Offline acceptance tests for coordinating observed-layer backfills."""

from datetime import date, datetime
from inspect import signature

import pytest

from skippercast.pipeline import noaa_chlorophyll, noaa_sst
from skippercast.pipeline.backfill_layers import LAYER_FETCHES, backfill_layers
from skippercast.pipeline.backfill_plan import BackfillResult


SST = "sst-analysis"
CHLOROPHYLL = "chlorophyll-observation"
TODAY = date(2026, 1, 8)
WEEK = tuple(date(2026, 1, day) for day in range(1, 8))


def test_c1_default_fetches_are_the_dated_readers_in_order():
    # A swap, a latest-only reader, or a different default would fetch the wrong data.
    assert list(LAYER_FETCHES.items()) == [
        (SST, noaa_sst.fetch_for_date),
        (CHLOROPHYLL, noaa_chlorophyll.fetch_for_date),
    ]
    assert signature(backfill_layers).parameters["fetches"].default is LAYER_FETCHES


def test_c2_seven_day_plans_use_each_layers_own_history_and_fetch_order():
    # Reversing the defaults catches fixed execution order; different held dates catch shared history.
    client, bounds = object(), object()
    calls = []

    def fetch(layer, payload):
        def read(actual_client, actual_bounds, day):
            calls.append((layer, actual_client, actual_bounds, day))
            return payload

        return read

    result = backfill_layers(
        client, bounds, TODAY, 7,
        {SST: iter(WEEK[:1]), CHLOROPHYLL: WEEK[-1:]},
        {CHLOROPHYLL: fetch(CHLOROPHYLL, "chlorophyll"), SST: fetch(SST, "temperature")},
    )

    assert list(result.items()) == [
        (CHLOROPHYLL, BackfillResult([(day, "chlorophyll") for day in WEEK[:-1]], [])),
        (SST, BackfillResult([(day, "temperature") for day in WEEK[1:]], [])),
    ]
    assert calls == [
        *((CHLOROPHYLL, client, bounds, day) for day in WEEK[:-1]),
        *((SST, client, bounds, day) for day in WEEK[1:]),
    ]


def test_c2_keep_empty_plan_but_do_not_add_unrequested_layers():
    # A fully held layer must still appear; a default layer not requested must not.
    def unexpected_fetch(client, bounds, day):
        pytest.fail("fully held layer was fetched")

    assert backfill_layers(None, None, TODAY, 7, {SST: WEEK}, {SST: unexpected_fetch}) == {
        SST: BackfillResult([], []),
    }


def test_c3_fetch_value_error_marks_only_its_layer_absent():
    # A missing observation must not abort or mark the other layer absent for that date.
    def missing(client, bounds, day):
        raise ValueError("no SST for this date")

    def available(client, bounds, day):
        return "chlorophyll"

    day = WEEK[-1]
    assert backfill_layers(None, None, TODAY, 1, {}, {SST: missing, CHLOROPHYLL: available}) == {
        SST: BackfillResult([], [(day, "no SST for this date")]),
        CHLOROPHYLL: BackfillResult([(day, "chlorophyll")], []),
    }


@pytest.mark.parametrize(("today", "days", "error", "message"), [
    (TODAY, 0, ValueError, "days must be an integer from 1 to 7, got 0"),
    (TODAY, 8, ValueError, "days must be an integer from 1 to 7, got 8"),
    (datetime(2026, 1, 8), 1, TypeError, "today must be a date, not a datetime"),
])
def test_c3_invalid_plan_raises_before_fetch(today, days, error, message):
    # Do not coerce bad inputs or misclassify planner errors as missing observations.
    def unexpected_fetch(client, bounds, day):
        pytest.fail("invalid plan called a fetch")

    with pytest.raises(error) as caught:
        backfill_layers(None, None, today, days, {}, {SST: unexpected_fetch})
    assert caught.type is error
    assert str(caught.value) == message


def test_c3_later_planner_error_prevents_earlier_layer_fetch():
    # A lazy second-layer history can fail during planning; no layer may have started.
    failure = ValueError("saved history unavailable")

    def broken_history():
        yield WEEK[-1]
        raise failure

    def unexpected_fetch(client, bounds, day):
        pytest.fail("fetch began before all plans were valid")

    with pytest.raises(ValueError) as caught:
        backfill_layers(None, None, TODAY, 1, {CHLOROPHYLL: broken_history()},
                        {SST: unexpected_fetch, CHLOROPHYLL: unexpected_fetch})
    assert caught.type is ValueError
    assert str(caught.value) == "saved history unavailable"
    assert caught.value is failure


def test_c3_other_fetch_error_propagates_and_stops():
    # A fatal fetch failure must neither become an absent day nor start the next layer.
    failure = RuntimeError("fixture transport failed")

    def fail(client, bounds, day):
        raise failure

    def unexpected_fetch(client, bounds, day):
        pytest.fail("next layer ran after a fatal fetch error")

    with pytest.raises(RuntimeError) as caught:
        backfill_layers(None, None, TODAY, 1, {}, {SST: fail, CHLOROPHYLL: unexpected_fetch})
    assert caught.type is RuntimeError
    assert str(caught.value) == "fixture transport failed"
    assert caught.value is failure
