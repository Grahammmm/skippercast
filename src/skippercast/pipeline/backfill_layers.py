"""Plan and run look-back backfills for the observed layers."""

from collections.abc import Callable, Iterable, Mapping
from datetime import date
from typing import TypeVar

from skippercast.pipeline import noaa_chlorophyll, noaa_sst
from skippercast.pipeline.backfill_plan import BackfillResult, backfill_dates, run_backfill


_Client = TypeVar("_Client")
_Bounds = TypeVar("_Bounds")

LAYER_FETCHES = {
    "sst-analysis": noaa_sst.fetch_for_date,
    "chlorophyll-observation": noaa_chlorophyll.fetch_for_date,
}


def backfill_layers(
    client: _Client,
    bounds: _Bounds,
    today: date,
    days: int,
    have: Mapping[str, Iterable[date]],
    fetches: Mapping[str, Callable[[_Client, _Bounds, date], object]] = LAYER_FETCHES,
) -> dict[str, BackfillResult]:
    """Plan every layer before fetching, then run the plans in mapping order."""
    plans = {layer: backfill_dates(today, days, have.get(layer, ())) for layer in fetches}
    return {layer: run_backfill(fetches[layer], client, bounds, dates) for layer, dates in plans.items()}
