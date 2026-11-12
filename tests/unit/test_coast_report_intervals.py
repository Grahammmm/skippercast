"""NWS interval ends must fit the four-digit UTC millisecond domain; invalid ones are refused, not overflowed (RF0421-9)."""

import copy
import json
from unittest import TestCase

from tests.unit import test_coast_report as base

from skippercast import http
from skippercast.pipeline import coast_report as cr
from skippercast.pipeline.goes_frames import MAX_MS, MIN_MS

START = "2026-10-08T18:00:00+00:00"
START_MS = cr._ms(START)
HUGE = ("P" + "9" * 310 + "D", "P999999999D")  # float infinity; finite but beyond the calendar
GRID_KEY = f"{cr.NWS}gridpoints/{base.GRIDS['central']}"


def routes_with(valid_times=None, wind_rows=None):
    """The synthetic routes with only the central grid's validTimes (and optionally wind rows) changed."""
    out = base.routes()
    grid = json.loads(out[GRID_KEY])
    if valid_times is not None:
        grid["properties"]["validTimes"] = valid_times
    if wind_rows is not None:
        grid["properties"]["windSpeed"]["values"] = wind_rows
    out[GRID_KEY] = base.body(grid)
    return out


def assemble(routes):
    return cr.assemble(http.FakeSession(routes), base.live(), base.NOW)


def by_id(items, ident):
    return next(item for item in items if item["id"] == ident)


class IntervalDomain(TestCase):
    def test_duration_float_infinity_refuses_at_parser(self):
        with self.assertRaises(ValueError):
            cr.interval(f"{START}/{HUGE[0]}")

    def test_finite_end_beyond_calendar_refuses_at_parser(self):
        with self.assertRaises(ValueError):
            cr.interval(f"{START}/{HUGE[1]}")
        with self.assertRaises(ValueError):
            cr.interval(f"{cr.iso(MAX_MS - 1000)}/PT1H")

    def test_canonical_domain_endpoints_and_ordering(self):
        self.assertEqual(cr.interval(f"{cr.iso(MAX_MS - 1000)}/PT0.5S"), (MAX_MS - 1000, MAX_MS - 500))
        self.assertEqual(cr.interval(f"{cr.iso(MAX_MS - 1000)}/{cr.iso(MAX_MS)}"), (MAX_MS - 1000, MAX_MS))
        self.assertEqual(cr.interval(f"{cr.iso(MIN_MS)}/{cr.iso(MIN_MS + 1000)}"), (MIN_MS, MIN_MS + 1000))
        self.assertEqual(cr.interval("2026-10-08T18:00:00Z/2026-10-08T19:00:00Z"), (1791482400000, 1791486000000))
        for bad in (f"{START}/PT0S", f"{START}/2026-10-08T17:00:00Z", f"{START}/{START}", f"{START}/junk", "junk", None):
            with self.assertRaises(ValueError, msg=str(bad)):
                cr.interval(bad)

    def test_ordinary_duration_forms_and_fractional_values_unchanged(self):
        cases = {"P1D": 86400, "P7DT13H": 7 * 86400 + 13 * 3600, "P1W": 7 * 86400, "PT2H": 7200, "PT30M": 1800,
                 "PT45S": 45, "PT1.5H": 5400}
        for text, seconds in cases.items():
            self.assertEqual(cr.interval(f"{START}/{text}"), (START_MS, START_MS + seconds * 1000), text)


class AssemblyContainment(TestCase):
    def test_optional_invalid_validtimes_does_not_abort_other_sources(self):
        baseline = assemble(routes_with())
        self.assertIn("validThrough", by_id(baseline["sources"], "nws-central"))
        for duration in HUGE:
            result = assemble(routes_with(f"{START}/{duration}"))
            central = by_id(result["sources"], "nws-central")
            self.assertEqual(central["outcome"], "ok")
            self.assertNotIn("validThrough", central)
            self.assertEqual(by_id(result["forecasts"], "central"), by_id(baseline["forecasts"], "central"))
            for ident in ("nws-north", "nws-south", "ndbc-46215", "ndbc-46028", "coops-tides", "nws-alerts"):
                self.assertEqual(by_id(result["sources"], ident), by_id(baseline["sources"], ident), ident)
            for key in ("observations", "tides", "tideEvents", "alerts", "catches"):
                self.assertEqual(result[key], baseline[key], key)

    def test_bad_field_interval_is_unavailable_not_weeklong_data(self):
        good = {"validTime": f"{START}/PT2H", "value": 18.52}  # 10 kn for 18:00-20:00, before the report's first hour
        later = {"validTime": "2026-10-08T22:00:00+00:00/PT1H", "value": 37.04}  # 20 kn for 22:00 only
        for duration in HUGE:
            bad = {"validTime": f"{START}/{duration}", "value": 92.6}  # 50 kn sentinel
            result = assemble(routes_with(wind_rows=[bad, good, later]))
            hours = by_id(result["forecasts"], "central")["hours"]
            winds = {h["at"]: h["windKnots"] for h in hours}
            self.assertEqual(winds["2026-10-08T22:00:00.000Z"], 20.0)
            self.assertNotIn(50.0, winds.values())
            self.assertEqual(sum(w is not None for w in winds.values()), 1)
            self.assertEqual(by_id(result["sources"], "nws-central")["outcome"], "ok")

    def test_all_rows_invalid_follows_existing_no_populated_hours_refusal(self):
        grid = json.loads(base.routes()[GRID_KEY])["properties"]
        for key in grid:
            if isinstance(grid[key], dict) and "values" in grid[key]:
                grid[key]["values"] = [{"validTime": f"{START}/{HUGE[0]}", "value": 1}]
        routes = base.routes()
        routes[GRID_KEY] = base.body({"properties": grid})
        central = by_id(assemble(routes)["sources"], "nws-central")
        self.assertEqual((central["outcome"], central["error"]), ("error", "No populated forecast hours"))

    def test_legacy_fixture_and_inputs_unchanged(self):
        feed = base.live()
        before = copy.deepcopy(feed)
        result = cr.assemble(http.FakeSession(base.routes()), feed, base.NOW)
        self.assertEqual(feed, before)
        self.assertTrue(result == json.loads(base.FIXTURE.read_text()), "assembled report differs from committed fixture")
