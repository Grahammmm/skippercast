"""A partial annual refresh must not replace a two-year seasonal baseline."""

from datetime import datetime, timezone
import json

import pytest

from skippercast.http import FakeSession
from skippercast.pipeline import ndbc_history as nh

STATION = "00001"
NOW = datetime(2025, 1, 2, 12, tzinfo=timezone.utc)


def met(year, day, water_temp):
    return f"YYYY MM DD hh mm WVHT WTMP\n{year} 01 {day} 11 00 1.5 {water_temp}\n".encode()


def annual_successes(station):
    return [s for s in station["sources"] if s["role"] == "annual" and s["outcome"] == "ok"]


@pytest.mark.parametrize("failed_body", [None, b"not standard-met rows"], ids=["missing", "unparseable"])
def test_partial_full_refresh_retains_baseline_until_all_prior_years_are_usable(tmp_path, monkeypatch, failed_body):
    monkeypatch.setitem(nh.STATIONS, "fixture", ("fixture", ((STATION, "Synthetic buoy", 0, 0),)))
    index, recent = nh.index_url(STATION), nh.recent_url(STATION)
    older, newer = (nh.annual_url(STATION, year) for year in (2022, 2023))
    original = {index: b"/00001h2022.txt.gz /00001h2023.txt.gz",
                recent: met(2025, 1, 12), older: met(2022, 1, 10), newer: met(2023, 1, 20)}

    def collect(mode, routes, previous=None):
        bundle = nh.collect("fixture", mode, FakeSession(routes), tmp_path,
                            previous=previous, now=NOW, revalidate=True)
        # Exercise the preceding run's JSON artifact, as the scheduled refresh does.
        return json.loads(json.dumps(bundle))

    prior = collect("full", original)
    old = prior["stations"][0]
    assert old["baseline"]["years"] == [2022, 2023]
    assert [s["year"] for s in annual_successes(old)] == [2022, 2023]

    routes = {**original, newer: met(2023, 1, 30), recent: met(2025, 2, 14)}
    if failed_body is None:
        del routes[older]
    else:
        routes[older] = failed_body
    partial = collect("full", routes, prior)
    retained = partial["stations"][0]
    assert retained["archive"]["availableYears"] == [2022, 2023]
    assert retained["baseline"] == old["baseline"]  # includes all quantiles and coverage denominators
    assert annual_successes(retained) == annual_successes(old)
    failures = [s for s in retained["sources"] if s["role"] == "annual" and s["outcome"] == "error"]
    assert [(s["year"], s["url"]) for s in failures] == [(2022, older)]
    assert failures[0]["error"]
    assert retained["recent"]["lastObservedAt"] == "2025-01-02T11:00:00.000Z"

    weekly = collect("recent", {recent: routes[recent]}, partial)["stations"][0]
    assert weekly["baseline"] == old["baseline"]
    assert annual_successes(weekly) == annual_successes(old)

    recovered = collect("full", {**routes, older: original[older]}, partial)["stations"][0]
    assert recovered["baseline"]["years"] == [2022, 2023]
    jan_water = next(m for m in recovered["baseline"]["months"] if m["month"] == 1 and m["metric"] == "waterTempF")
    assert (jan_water["p10"], jan_water["median"], jan_water["p90"]) == (53.6, 68, 82.4)
    assert [s["year"] for s in annual_successes(recovered)] == [2022, 2023]
    assert annual_successes(recovered)[1]["sha256"] != annual_successes(old)[1]["sha256"]
    assert not any(s["outcome"] == "error" for s in recovered["sources"])
