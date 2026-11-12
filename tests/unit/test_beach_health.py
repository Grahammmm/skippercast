"""FE-41: SLO County beach-health collector, offline against synthetic ArcGIS responses."""

from datetime import datetime, timedelta, timezone
import copy
import json
from pathlib import Path
import re
import tempfile
from unittest import TestCase

from skippercast.http import FakeSession, TransportError
from skippercast.pipeline import beach_health as bh
from tests._support import FIXTURES as ALL_FIXTURES, ROOT
from tests.unit.test_ndbc_history import TsTypes

FIXTURES = ALL_FIXTURES / "beach-health"
BINDING = bh.BINDINGS["morro-bay"]
FETCHED = "2026-10-08T15:00:00.000Z"
NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)


def fixture(name):
    return json.loads((FIXTURES / name).read_text())


def coast_types():
    """BeachWaterQuality and SourceStatus as packages/coast declares them."""
    checker = TsTypes.__new__(TsTypes)
    enrichment = (ROOT / "packages/coast/src/enrichment-types.ts").read_text()
    body = re.search(r"export type BeachWaterQuality = (\{.*?\});", enrichment, re.S).group(1)
    status = re.search(r"^export type SourceStatus = (.*);$", (ROOT / "packages/coast/src/types.ts").read_text(), re.M).group(1)
    checker.types = {"BeachWaterQuality": re.sub(r"\s*\n\s*", "", body), "SourceStatus": status}
    return checker


def routes(query=None, count=None):
    return {bh.query_url(BINDING): json.dumps(query or fixture("query.json")).encode(),
            bh.count_url(BINDING): json.dumps(count or fixture("count.json")).encode()}


class ParseTests(TestCase):
    def setUp(self):
        self.payload = fixture("query.json")

    def test_rows_validate_against_beach_water_quality(self):
        rows = bh.parse(self.payload, 4, BINDING, FETCHED)
        self.assertEqual(coast_types().errors(rows, "BeachWaterQuality[]"), [])
        self.assertEqual([r["name"] for r in rows], ["TS3", "Test Shore Central 2", "Test Shore North 1", "Test Shore South 4"])
        broken = copy.deepcopy(rows)
        broken[0]["sampledAt"], broken[1]["lat"] = 3, "35"
        del broken[2]["sourceId"]
        self.assertEqual(len(coast_types().errors(broken, "BeachWaterQuality[]")), 3)

    def test_no_date_is_invented(self):
        rows = bh.parse(self.payload, 4, BINDING, FETCHED)
        for row in rows:
            self.assertIsNone(row["sampledAt"])
            self.assertIs(row["sampleDateAvailable"], False)
            self.assertEqual(row["fetchedAt"], FETCHED)
            # The only time in a row is the retrieval time; the view's edit time is never carried.
            dated = [v for v in row.values() if isinstance(v, str) and re.match(r"\d{4}-\d\d-\d\d", v)]
            self.assertEqual(dated, [FETCHED])
            self.assertNotIn("1790000000", json.dumps(row))

    def test_status_text_link_and_area_only(self):
        rows = {r["stationCode"]: r for r in bh.parse(self.payload, 4, BINDING, FETCHED)}
        self.assertEqual({k: r["areaId"] for k, r in rows.items()}, {"TS1": "north", "TS2": "central", "TS3": "south", "TS4": "south"})
        self.assertEqual(rows["TS2"]["status"], "Beach Health Advisory")
        self.assertEqual(rows["TS2"]["lon"], -120.88)  # geometry, not the missing Longitude attribute
        self.assertEqual(rows["TS2"]["advisory"], "Beach Health Advisory · Elevated bacteria in the last sample.")
        self.assertEqual(rows["TS3"]["advisory"], "Beach Closure")  # duplicates collapse
        self.assertEqual(rows["TS3"]["status"], "Beach Closure")
        self.assertEqual((rows["TS4"]["status"], rows["TS4"]["advisory"], rows["TS4"]["id"]), ("Unknown", None, "TS4"))
        self.assertTrue(all(r["url"] == BINDING["pageUrl"] and r["sourceId"] == "slo-beach-water-quality" for r in rows.values()))

    def test_incomplete_responses_raise(self):
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            bh.parse({**self.payload, "exceededTransferLimit": True}, 4, BINDING, FETCHED)
        for expected in (3, 5, 0):
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                bh.parse(self.payload, expected, BINDING, FETCHED)
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            bh.parse({"features": []}, 0, BINDING, FETCHED)
        with self.assertRaisesRegex(ValueError, "ArcGIS error: Token required"):
            bh.parse({"error": {"code": 499, "message": "Token required"}}, 4, BINDING, FETCHED)
        with self.assertRaisesRegex(ValueError, "reference system"):
            bh.parse({**self.payload, "spatialReference": {"wkid": 3857}}, 4, BINDING, FETCHED)

    def test_spatial_reference_requires_integer_4326(self):
        for wkid in (0, False, True, None, "", "4326", 4326.0, [], {}, 3857):
            payload = {**self.payload, "spatialReference": {"wkid": wkid}}
            with self.subTest(wkid=wkid), self.assertRaisesRegex(ValueError, "^Unexpected beach coordinate reference system$"):
                bh.parse(payload, 4, BINDING, FETCHED)
        for declaration in ({}, {"latestWkid": 4326}):  # empty object or the key missing from an object
            with self.subTest(declaration=declaration), self.assertRaisesRegex(ValueError, "^Unexpected beach coordinate reference system$"):
                bh.parse({**self.payload, "spatialReference": declaration}, 4, BINDING, FETCHED)

    def test_latest_wkid_must_agree_with_wkid(self):
        expected = bh.parse(self.payload, 4, BINDING, FETCHED)
        for latest in (3857, 0, False, None, "4326", 4326.0, [], {}):
            payload = {**self.payload, "spatialReference": {"wkid": 4326, "latestWkid": latest}}
            with self.subTest(latest=latest), self.assertRaisesRegex(ValueError, "^Unexpected beach coordinate reference system$"):
                bh.parse(payload, 4, BINDING, FETCHED)
        with self.assertRaisesRegex(ValueError, "^Unexpected beach coordinate reference system$"):
            bh.parse({**self.payload, "spatialReference": {"latestWkid": 4326}}, 4, BINDING, FETCHED)
        for declaration in ({"wkid": 4326, "latestWkid": 4326}, {"wkid": 4326}):
            with self.subTest(declaration=declaration):
                self.assertEqual(bh.parse({**self.payload, "spatialReference": declaration}, 4, BINDING, FETCHED), expected)

    def test_absent_spatial_reference_compatibility(self):
        expected = bh.parse(self.payload, 4, BINDING, FETCHED)
        absent = {k: v for k, v in self.payload.items() if k != "spatialReference"}
        self.assertEqual(bh.parse(absent, 4, BINDING, FETCHED), expected)
        self.assertEqual(bh.parse({**self.payload, "spatialReference": None}, 4, BINDING, FETCHED), expected)
        with self.assertRaisesRegex(ValueError, "reference system"):  # an explicitly empty object is not an absent one
            bh.parse({**self.payload, "spatialReference": {}}, 4, BINDING, FETCHED)

    def test_out_of_county_or_missing_geometry_is_rejected(self):
        for geometry in ({"x": -118.0, "y": 34.0}, {"x": -120.6, "y": 35.9}, {"x": -13_440_000.0, "y": 4_200_000.0},
                         {"x": True, "y": 35.3}, {"x": -120.8}, None):
            payload = copy.deepcopy(self.payload)
            payload["features"][0]["geometry"] = geometry
            with self.subTest(geometry=geometry), self.assertRaisesRegex(ValueError, "out-of-county"):
                bh.parse(payload, 4, BINDING, FETCHED)

    def test_identity_must_be_present_and_unique(self):
        payload = copy.deepcopy(self.payload)
        payload["features"][1]["attributes"]["GlobalID_2"] = payload["features"][0]["attributes"]["GlobalID_2"]
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            bh.parse(payload, 4, BINDING, FETCHED)
        payload = copy.deepcopy(self.payload)
        payload["features"][3]["attributes"].update(GlobalID_2=None, Station=None, FID=None)
        with self.assertRaisesRegex(ValueError, "Missing beach identity"):
            bh.parse(payload, 4, BINDING, FETCHED)


class CollectTests(TestCase):
    def test_feed_carries_rows_and_an_ok_source(self):
        session = FakeSession(routes())
        feed = bh.collect("morro-bay", session, NOW)
        types = coast_types()
        self.assertEqual(types.errors(feed["waterQuality"], "BeachWaterQuality[]"), [])
        self.assertEqual(types.errors(feed["sources"], "SourceStatus[]"), [])
        self.assertEqual((feed["countyId"], feed["regionId"], len(feed["waterQuality"])), ("slo", "morro-bay", 4))
        self.assertEqual(feed["sources"][0]["outcome"], "ok")
        self.assertEqual(feed["sources"][0]["fetchedAt"], bh.iso(NOW))
        self.assertTrue(all(call[1].startswith(bh.SERVICE_PREFIX) for call in session.calls))

    def test_failures_publish_no_rows_and_an_error_source(self):
        cases = {"transport": {**routes(), bh.query_url(BINDING): TransportError("offline")},
                 "count mismatch": routes(count={"count": 19}),
                 "count error": routes(count={"error": {"code": 400}}),
                 "transfer limit": routes(query={**fixture("query.json"), "exceededTransferLimit": True}),
                 "not json": {**routes(), bh.query_url(BINDING): b"<html>"}}
        for name, case in cases.items():
            with self.subTest(case=name):
                feed = bh.collect("morro-bay", FakeSession(case), NOW)
                self.assertEqual(feed["waterQuality"], [])
                self.assertEqual(feed["sources"][0]["outcome"], "error")
                self.assertTrue(feed["sources"][0]["error"])
                self.assertEqual(coast_types().errors(feed["sources"], "SourceStatus[]"), [])

    def assert_published_error(self, query):
        """The CLI path: publish() writes zero rows and an error source instead of crashing."""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bh.publish(tmp, FakeSession(routes(query=query))), {"morro-bay": "error"})
            feed = json.loads((Path(tmp) / "regions/morro-bay/beach-health.json").read_text())
        self.assertEqual(feed["waterQuality"], [])
        self.assertEqual(feed["sources"][0]["outcome"], "error")
        self.assertTrue(feed["sources"][0]["error"])
        self.assertEqual(coast_types().errors(feed["sources"], "SourceStatus[]"), [])

    def test_non_object_geometry_publishes_an_error_source(self):
        for geometry in ("POINT (-120.8 35.3)", [-120.8, 35.3], 35.3):
            payload = fixture("query.json")
            payload["features"][0]["geometry"] = geometry
            with self.subTest(geometry=geometry):
                with self.assertRaisesRegex(ValueError, "out-of-county"):
                    bh.parse(payload, 4, BINDING, FETCHED)
                self.assert_published_error(payload)

    def test_non_object_spatial_reference_publishes_an_error_source(self):
        for spatial_reference in ("4326", "EPSG:3857", [4326]):
            payload = {**fixture("query.json"), "spatialReference": spatial_reference}
            with self.subTest(spatial_reference=spatial_reference):
                with self.assertRaisesRegex(ValueError, "reference system"):
                    bh.parse(payload, 4, BINDING, FETCHED)
                self.assert_published_error(payload)

    def test_malformed_crs_publishes_no_rows(self):
        families = [{"wkid": w} for w in (0, False, True, None, "", "4326", 4326.0, [], {}, 3857)]
        families += [{}, {"latestWkid": 4326}]
        families += [{"wkid": 4326, "latestWkid": v} for v in (3857, 0, False, None, "4326", 4326.0, [], {})]
        for declaration in families:
            payload = {**fixture("query.json"), "spatialReference": declaration}
            with self.subTest(spatialReference=declaration):
                feed = bh.collect("morro-bay", FakeSession(routes(query=payload)), NOW)
                self.assertEqual(feed["waterQuality"], [])
                self.assertEqual(feed["sources"][0]["outcome"], "error")
                self.assertEqual(feed["sources"][0]["error"], "Unexpected beach coordinate reference system")
                self.assert_published_error(payload)
        for declaration in ({"wkid": 4326, "latestWkid": 4326}, {"wkid": 4326}, None):  # valid controls stay ok
            feed = bh.collect("morro-bay", FakeSession(routes(query={**fixture("query.json"), "spatialReference": declaration})), NOW)
            self.assertEqual((len(feed["waterQuality"]), feed["sources"][0]["outcome"]), (4, "ok"))

    def test_unbound_region_and_unreviewed_host(self):
        self.assertIsNone(bh.collect("crescent-city", FakeSession({}), NOW))
        with self.assertRaisesRegex(ValueError, "Unreviewed"):
            bh._json(FakeSession({}), "https://services9.arcgis.com/x/arcgis/rest/services/y/FeatureServer/0/query")


class PublishTests(TestCase):
    def test_writes_each_bound_region_and_polls_about_hourly(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = FakeSession(routes())
            self.assertEqual(bh.publish(tmp, session), {"morro-bay": "ok"})
            path = Path(tmp) / "regions/morro-bay/beach-health.json"
            self.assertEqual(len(json.loads(path.read_text())["waterQuality"]), 4)
            calls = len(session.calls)
            fetched = datetime.fromisoformat(json.loads(path.read_text())["sources"][0]["fetchedAt"].replace("Z", "+00:00"))
            self.assertEqual(bh.publish(tmp, session, fetched + timedelta(minutes=30)), {"morro-bay": "kept"})
            self.assertEqual(len(session.calls), calls)
            self.assertEqual(bh.publish(tmp, session, fetched + timedelta(minutes=56)), {"morro-bay": "ok"})

    def test_an_error_is_retried_next_cycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bh.publish(tmp, FakeSession({})), {"morro-bay": "error"})
            self.assertTrue(bh.due(Path(tmp) / "regions/morro-bay/beach-health.json", NOW))
        self.assertTrue(bh.due(Path("/nonexistent/beach-health.json"), NOW))


HUGE = 10**400  # valid JSON integer far outside float range
GEOMETRY_ERROR = "^Invalid/out-of-county beach geometry$"


def oversized(axis, value):
    """The synthetic fixture with only the last feature's `axis` set to `value`."""
    payload = fixture("query.json")
    payload["features"][-1]["geometry"][axis] = value
    return payload


def oversized_routes(axis, value):
    return {**routes(), bh.query_url(BINDING): json.dumps(oversized(axis, value), allow_nan=False).encode()}


VARIANTS = [(axis, sign * HUGE) for axis in ("x", "y") for sign in (1, -1)]


class OversizedCoordinateTests(TestCase):
    def test_oversized_integer_geometry_is_named(self):
        for axis, value in VARIANTS:
            payload = oversized(axis, value)
            before = copy.deepcopy(payload)
            with self.subTest(axis=axis, negative=value < 0), self.assertRaisesRegex(ValueError, GEOMETRY_ERROR):
                bh.parse(payload, 4, BINDING, FETCHED)
            self.assertEqual(payload, before)

    def test_oversized_integer_json_collect_has_no_partial_rows(self):
        for axis, value in VARIANTS:
            with self.subTest(axis=axis, negative=value < 0):
                feed = bh.collect("morro-bay", FakeSession(oversized_routes(axis, value)), NOW)
                self.assertEqual(feed["waterQuality"], [])
                self.assertEqual(len(feed["sources"]), 1)
                self.assertEqual(feed["sources"][0]["outcome"], "error")
                self.assertEqual(feed["sources"][0]["error"], "Invalid/out-of-county beach geometry")
                self.assertEqual(coast_types().errors(feed["sources"], "SourceStatus[]"), [])

    def stale_success(self, root):
        path = Path(root) / "regions/morro-bay/beach-health.json"
        path.parent.mkdir(parents=True)
        stale = bh.collect("morro-bay", FakeSession(routes()), NOW - timedelta(hours=3))
        path.write_text(json.dumps(stale))
        self.assertEqual(len(stale["waterQuality"]), 4)
        return path

    def test_oversized_integer_publish_replaces_stale_success(self):
        for axis, value in VARIANTS:
            with self.subTest(axis=axis, negative=value < 0), tempfile.TemporaryDirectory() as tmp:
                path = self.stale_success(tmp)
                self.assertEqual(bh.publish(tmp, FakeSession(oversized_routes(axis, value)), NOW), {"morro-bay": "error"})
                feed = json.loads(path.read_text())
                self.assertEqual(feed["waterQuality"], [])
                self.assertEqual((feed["sources"][0]["outcome"], feed["sources"][0]["error"]),
                                 ("error", "Invalid/out-of-county beach geometry"))

    def test_geometry_error_retries_and_recovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.stale_success(tmp)
            self.assertEqual(bh.publish(tmp, FakeSession(oversized_routes("y", HUGE)), NOW), {"morro-bay": "error"})
            # An error feed is due at once, even though its retrieval time is recent.
            fetched = datetime.fromisoformat(json.loads(path.read_text())["sources"][0]["fetchedAt"].replace("Z", "+00:00"))
            self.assertTrue(bh.due(path, fetched))
            self.assertTrue(bh.due(path, fetched + timedelta(minutes=1)))
            self.assertEqual(bh.publish(tmp, FakeSession(routes()), fetched + timedelta(minutes=1)), {"morro-bay": "ok"})
            feed = json.loads(path.read_text())
            self.assertEqual((feed["sources"][0]["outcome"], len(feed["waterQuality"])), ("ok", 4))

    def test_numeric_geometry_compatibility(self):
        healthy = bh.parse(fixture("query.json"), 4, BINDING, FETCHED)
        self.assertEqual(sorted((r["lon"], r["lat"]) for r in healthy),
                         sorted((f["geometry"]["x"], f["geometry"]["y"]) for f in fixture("query.json")["features"]))
        county = fixture("query.json")
        county["features"][-1]["geometry"] = {"x": -121, "y": 35}  # in-bounds integers stay accepted and exact
        rows = bh.parse(county, 4, BINDING, FETCHED)
        exact = [r for r in rows if (r["lat"], r["lon"]) == (35, -121)]
        self.assertEqual([(type(r["lat"]), type(r["lon"])) for r in exact], [(int, int)])
        for axis, value in (("x", -118), ("y", 34), ("x", -(2**60)), ("y", 2**60), ("x", True), ("y", False), ("x", None),
                            ("y", "35.3"), ("x", float("nan")), ("y", float("inf")), ("x", float("-inf"))):
            with self.subTest(axis=axis, value=value), self.assertRaisesRegex(ValueError, GEOMETRY_ERROR):
                bh.parse(oversized(axis, value), 4, BINDING, FETCHED)
