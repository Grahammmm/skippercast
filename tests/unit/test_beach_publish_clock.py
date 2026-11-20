"""RF1930-1: an explicit publish clock drives both poll eligibility and feed timestamps."""

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
from unittest import TestCase, mock

from skippercast.http import FakeSession
from skippercast.pipeline import beach_health as bh
from tests.unit.test_beach_health import routes

T0 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
STAMP = "2000-01-01T12:00:00.000Z"


def feed(tmp):
    return json.loads((Path(tmp) / "regions/morro-bay/beach-health.json").read_text())


class PublishClockTests(TestCase):
    def test_explicit_publish_clock_prevents_immediate_refetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = FakeSession(routes())
            self.assertEqual(bh.publish(tmp, session, T0), {"morro-bay": "ok"})
            data, raw, calls = feed(tmp), (Path(tmp) / "regions/morro-bay/beach-health.json").read_bytes(), len(session.calls)
            self.assertEqual(data["generatedAt"], STAMP)
            self.assertEqual(data["sources"][0]["fetchedAt"], STAMP)
            self.assertEqual({r["fetchedAt"] for r in data["waterQuality"]}, {STAMP})
            self.assertEqual(bh.publish(tmp, session, T0), {"morro-bay": "kept"})
            self.assertEqual(len(session.calls), calls)
            self.assertEqual((Path(tmp) / "regions/morro-bay/beach-health.json").read_bytes(), raw)

    def test_poll_interval_boundary_uses_forwarded_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = FakeSession(routes())
            bh.publish(tmp, session, T0)
            calls = len(session.calls)
            late = T0 + timedelta(minutes=54, seconds=59)
            self.assertEqual(bh.publish(tmp, session, late), {"morro-bay": "kept"})
            self.assertEqual(len(session.calls), calls)
            edge = (T0 + timedelta(minutes=55)).astimezone(timezone(timedelta(hours=-8)))
            self.assertEqual(bh.publish(tmp, session, edge), {"morro-bay": "ok"})
            self.assertEqual(feed(tmp)["sources"][0]["fetchedAt"], "2000-01-01T12:55:00.000Z")
            calls = len(session.calls)
            self.assertEqual(bh.publish(tmp, session, edge), {"morro-bay": "kept"})
            self.assertEqual(len(session.calls), calls)

    def test_error_timestamp_is_injected_and_retry_remains_due(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(bh.publish(tmp, FakeSession({}), T0), {"morro-bay": "error"})
            data = feed(tmp)
            self.assertEqual((data["waterQuality"], data["generatedAt"], data["sources"][0]["fetchedAt"]), ([], STAMP, STAMP))
            self.assertTrue(bh.due(Path(tmp) / "regions/morro-bay/beach-health.json", T0))
            self.assertEqual(bh.publish(tmp, FakeSession(routes()), T0), {"morro-bay": "ok"})
            self.assertEqual(len(feed(tmp)["waterQuality"]), 4)

    def test_omitted_clock_preserves_collect_default(self):
        seen, real_collect = {}, bh.collect

        def fake_due(path, now, *args):
            seen["due"] = now
            return True

        def fake_collect(region_id, session, now=None):
            seen["collect"] = now
            return real_collect(region_id, session, T0)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(bh, "due", fake_due), \
                mock.patch.object(bh, "collect", fake_collect):
            bh.publish(tmp, FakeSession(routes()))
        self.assertIsNone(seen["collect"])
        self.assertIsNotNone(seen["due"].utcoffset())
