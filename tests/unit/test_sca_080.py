"""Coast-report observation age and replacement, using only offline fixtures."""

from datetime import timedelta
import json

import pytest

from skippercast import http
from skippercast.pipeline import coast_report as cr
from tests.unit.test_coast_report import GRIDS, NOW, buoy, routes


def at(age):
    return (NOW - age).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def reading(age, **values):
    return {"time": at(age), **values}


def feed(*records):
    return {"schema_version": 1, "region_id": cr.REGION, "generated_at": at(timedelta()),
            "sources": {f"fixture-{i}": record for i, record in enumerate(records)}}


@pytest.mark.parametrize(("age", "upstream", "current"), [
    (timedelta(days=-2), "ok", False),
    (timedelta(milliseconds=-1), "ok", False),
    (timedelta(), "ok", True),
    (timedelta(hours=1), "ok", True),
    (timedelta(hours=3), "ok", True),
    (timedelta(hours=3, milliseconds=1), "ok", False),
    (timedelta(days=2), "ok", False),
    (timedelta(hours=1), "stale", False),
])
def test_normalization_accepts_only_current_samples(age, upstream, current):
    doc = feed(buoy("46215", [reading(age, WVHT=1.3)], status=upstream))
    report = cr.assemble(http.FakeSession({}), doc, NOW)
    sources = {s["id"]: s for s in report["sources"]}
    assert sources["ndbc-46215"]["outcome"] == ("ok" if current else "error")
    assert [r["observedAt"] for r in report["observations"]] == ([at(age)] if current else [])


@pytest.mark.parametrize(("observed_at", "allowed"), [
    (at(timedelta(days=-2)), False),
    (at(timedelta(milliseconds=-1)), False),
    (at(timedelta()), True),
    (at(timedelta(hours=3)), True),
    (at(timedelta(hours=3, milliseconds=1)), False),
    ("invalid", False),
])
def test_publishability_rechecks_observation_age(observed_at, allowed):
    report = {"generatedAt": at(timedelta()), "forecasts": [{"hours": []}],
              "observations": [{"stationId": "46215", "observedAt": observed_at, "waveFt": 4.0}]}
    assert cr.publishable(report) is allowed


def test_current_wind_survives_ineligible_waves_at_the_same_station():
    doc = feed(buoy("46215", [reading(timedelta(days=-2), WVHT=9),
                             reading(timedelta(hours=1), WSPD=5),
                             reading(timedelta(days=2), WVHT=8)]))
    report = cr.assemble(http.FakeSession({}), doc, NOW)
    [row] = report["observations"]
    assert row["observedAt"] == at(timedelta(hours=1))
    assert row["waveFt"] is None and row["windKnots"] > 0
    assert cr.publishable(report)


@pytest.mark.parametrize("valid_source", [None, "buoy", "forecast"])
def test_report_replacement_keeps_independent_current_sources(tmp_path, valid_source):
    folder = tmp_path / "regions" / cr.REGION
    folder.mkdir(parents=True)
    destination = folder / "coast-report.json"
    previous = b'{"previous":"useful edition"}\n'
    destination.write_bytes(previous)
    future = buoy("46215", [reading(timedelta(days=-2), WVHT=1.3)])
    second = buoy("46028", [reading(timedelta(hours=1), WVHT=1.2)],
                  status="ok" if valid_source == "buoy" else "stale")
    (folder / "latest.json").write_text(json.dumps(feed(future, second)))
    forecast_routes = {url: body for url, body in routes().items()
                       if url.startswith(cr.NWS + "points/") or url == f"{cr.NWS}gridpoints/{GRIDS['north']}"}
    session = http.FakeSession(forecast_routes if valid_source == "forecast" else {})

    assert cr.main(["--root", str(tmp_path)], session=session, now=NOW) == (0 if valid_source else 1)
    if valid_source is None:
        assert destination.read_bytes() == previous
    else:
        report = json.loads(destination.read_bytes())
        assert [r["stationId"] for r in report["observations"]] == (["46028"] if valid_source == "buoy" else [])
        assert sum(bool(f["hours"]) for f in report["forecasts"]) == (1 if valid_source == "forecast" else 0)
