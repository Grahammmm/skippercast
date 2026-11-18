"""SCA-279 / F09-06: a cached beach-health file is kept only if it is a usable edition, not just recently stamped.

Contract protected: `publish` skips the poll ("kept") only when the file is a successful edition for THIS region's
binding (region, county, source, non-empty site rows). Believable bug: `due` trusting only `sources[0].fetchedAt`
and `outcome == "ok"`, so a wrong-county or row-less file with a fresh clock suppresses the next poll until the
interval expires. All data is synthetic (the beach-health test fixtures); nothing is fetched.
"""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
from unittest import TestCase

from skippercast.http import FakeSession
from skippercast.pipeline import beach_health as bh
from tests.unit.test_beach_health import routes

NOW = datetime(2026, 10, 8, 15, tzinfo=timezone.utc)
RECENT = NOW + timedelta(minutes=10)  # well inside POLL_MINUTES


def valid_edition():
    return bh.collect("morro-bay", FakeSession(routes()), NOW)


def mutated(change):
    doc = copy.deepcopy(valid_edition())
    change(doc)
    return doc


def _row(key, value):
    def change(doc):
        doc["waterQuality"][0][key] = value
    return change


def _source(key, value):
    def change(doc):
        doc["sources"][0][key] = value
    return change


def _top(key, value):
    def change(doc):
        doc[key] = value
    return change


UNUSABLE = {
    "wrong county": _top("countyId", "other-county"),
    "wrong region": _top("regionId", "elsewhere"),
    "no site rows": _top("waterQuality", []),
    "rows missing": lambda doc: doc.pop("waterQuality"),
    "rows not a list": _top("waterQuality", {"a": 1}),
    "wrong schema version": _top("schemaVersion", 2),
    "wrong source id": _source("id", "synthetic-beach-status"),
    "wrong source url": _source("url", "https://feeds.example.invalid/beach"),
    "row from another source": _row("sourceId", "other-source"),
    "row outside the county": _row("lat", 10.0),
    "row with an invented sample date": _row("sampledAt", "2026-10-08T00:00:00.000Z"),
    "row claiming a sample date": _row("sampleDateAvailable", True),
    "row without identity": _row("id", ""),
    "two sources": lambda doc: doc["sources"].append(copy.deepcopy(doc["sources"][0])),
    "document not an object": None,
}
# Malformed rows: the BeachWaterQuality fields `parse` always writes, each deleted or given a wrong type.
# Believable bug: `_usable_edition` checking only identity/geometry, so a half-written row suppresses the poll.
for _key in ("name", "status", "advisory", "sampledAt", "sampleDateAvailable", "fetchedAt", "stationCode", "areaId"):
    UNUSABLE[f"row missing {_key}"] = (lambda key: lambda doc: doc["waterQuality"][0].pop(key))(_key)
UNUSABLE.update({
    "row name empty": _row("name", "  "),
    "row name not text": _row("name", 7),
    "row status empty": _row("status", ""),
    "row status not text": _row("status", None),
    "row advisory not text or null": _row("advisory", 5),
    "row stationCode not text or null": _row("stationCode", 12),
    "row fetchedAt not text": _row("fetchedAt", 1760000000),
    "row fetchedAt not a time": _row("fetchedAt", "yesterday"),
    "row fetchedAt without timezone": _row("fetchedAt", "2026-10-08T15:00:00"),
    "row areaId outside the binding": _row("areaId", "atlantis"),
    "row not an object": lambda doc: doc["waterQuality"].__setitem__(0, "row"),
})


class ReuseValidationTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "regions/morro-bay/beach-health.json"
        self.path.parent.mkdir(parents=True)

    def write(self, doc):
        self.path.write_text(json.dumps(doc))

    def test_valid_recent_edition_is_kept(self):
        """Positive control: the collector's own ok edition, polled again inside the interval, is kept with no fetch."""
        self.write(valid_edition())
        original = self.path.read_bytes()
        session = FakeSession({})
        self.assertFalse(bh.due(self.path, RECENT, bh.POLL_MINUTES, "morro-bay"))
        self.assertEqual(bh.publish(self.tmp.name, session, RECENT, regions=["morro-bay"]), {"morro-bay": "kept"})
        self.assertEqual(session.calls, [])
        self.assertEqual(self.path.read_bytes(), original)

    def test_unusable_recent_ok_files_are_due_and_refetched(self):
        """Negative control for the cited failure: each fresh-clock, outcome-ok file is due and is replaced."""
        for label, change in UNUSABLE.items():
            with self.subTest(case=label):
                doc = mutated(change) if change else ["not", "a", "feed"]
                self.write(doc)
                if isinstance(doc, dict):  # the clock and outcome stay good: only the payload is wrong
                    self.assertEqual(doc["sources"][0]["outcome"], "ok")
                self.assertTrue(bh.due(self.path, RECENT, bh.POLL_MINUTES, "morro-bay"))
                session = FakeSession(routes())
                self.assertEqual(bh.publish(self.tmp.name, session, RECENT, regions=["morro-bay"]), {"morro-bay": "ok"})
                self.assertTrue(session.calls)
                repaired = json.loads(self.path.read_text())
                self.assertEqual((repaired["countyId"], repaired["regionId"]), ("slo", "morro-bay"))
                self.assertEqual(len(repaired["waterQuality"]), 4)

    def test_no_region_keeps_clock_only_behaviour(self):
        """`due(path, now)` without a region still judges the clock alone (existing callers unchanged)."""
        self.write(mutated(_top("waterQuality", [])))
        self.assertFalse(bh.due(self.path, RECENT))
        self.assertTrue(bh.due(self.path, RECENT, bh.POLL_MINUTES, "morro-bay"))
        self.assertTrue(bh.due(self.path, RECENT, bh.POLL_MINUTES, "unbound-region"))
