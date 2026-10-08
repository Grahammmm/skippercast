"""FE-87: the coast report base from SkipperCast collectors (synthetic NWS, CO-OPS, live and daily feeds; offline).

`tests/fixtures/coast/skippercast-report.json` is `assemble(FakeSession(routes()), live(), NOW)` written as
compact JSON; `tests/test_coast_data.mjs` runs it through `packages/coast` readiness and the Worker switch.
"""

import copy
from datetime import datetime, timezone
import json
import math
import re
import tempfile
from pathlib import Path
from unittest import TestCase

from skippercast import http
from skippercast.pipeline import coast_report as cr
from tests._support import ROOT

NOW = datetime(2026, 10, 8, 21, 0, tzinfo=timezone.utc)
FIXTURE = ROOT / "tests/fixtures/coast/skippercast-report.json"
GRIDS = {"north": "LOX/10,30", "central": "LOX/20,20", "south": "LOX/30,10"}
LAND_ZONES = {"north": "CAZ340", "central": "CAZ087", "south": "CAZ087"}


def body(value):
    return json.dumps(value).encode()


def field(uom, first, second):
    """Two intervals covering 2026-10-08T18:00Z to 2026-10-10T21:00Z, plus one malformed row that stays unavailable."""
    return {"uom": uom, "values": [{"validTime": "2026-10-08T18:00:00+00:00/PT27H", "value": first},
                                   {"validTime": "2026-10-09T21:00:00+00:00/P1D", "value": second},
                                   {"validTime": "not-a-time/PT1H", "value": 99}]}


def grid():
    return {"properties": {"updateTime": "2026-10-08T18:26:38+00:00", "validTimes": "2026-10-08T12:00:00+00:00/P7DT13H",
                           "windSpeed": field("wmoUnit:km_h-1", 14.8, 22.2), "windGust": field("wmoUnit:km_h-1", 24.1, 31.5),
                           "waveHeight": field("wmoUnit:m", 1.22, 1.83), "wavePeriod": field("wmoUnit:s", 11, 9),
                           "primarySwellHeight": field("wmoUnit:m", 1.1, 1.5), "primarySwellPeriod": field("wmoUnit:s", 12, 10),
                           "windWaveHeight": field("wmoUnit:m", 0.3, 0.6), "windDirection": field("wmoUnit:degree_(angle)", 315, 320),
                           "temperature": field("wmoUnit:degC", 16.1, 15.0), "probabilityOfPrecipitation": field("wmoUnit:percent", 0, 10),
                           "skyCover": field("wmoUnit:percent", 20, 140), "relativeHumidity": field("wmoUnit:percent", 70, 75)}}


def tide_rows(events):
    if events:
        times = [f"2026-10-{d:02d} {h:02d}:{m:02d}" for d in range(7, 11) for h, m in ((3, 30), (9, 56), (16, 12), (22, 40))]
        return [{"t": t, "v": f"{1.6 if i % 2 == 0 else 0.1:.3f}", "type": "H" if i % 2 == 0 else "L"} for i, t in enumerate(times)]
    return [{"t": f"2026-10-{7 + h // 24:02d} {h % 24:02d}:00", "v": f"{0.9 + 0.7 * math.sin(h / 2):.3f}"} for h in range(97)]


def alerts():
    point = lambda zones=(), ugc=(), geometry=None, **p: {"id": p["id"], "geometry": geometry, "properties": {
        "@id": p["id"], "event": p["event"], "headline": p.get("headline"), "description": "Synthetic alert text.",
        "effective": "2026-10-08T14:00:00-07:00", "expires": "2026-10-09T03:00:00-07:00",
        "affectedZones": [f"https://api.weather.gov/zones/forecast/{z}" for z in zones], "geocode": {"UGC": list(ugc)}}}
    south = {"type": "Polygon", "coordinates": [[[-120.9, 35.1], [-120.6, 35.1], [-120.6, 35.25], [-120.9, 35.25], [-120.9, 35.1]]]}
    return {"type": "FeatureCollection", "features": [
        point(id="https://api.weather.gov/alerts/urn:fixture:1", event="Small Craft Advisory", headline="Fixture marine advisory", zones=["PZZ645"]),
        point(id="https://api.weather.gov/alerts/urn:fixture:2", event="Beach Hazards Statement", ugc=["CAZ340"]),
        point(id="https://api.weather.gov/alerts/urn:fixture:3", event="Dense Fog Advisory", geometry=south),
        point(id="https://api.weather.gov/alerts/urn:fixture:4", event="Gale Warning", zones=["PZZ999"])]}


def routes():
    out = {}
    for ident, name, lat, lon, land_lat, land_lon, zone in cr.AREAS:
        out[f"{cr.NWS}points/{lat},{lon}"] = body({"properties": {"forecastGridData": f"{cr.NWS}gridpoints/{GRIDS[ident]}",
                                                                  "forecastZone": f"{cr.NWS}zones/forecast/{zone}"}})
        out[f"{cr.NWS}points/{land_lat},{land_lon}"] = body({"properties": {"forecastZone": f"{cr.NWS}zones/forecast/{LAND_ZONES[ident]}",
                                                                            "county": f"{cr.NWS}zones/county/CAC079"}})
        out[f"{cr.NWS}gridpoints/{GRIDS[ident]}"] = body(grid())
    out[cr.tide_url(NOW, "6")] = body({"predictions": tide_rows(False)})
    out[cr.tide_url(NOW, "hilo")] = body({"predictions": tide_rows(True)})
    out[cr.ALERTS_URL] = body(alerts())
    out[cr.DAILY_URL] = body(daily())
    return out


def buoy(station, rows, status="ok"):
    units = {"WDIR": "degT", "WSPD": "m/s", "GST": "m/s", "WVHT": "m", "DPD": "sec", "MWD": "degT", "WTMP": "degC"}
    return {"url": f"https://www.ndbc.noaa.gov/data/realtime2/{station}.txt", "status": status, "checked_at": "2026-10-08T20:37:07Z",
            "data_retrieved_at": "2026-10-08T20:37:08Z", "issue": None if status == "ok" else "HTTPStatusError: HTTP 503",
            "data": {"station": station, "sample_at": rows[0]["time"], "units": units, "observations": rows}}


def live():
    row = lambda time, **v: {"time": time, "WVHT": None, "DPD": None, "WTMP": None, "WSPD": None, "GST": None, "MWD": None, **v}
    return {"schema_version": 1, "region_id": "morro-bay", "generated_at": "2026-10-08T20:37:07Z", "sources": {
        "diablo": buoy("46215", [row("2026-10-08T20:26:00Z", WVHT=1.3, DPD=11.0, WTMP=14.2, MWD=280.0),
                                 row("2026-10-08T19:56:00Z", WVHT=1.2, DPD=12.0, WTMP=14.1)]),
        "diablo-spectrum": {**buoy("46215", [row("2026-10-08T20:26:00Z", WVHT=1.3)]), "url": "https://www.ndbc.noaa.gov/data/realtime2/46215.spec"},
        "offshore": buoy("46028", [row("2026-10-08T20:30:00Z", WSPD=6.0, GST=8.0, WTMP=15.0),  # newer wind-only row is not mixed in
                                   row("2026-10-08T20:20:00Z", WVHT=2.0, DPD=10.0, WTMP=15.1, WSPD=5.0, GST=7.0, MWD=300.0)])}}


TRIP = {"id": "0123456789abcdef", "date": "2026-10-06", "boat": "Fixture Vessel", "port": "Morro Bay", "trip_type": "1/2 Day AM",
        "anglers": 12, "ground": None, "catches": [{"species": "rockfish", "label": "Vermilion Rockfish", "count": 40, "disposition": "reported"},
                                                   {"species": "lingcod", "label": "Lingcod", "count": 2, "disposition": "released"}],
        "source_url": "https://www.socalfishreports.com/dock_totals/boats.php?date=2026-10-06", "coordinates": None}


def daily(trips=(TRIP,)):
    day = lambda date, reports: {"id": f"catches-{date}", "status": "ok", "kind": "charter-reports", "checked_at": "2026-10-08T11:18:00Z",
                                 "url": f"https://www.socalfishreports.com/dock_totals/boats.php?date={date}", "data": {"date": date, "reports": reports}}
    sst = {"time": "2026-10-07T12:00:00Z", "mask": 1}
    return {"schema_version": 1, "region_id": "morro-bay", "generated_at": "2026-10-08T11:20:00Z",
            "report_window": {"start": "2026-09-08", "end": "2026-10-07", "days": 30}, "reports": list(trips), "sources": {
                "catches-2026-10-06": day("2026-10-06", [TRIP]), "catches-2026-10-07": day("2026-10-07", []),
                "sst": {"status": "ok", "url": "https://coastwatch.noaa.gov/cwn/products/fixture.html", "checked_at": "2026-10-08T11:18:00Z",
                        "data_retrieved_at": "2026-10-08T11:18:40Z", "data": {
                            "kind": "sst", "sample_at": "2026-10-07T12:00:00Z", "native_resolution_degrees": [0.05, 0.05],
                            "units": {"analysed_sst": "degree_C", "analysis_error": "degree_C", "mask": "flag"},
                            "query_url": "https://coastwatch.noaa.gov/thredds/ncss/grid/fixture.nc?var=analysed_sst",
                            "samples": [{**sst, "latitude": 35.3, "longitude": -121.0, "analysed_sst": 15.5, "analysis_error": 0.3},
                                        {**sst, "latitude": 35.3, "longitude": -120.95, "analysed_sst": 15.9, "analysis_error": 0.2},
                                        {**sst, "latitude": 35.35, "longitude": -120.85, "mask": 2, "analysed_sst": None, "analysis_error": None}]}},
                "mpa-boundaries": {"status": "ok", "url": "https://services2.arcgis.com/fixture/FeatureServer/0/query?f=geojson",
                                   "checked_at": "2026-10-08T11:18:00Z", "data_retrieved_at": "2026-10-08T11:18:41Z", "data": {"geojson": {
                                       "type": "FeatureCollection", "crs": {}, "features": [{"type": "Feature", "properties": {"NAME": "Fixture SMR"},
                                           "geometry": {"type": "Polygon", "coordinates": [[[-121, 35.4], [-120.98, 35.4], [-120.98, 35.42], [-121, 35.4]]]}}]}}}}}


def report(session=None, feed=None):
    return cr.assemble(session or http.FakeSession(routes()), live() if feed is None else feed, NOW)


# --- `Report` from packages/coast/src/types.ts, read structurally ---------------------------------------------------

def _split(text, sep):
    parts, depth, cur = [], 0, ""
    for ch in text:
        depth += ch in "{[(<"
        depth -= ch in "}])>"
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    return [p.strip() for p in parts + [cur] if p.strip()]


def _fields(literal):
    out = {}
    for part in _split(literal.strip()[1:-1], ";"):
        key, _, kind = part.partition(":")
        out[key.strip().rstrip("?")] = (key.strip().endswith("?"), kind.strip())
    return out


def types():
    found = {}
    for path in ("packages/coast/src/types.ts", "packages/coast/src/spatial-types.ts"):
        for name, text in re.findall(r"^export type (\w+) ?= ?(.*);\s*$", (ROOT / path).read_text(), re.M):
            parts = _split(text, "&")
            found[name] = {k: v for p in parts for k, v in (_fields(p) if p.startswith("{") else found[p]).items()} \
                if all(p.startswith("{") or p in found for p in parts) and "{" in text else text
    return found


def conforms(value, kind, known):
    for option in _split(kind, "|"):
        if option.endswith("[]"):
            ok = isinstance(value, list) and all(conforms(v, option[:-2], known) for v in value)
        elif option.startswith("{") or isinstance(known.get(option), dict):
            fields = _fields(option) if option.startswith("{") else known[option]
            ok = isinstance(value, dict) and not set(value) - set(fields) and all(
                (k in value or optional) and (k not in value or conforms(value[k], t, known)) for k, (optional, t) in fields.items())
        elif option in known:
            ok = conforms(value, known[option], known)
        elif option.startswith("["):
            ok = isinstance(value, list) and len(value) == len(_split(option[1:-1], ",")) and all(map(cr._number, value))
        else:
            simple = {"string": isinstance(value, str), "number": cr._number(value), "null": value is None, "any": True,
                      "boolean": isinstance(value, bool)}
            ok = simple[option] if option in simple else value == (option[1:-1] if option[0] == "'" else json.loads(option))
        if ok:
            return True
    return False


class ReportShape(TestCase):
    def test_the_fixture_is_the_assembled_report_and_validates_against_report(self):
        built, known = report(), types()
        self.assertEqual(built, json.loads(FIXTURE.read_text()), "rebuild tests/fixtures/coast/skippercast-report.json from report()")
        self.assertTrue(conforms(built, "Report", known))
        for bad in ({**built, "extra": 1}, {**built, "sources": [{**built["sources"][0], "outcome": "partial"}]},
                    {**built, "forecasts": [{**built["forecasts"][0], "validThrough": "2026-10-16T01:00:00.000Z"}]}):
            self.assertFalse(conforms(bad, "Report", known))  # the check itself rejects shapes Report does not allow

    def test_areas_buoys_and_tide_station_are_the_packages_county(self):
        county = (ROOT / "packages/coast/src/counties.ts").read_text()
        areas = re.findall(r"\{id:'(\w+)',name:'([^']+)'.*?,lat:([-\d.]+),lon:([-\d.]+),landLat:([-\d.]+),landLon:([-\d.]+).*?forecastZone:'(\w+)'", county)
        self.assertEqual([(a, n, *map(float, c), z) for a, n, *c, z in areas], [tuple(a) for a in cr.AREAS])
        self.assertEqual(re.findall(r"\{id:'(\d{5})',name:'([^']+)'", county), list(cr.BUOYS))
        self.assertIn(f"tideStation:{{id:'{cr.TIDE_STATION}',name:'{cr.TIDE_NAME}'", county)


class Sources(TestCase):
    def test_each_source_keeps_its_own_clocks_and_outcome(self):
        built = report()
        status = {s["id"]: s for s in built["sources"]}
        self.assertEqual(list(status), ["nws-north", "nws-central", "nws-south", "ndbc-46215", "ndbc-46028", "coops-tides",
                                        "coops-tide-events", "nws-alerts", "noaa-blended-sst", "cdfw-protected-areas", "landing-reports"])
        self.assertTrue(all(s["outcome"] == "ok" for s in built["sources"]))
        self.assertEqual((status["nws-central"]["issuedAt"], status["nws-central"]["validThrough"], status["nws-central"]["url"]),
                         ("2026-10-08T18:26:38.000Z", "2026-10-16T01:00:00.000Z", f"{cr.NWS}gridpoints/LOX/20,20"))
        self.assertEqual(status["ndbc-46215"]["fetchedAt"], "2026-10-08T20:37:08.000Z")  # the live collector's retrieval
        self.assertEqual((status["noaa-blended-sst"]["fetchedAt"], built["spatial"]["surfaceTemperature"]["analysedAt"]),
                         ("2026-10-08T11:18:40.000Z", "2026-10-07T12:00:00.000Z"))
        self.assertEqual(built["catches"][0]["retrievedAt"], "2026-10-08T11:18:00Z")  # the day receipt's own clock
        self.assertEqual(built["catchContext"]["feedGeneratedAt"], "2026-10-08T11:20:00Z")
        self.assertEqual(status["coops-tides"]["validThrough"], built["tides"][-1]["at"])

    def test_forecast_hours_convert_units_from_this_hour_and_keep_gaps(self):
        hours = report()["forecasts"][1]["hours"]
        self.assertEqual((hours[0]["at"], hours[-1]["at"], len(hours)), ("2026-10-08T21:00:00.000Z", "2026-10-10T20:00:00.000Z", 48))
        first = hours[0]
        self.assertAlmostEqual(first["windKnots"], 14.8 / 1.852)
        self.assertAlmostEqual(first["waveFt"], 1.22 * cr.FT)
        self.assertAlmostEqual(first["airTempF"], 16.1 * 1.8 + 32)
        self.assertIsNone(hours[-1]["cloudCoverPct"])  # 140 % is not a percentage; never clamped

    def test_buoys_take_one_row_per_station(self):
        diablo, offshore = report()["observations"]
        self.assertEqual((diablo["observedAt"], diablo["windKnots"], diablo["directionDeg"]), ("2026-10-08T20:26:00.000Z", None, 280.0))
        self.assertEqual((offshore["observedAt"], offshore["waveFt"] / cr.FT, offshore["windKnots"] / cr.KT), ("2026-10-08T20:20:00.000Z", 2.0, 5.0))
        feed = live()
        feed["sources"]["offshore"] = {**buoy("46028", feed["sources"]["offshore"]["data"]["observations"], "retained")}
        rows, statuses = cr.buoys(feed, "fallback")
        self.assertEqual([r["stationId"] for r in rows], ["46215"])
        self.assertEqual({k: statuses[1][k] for k in ("outcome", "fetchedAt", "error")},
                         {"outcome": "error", "fetchedAt": "2026-10-08T20:37:07.000Z", "error": "HTTPStatusError: HTTP 503"})
        self.assertEqual([s["outcome"] for s in cr.buoys(None, "2026-10-08T21:00:00.000Z")[1]], ["error", "error"])

    def test_alerts_reach_areas_by_marine_zone_shore_zone_or_polygon(self):
        found = {a["event"]: a["areaIds"] for a in report()["alerts"]}
        self.assertEqual(found, {"Small Craft Advisory": ["north", "central", "south"], "Beach Hazards Statement": ["north"],
                                 "Dense Fog Advisory": ["south"]})
        paged = {**alerts(), "pagination": {"next": "https://api.weather.gov/alerts?cursor=2"}}
        with self.assertRaisesRegex(ValueError, "pagination"):
            cr.alerts(paged, {})

    def test_a_failed_source_is_an_error_with_no_rows_and_the_rest_stand(self):
        bad = routes()
        bad[f"{cr.NWS}points/35.35,-120.95"] = http.HTTPStatusError("HTTP 500", 500)
        bad[cr.tide_url(NOW, "hilo")] = body({"predictions": [{"t": "2026-10-08 03:30", "v": "1.2", "type": "X"}]})
        bad[cr.ALERTS_URL] = (503, b"unavailable")
        bad[cr.DAILY_URL] = http.TransportError("connection reset")
        built = report(http.FakeSession(bad))
        status = {s["id"]: s for s in built["sources"]}
        self.assertEqual([f["hours"] != [] for f in built["forecasts"]], [True, False, True])
        self.assertEqual((status["nws-central"]["outcome"], status["nws-central"]["error"]), ("error", "HTTP 500"))
        self.assertEqual((built["tideEvents"], status["coops-tide-events"]["error"]), ([], "Invalid tide value/time"))
        self.assertEqual(len(built["tides"]), 97)
        self.assertEqual((built["alerts"], status["nws-alerts"]["outcome"]), ([], "error"))
        self.assertEqual((built["catches"], built["spatial"], "catchContext" in built), ([], {}, False))
        for ident in ("landing-reports", "noaa-blended-sst", "cdfw-protected-areas"):
            self.assertEqual((status[ident]["outcome"], status[ident]["error"]), ("error", "connection reset"))
        self.assertEqual(built["catchStatus"], "Dated local catch facts unavailable for this edition. Published reports remain linked.")


class Catches(TestCase):
    def test_trips_are_checked_against_their_day_receipt_and_window(self):
        now = cr._ms("2026-10-08T21:00:00Z")
        changed = {**TRIP, "id": "fedcba9876543210"}  # not in its day receipt
        foreign = {**TRIP, "id": "aaaaaaaaaaaaaaaa", "port": "Santa Barbara"}
        with self.assertRaisesRegex(ValueError, "identity"):
            cr._normalized({**TRIP, "id": 1234567890123456}, "2026-10-08T11:18:00Z")  # a numeric id is not a trip id
        trips, status, text, context = cr.catches(daily([TRIP, TRIP, changed, foreign]), now, "2026-10-08T21:00:00.000Z")
        self.assertEqual([t["id"] for t in trips], [TRIP["id"]])
        self.assertEqual(trips[0]["species"][1], {"name": "Lingcod", "count": 2, "disposition": "released", "released": True})
        self.assertEqual(status["outcome"], "error")
        self.assertIn("2 records unavailable. 1 exact duplicates ignored.", text)
        self.assertEqual((context["latestTripDate"], context["rights"]["scope"]), ("2026-10-06", "linked-factual-counts"))
        other = {**TRIP, "date": "2026-10-07", "source_url": "https://www.socalfishreports.com/dock_totals/boats.php?date=2026-10-07"}
        feed = daily([TRIP, other])
        feed["sources"]["catches-2026-10-07"]["data"]["reports"] = [other]
        self.assertEqual(cr.catches(feed, now, "x")[:3:2], ([], "No verified dated local trip facts in this feed edition; "
                                                           "2 records unavailable. Missing reports do not establish zero fishing or catches."))
        old = cr.catches(daily(), cr._ms("2026-10-11T12:00:00Z"), "x")  # the feed is over 72 hours old
        self.assertEqual((old[0], old[1]["error"], old[3]), ([], "Catch source clock is future dated or older than 72 hours", None))
        for change in ({"region_id": "monterey-point-sur"}, {"report_window": {"start": "2026-09-08", "end": "2026-10-08", "days": 31}}):
            self.assertEqual(cr.catches({**daily(), **change}, now, "x")[0], [])

    def test_no_prose_photos_or_positions_are_carried(self):
        trip = report()["catches"][0]
        self.assertEqual(set(trip), {"id", "tripDate", "boat", "landing", "anglers", "tripType", "species", "sourceUrl", "retrievedAt"})
        self.assertNotIn("coordinates", json.dumps(report()["catches"]))


class Publication(TestCase):
    def test_main_writes_a_usable_report_and_keeps_the_last_one_otherwise(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "regions/morro-bay").mkdir(parents=True)
            (root / "regions/morro-bay/latest.json").write_text(json.dumps(live()))
            self.assertEqual(cr.main(["--root", tmp], session=http.FakeSession(routes()), now=NOW), 0)
            path = root / "regions/morro-bay/coast-report.json"
            self.assertEqual(json.loads(path.read_text()), json.loads(FIXTURE.read_text()))
            down = {url: http.TransportError("offline") for url in routes()}
            (root / "regions/morro-bay/latest.json").write_text(json.dumps({**live(), "sources": {}}))
            self.assertEqual(cr.main(["--root", tmp], session=http.FakeSession(down), now=NOW), 1)
            self.assertEqual(json.loads(path.read_text()), json.loads(FIXTURE.read_text()))  # untouched

    def test_inputs_are_not_changed(self):
        feed = live()
        before = copy.deepcopy(feed)
        report(feed=feed)
        self.assertEqual(feed, before)
