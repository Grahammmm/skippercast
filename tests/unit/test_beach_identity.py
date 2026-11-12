"""Container-valued beach identities are refused, never turned into Python-repr IDs (offline, synthetic ArcGIS)."""

from datetime import datetime, timezone
import copy
import json
from unittest import TestCase

from skippercast.http import FakeSession
from skippercast.pipeline import beach_health as bh
from tests._support import FIXTURES

FIXTURE = FIXTURES / "beach-health"
BINDING = bh.BINDINGS["morro-bay"]
FETCHED = "2026-10-08T15:00:00.000Z"
NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)
CONTAINERS = ({}, [], {"site": "synthetic"}, ["synthetic"], {"a": [1, {"b": []}]}, [[]])


def payload():
    return json.loads((FIXTURE / "query.json").read_text())


def collect(query):
    routes = {bh.query_url(BINDING): json.dumps(query).encode(),
              bh.count_url(BINDING): (FIXTURE / "count.json").read_bytes()}
    return bh.collect("morro-bay", FakeSession(routes), NOW)


def with_attributes(index, **fields):
    data = payload()
    data["features"][index]["attributes"].update(fields)
    return data


class ContainerIdentityTests(TestCase):
    def test_selected_container_identity_refuses(self):
        # Each slot is the selected one: GlobalID_2 present; Station when GlobalID_2 is null; FID when both are null.
        slots = (("GlobalID_2", {}), ("Station", {"GlobalID_2": None}), ("FID", {"GlobalID_2": None, "Station": None}))
        for slot, nulls in slots:
            for value in CONTAINERS:
                with self.subTest(slot=slot, value=value):
                    data = with_attributes(0, **nulls, **{slot: value})
                    with self.assertRaisesRegex(ValueError, "^Missing beach identity$"):
                        bh.parse(data, 4, BINDING, FETCHED)

    def test_bad_preferred_identity_does_not_fall_back(self):
        # A malformed GlobalID_2 is not hidden by a valid Station/FID, nor a malformed Station by a valid FID.
        for value in CONTAINERS:
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "Missing beach identity"):
                    bh.parse(with_attributes(0, GlobalID_2=value, Station="TS1", FID=1), 4, BINDING, FETCHED)
                with self.assertRaisesRegex(ValueError, "Missing beach identity"):
                    bh.parse(with_attributes(0, GlobalID_2=None, Station=value, FID=1), 4, BINDING, FETCHED)
        # Absent or null higher-priority fields still allow a valid lower-priority scalar.
        data = with_attributes(0, FID=0, Station=None)
        del data["features"][0]["attributes"]["GlobalID_2"]
        self.assertIn("0", {r["id"] for r in bh.parse(data, 4, BINDING, FETCHED)})
        data = with_attributes(0, GlobalID_2=None)
        self.assertIn("TS1", {r["id"] for r in bh.parse(data, 4, BINDING, FETCHED)})

    def test_late_bad_identity_discards_all_rows(self):
        for value in CONTAINERS:
            with self.subTest(value=value):
                feed = collect(with_attributes(3, GlobalID_2=value))
                self.assertEqual(feed["waterQuality"], [])
                (source,) = feed["sources"]
                self.assertEqual((source["outcome"], source["error"]), ("error", "Missing beach identity"))

    def test_ordinary_scalar_fallbacks_and_strings_preserved(self):
        feed = collect(payload())
        self.assertEqual(feed["sources"][0]["outcome"], "ok")
        self.assertEqual(sorted(r["id"] for r in feed["waterQuality"]),
                         sorted([f"00000000-0000-4000-8000-00000000000{n}" for n in (1, 2, 3)] + ["TS4"]))
        # A string that merely looks like a container is still a string.
        rows = bh.parse(with_attributes(0, GlobalID_2="{}"), 4, BINDING, FETCHED)
        self.assertIn("{}", {r["id"] for r in rows})
        rows = bh.parse(with_attributes(0, GlobalID_2="['x']"), 4, BINDING, FETCHED)
        self.assertIn("['x']", {r["id"] for r in rows})

    def test_existing_missing_and_duplicate_rules_remain(self):
        for nulls in ({"GlobalID_2": None, "Station": None, "FID": None}, {"GlobalID_2": "", "Station": "TS1"}):
            with self.subTest(nulls=nulls):
                with self.assertRaisesRegex(ValueError, "^Missing beach identity$"):
                    bh.parse(with_attributes(0, **nulls), 4, BINDING, FETCHED)
        data = with_attributes(0, GlobalID_2=7)
        data["features"][1]["attributes"]["GlobalID_2"] = "7"
        with self.assertRaisesRegex(ValueError, "^Duplicate beach identity$"):
            bh.parse(data, 4, BINDING, FETCHED)

    def test_inputs_and_time_disclosures_unchanged(self):
        for data in (payload(), with_attributes(3, GlobalID_2=["x"])):
            before = copy.deepcopy(data)
            feed = collect(data)
            self.assertEqual(data, before)
            for row in feed["waterQuality"]:
                self.assertIsNone(row["sampledAt"])
                self.assertIs(row["sampleDateAvailable"], False)
                self.assertEqual(row["fetchedAt"], FETCHED)
        for data in (payload(), with_attributes(0, GlobalID_2={})):
            before = copy.deepcopy(data)
            try:
                bh.parse(data, 4, BINDING, FETCHED)
            except ValueError:
                pass
            self.assertEqual(data, before)
