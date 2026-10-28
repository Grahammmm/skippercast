"""Fail-closed retry and upstream-outage reporting for the NOAA ENC hazard step.

Stdlib only (no GIS packages), so this runs in the CI ``check`` job alongside the
product suite. It pins the two behaviors T05 added: (1) ``fetch_json`` retries the
exact transient NOAA "Could not find service" 500 and then fails closed, and
(2) the inventory reporter downgrades only an explicit upstream-unavailable
receipt to a warning, never a silently missing snapshot.
"""
import io
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

import research.scripts.refresh_enc_hazards as refresh
from research.scripts import report_enc_hazard_coverage as reporter

TRANSIENT = {"error": {"code": 500,
    "message": "Error handling service request :Could not find service. "
               "Service may be stopped or it may not be configured.",
    "details": []}}


class FakeResponse:
    def __init__(self, payload, url, status=200):
        self._payload = json.dumps(payload).encode() if not isinstance(payload, bytes) else payload
        self.status = status
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, _limit):
        return self._payload


def transient_then_ok(responses):
    """Return a urlopen side-effect that yields each response in order."""
    url = refresh.BASE + "/enc_harbour/MapServer?f=pjson"
    replies = iter(responses)
    def opener(request, timeout=35):
        payload = next(replies)
        return FakeResponse(payload, url)
    return opener


class EncHazardRetryTests(unittest.TestCase):
    def test_transient_then_success_returns_first_good_response(self):
        good = {"layers": [{"name": "Harbor.Obstruction_point", "id": 0}]}
        opener = transient_then_ok([TRANSIENT, TRANSIENT, good])
        with patch.object(refresh.urllib.request, "urlopen", side_effect=opener), \
             patch.object(refresh.time, "sleep") as slept:
            result, digest = refresh.fetch_json(refresh.BASE + "/enc_harbour/MapServer?f=pjson")
        self.assertEqual(result, good)
        self.assertEqual(slept.call_count, 2)  # one sleep per retry, not after success

    def test_persistent_transient_fails_closed_as_upstream_unavailable(self):
        opener = transient_then_ok([TRANSIENT] * refresh.TRANSIENT_ATTEMPTS)
        with patch.object(refresh.urllib.request, "urlopen", side_effect=opener), \
             patch.object(refresh.time, "sleep"):
            with self.assertRaises(refresh.EncUpstreamUnavailable):
                refresh.fetch_json(refresh.BASE + "/enc_harbour/MapServer?f=pjson")

    def test_other_error_is_not_retried_and_raises_value_error(self):
        opener = transient_then_ok([{"error": {"code": 500, "message": "Some other failure"}}])
        with patch.object(refresh.urllib.request, "urlopen", side_effect=opener), \
             patch.object(refresh.time, "sleep") as slept:
            with self.assertRaisesRegex(ValueError, "ENC service reported an error"):
                refresh.fetch_json(refresh.BASE + "/enc_harbour/MapServer?f=pjson")
        self.assertEqual(slept.call_count, 0)

    def test_near_match_without_both_markers_is_not_retried(self):
        # code 500 but only one marker -> not the transient signature.
        near = {"error": {"code": 500, "message": "Could not find service"}}
        opener = transient_then_ok([near])
        with patch.object(refresh.urllib.request, "urlopen", side_effect=opener), \
             patch.object(refresh.time, "sleep") as slept:
            with self.assertRaisesRegex(ValueError, "ENC service reported an error"):
                refresh.fetch_json(refresh.BASE + "/enc_harbour/MapServer?f=pjson")
        self.assertEqual(slept.call_count, 0)

    def test_non_500_error_is_not_retried(self):
        opener = transient_then_ok([{"error": {"code": 400, "message": "Bad request"}}])
        with patch.object(refresh.urllib.request, "urlopen", side_effect=opener), \
             patch.object(refresh.time, "sleep") as slept:
            with self.assertRaisesRegex(ValueError, "ENC service reported an error"):
                refresh.fetch_json(refresh.BASE + "/enc_harbour/MapServer?f=pjson")
        self.assertEqual(slept.call_count, 0)

    def test_foreign_host_is_refused_before_any_request(self):
        with patch.object(refresh.urllib.request, "urlopen") as opener:
            with self.assertRaisesRegex(ValueError, "outside the reviewed NOAA host"):
                refresh.fetch_json("https://example.com/enc_harbour/MapServer?f=pjson")
        opener.assert_not_called()


class EncHazardReporterTests(unittest.TestCase):
    def _write(self, directory, name, payload):
        path = Path(directory) / name
        path.write_text(json.dumps(payload))
        return path

    def _scope(self, directory, scope):
        return {"scope_id": scope, "region_id": "r", "bounds": [-119.12, 33.33, -118.98, 33.54]}

    def test_valid_snapshot_reports_clean(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"status": "charted-danger-screen-only", "scope_id": "santa-barbara-island",
                    "query_receipts": [{}] * 18, "features": [], "checked_at": "t"}
            self._write(d, "santa-barbara-island.geojson", data)
            lines, unhealthy = reporter.report(d, ("santa-barbara-island",))
        self.assertEqual(unhealthy, [])
        self.assertIn("charted features across 18 complete layer queries", lines[1])

    def test_explicit_upstream_receipt_warns_without_failing(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"status": "upstream_unavailable", "scope_id": "santa-barbara-island",
                    "checked_at": "t"}
            self._write(d, "santa-barbara-island.unavailable.json", data)
            lines, unhealthy = reporter.report(d, ("santa-barbara-island",))
        self.assertEqual(unhealthy, [])
        self.assertIn("upstream_unavailable", lines[1])

    def test_missing_snapshot_without_receipt_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            lines, unhealthy = reporter.report(d, ("santa-barbara-island",))
        self.assertEqual(unhealthy, ["santa-barbara-island"])

    def test_corrupt_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "santa-barbara-island.geojson").write_text("{not json")
            lines, unhealthy = reporter.report(d, ("santa-barbara-island",))
        self.assertEqual(unhealthy, ["santa-barbara-island"])

    def test_incomplete_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"status": "charted-danger-screen-only", "scope_id": "santa-barbara-island",
                    "query_receipts": [{}] * 10, "features": [], "checked_at": "t"}
            self._write(d, "santa-barbara-island.geojson", data)
            lines, unhealthy = reporter.report(d, ("santa-barbara-island",))
        self.assertEqual(unhealthy, ["santa-barbara-island"])

    def test_unexpected_receipt_status_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            data = {"status": "charted-danger-screen-only", "scope_id": "santa-barbara-island"}
            self._write(d, "santa-barbara-island.unavailable.json", data)
            lines, unhealthy = reporter.report(d, ("santa-barbara-island",))
        self.assertEqual(unhealthy, ["santa-barbara-island"])


class EncHazardUnavailableReceiptTests(unittest.TestCase):
    def test_record_unavailable_writes_receipt_and_warns_green(self):
        with tempfile.TemporaryDirectory() as d:
            output = Path(d) / "santa-barbara-island.geojson"
            scope = {"id": "santa-barbara-island", "region_id": "southern-california",
                     "bounds": [-119.12, 33.33, -118.98, 33.54]}
            error = refresh.EncUpstreamUnavailable("NOAA ENC Direct stayed unavailable")
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                refresh._record_unavailable(scope, output, error)
            printed = out.getvalue()
            self.assertIn("::warning", printed)
            self.assertIn("santa-barbara-island", printed)
            receipt = Path(d) / "santa-barbara-island.unavailable.json"
            self.assertTrue(receipt.is_file())
            data = json.loads(receipt.read_text())
            self.assertEqual(data["status"], "upstream_unavailable")
            self.assertEqual(data["scope_id"], "santa-barbara-island")
            self.assertIn("NOAA ENC Direct stayed unavailable", data["message"])

    def test_main_propagates_upstream_unavailable_to_receipt(self):
        # main() catches EncUpstreamUnavailable and records it; the receipt path
        # is derived from --output, which must stay under var/ (enforced earlier).
        scope = {"id": "santa-barbara-island", "region_id": "southern-california",
                 "bounds": [-119.12, 33.33, -118.98, 33.54],
                 "output": "dist/regions/southern-california/enc-hazards-santa-barbara.geojson"}
        error = refresh.EncUpstreamUnavailable("NOAA ENC Direct stayed unavailable")
        with patch.object(refresh, "refresh", side_effect=error), \
             patch.object(refresh, "_record_unavailable") as recorded, \
             patch("sys.argv", ["refresh_enc_hazards.py", "--scope", "santa-barbara-island"]):
            refresh.main()
        recorded.assert_called_once()
        self.assertEqual(recorded.call_args[0][0]["id"], "santa-barbara-island")


if __name__ == "__main__":
    unittest.main()
