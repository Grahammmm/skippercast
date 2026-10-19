"""Offline integration regressions for NOAA ENC hazard invocation binding.

These exercise the real ``main`` -> ``refresh`` -> filesystem outputs -> the
workflow-selected reporter (``report_bound``), mocking ONLY the network
(``urllib.request.urlopen``) and ``time.sleep``. No stub of ``refresh`` and no
hand-made success snapshot: a success snapshot is only ever produced by a real
refresh run over the scripted responses.

The two reproduced defects (Sol review, offline probe) are pinned here:

- P1-a mixed hard-error/outage: a real parse/validation error must outrank an
  isolated upstream outage no matter the submission/completion order, instead of
  ``pool.map`` raising the first exception in input order and masking the hard
  error behind an outage receipt.
- P1-b stale snapshot: a historical valid snapshot can never satisfy a new
  invocation, and a current outage must remain visible next to it (labeled
  last-known), instead of the reporter quietly reporting the old coverage.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.scripts import refresh_enc_hazards as enc
from research.scripts import report_enc_hazard_coverage as reporter

TRANSIENT = {"error": {"code": 500,
    "message": "Error handling service request :Could not find service. "
               "Service may be stopped or it may not be configured.",
    "details": []}}

PREFIX = {"enc_harbour": "Harbor", "enc_approach": "Approach", "enc_coastal": "Coastal"}


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


def make_opener(plan):
    """Build a scripted urlopen for one scope's full metadata + 18 layer queries.

    ``plan`` maps ``(service, layer_id) -> mode`` with a ``default`` fallback.
    Modes: ok, transient (persistent 500), hard (count -1), malformed_count
    (count not an int), malformed_data (features not a list), empty (no bytes).
    """
    def opener(request, timeout=35):
        url = request.full_url
        metadata = re.search(r"/(enc_[a-z]+)/MapServer\?f=pjson", url)
        if metadata:
            service = metadata.group(1)
            payload = {"layers": [{"name": PREFIX[service] + "." + layer, "id": i}
                                  for i, layer in enumerate(enc.LAYERS)]}
            return FakeResponse(payload, url)
        match = re.search(r"/(enc_[a-z]+)/MapServer/(\d+)/query\?", url)
        service, layer_id = match.group(1), int(match.group(2))
        mode = plan.get(service, {}).get(layer_id, plan.get("default", "ok"))
        if mode == "transient":
            return FakeResponse(TRANSIENT, url)
        if mode == "empty":
            return FakeResponse(b"", url)
        is_count = "returnCountOnly" in url
        if is_count:
            if mode == "hard":
                return FakeResponse({"count": -1}, url)
            if mode == "malformed_count":
                return FakeResponse({"count": "not-an-int"}, url)
            return FakeResponse({"count": 0}, url)
        if mode == "malformed_data":
            return FakeResponse({"type": "FeatureCollection", "features": "not-a-list"}, url)
        return FakeResponse({"type": "FeatureCollection", "features": []}, url)
    return opener


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


class EncHazardInvocationBindingTests(unittest.TestCase):
    SCOPE = "santa-barbara-island"

    def setUp(self):
        (enc.ROOT / "var").mkdir(exist_ok=True)

    def _directory(self):
        directory = tempfile.TemporaryDirectory(dir=enc.ROOT / "var")
        self.addCleanup(directory.cleanup)
        return Path(directory.name)

    def _run(self, scope, output, plan):
        opener = make_opener(plan)
        stdout = io.StringIO()
        error = None
        try:
            with patch.object(enc.urllib.request, "urlopen", side_effect=opener), \
                 patch.object(enc.time, "sleep"), \
                 patch("sys.argv", ["refresh_enc_hazards.py", "--scope", scope, "--output", str(output)]), \
                 patch.dict("os.environ", {"GITHUB_STEP_SUMMARY": ""}), \
                 contextlib.redirect_stdout(stdout):
                enc.main()
        except Exception as exc:  # noqa: BLE001 - capture the hard failure
            error = exc
        return error, stdout.getvalue()

    def _run_scope(self, plan, scope=SCOPE):
        directory = self._directory()
        output = directory / (scope + ".geojson")
        error, stdout = self._run(scope, output, plan)
        return directory, output, error, stdout

    def _status(self, directory, scope=SCOPE):
        return json.loads((directory / (scope + enc.RUN_STATUS_SUFFIX)).read_text())

    def test_success_writes_snapshot_and_terminal_status(self):
        directory, output, error, _ = self._run_scope({"default": "ok"})
        self.assertIsNone(error)
        self.assertTrue(output.is_file())
        snapshot = json.loads(output.read_text())
        status = self._status(directory)
        self.assertEqual(status["status"], "success")
        self.assertEqual(status["checked_at"], snapshot["checked_at"])
        self.assertEqual(status["artifact"], output.name)
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [])
        self.assertIn("charted features across 18 complete layer queries", lines[1])

    def test_isolated_persistent_outage_warns_green_with_receipt(self):
        directory, output, error, _ = self._run_scope({"default": "transient"})
        self.assertIsNone(error)
        self.assertFalse(output.is_file())
        receipt = json.loads((directory / (self.SCOPE + ".unavailable.json")).read_text())
        self.assertEqual(receipt["status"], "upstream_unavailable")
        status = self._status(directory)
        self.assertEqual(status["status"], "upstream_unavailable")
        self.assertEqual(status["checked_at"], receipt["checked_at"])
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [])
        self.assertIn("upstream_unavailable", lines[1])

    def test_unexpected_empty_response_fails_closed(self):
        directory, _, error, _ = self._run_scope({"enc_harbour": {0: "empty"}})
        self.assertIsInstance(error, ValueError)
        self.assertIn("empty or oversized", str(error))
        self.assertEqual(self._status(directory)["status"], "failed")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [self.SCOPE])

    def test_malformed_data_fails_closed(self):
        directory, _, error, _ = self._run_scope({"enc_approach": {1: "malformed_data"}})
        self.assertIsInstance(error, ValueError)
        self.assertIn("Incomplete or changed ENC", str(error))
        self.assertEqual(self._status(directory)["status"], "failed")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [self.SCOPE])

    def test_mixed_outage_then_hard_error_raises_hard_not_outage(self):
        # P1-a ordering 1: harbour layer 0 persistently transient (outage) is
        # submitted before harbour layer 1 invalid count (hard). The hard error
        # must win, and no outage receipt may mask it.
        plan = {"enc_harbour": {0: "transient", 1: "hard"}}
        directory, output, error, _ = self._run_scope(plan)
        self.assertIsInstance(error, ValueError)
        self.assertIn("count is missing or exceeds", str(error))
        self.assertFalse(output.is_file())
        self.assertFalse((directory / (self.SCOPE + ".unavailable.json")).is_file())
        self.assertEqual(self._status(directory)["status"], "failed")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [self.SCOPE])
        self.assertNotIn("upstream_unavailable", lines[1])

    def test_mixed_hard_error_then_outage_raises_hard_not_outage(self):
        # P1-a ordering 2: the hard error is submitted before the outage.
        plan = {"enc_harbour": {0: "hard", 1: "transient"}}
        directory, output, error, _ = self._run_scope(plan)
        self.assertIsInstance(error, ValueError)
        self.assertIn("count is missing or exceeds", str(error))
        self.assertFalse(output.is_file())
        self.assertFalse((directory / (self.SCOPE + ".unavailable.json")).is_file())
        self.assertEqual(self._status(directory)["status"], "failed")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [self.SCOPE])

    def test_success_then_outage_reports_outage_and_last_known_snapshot(self):
        # P1-b: a current outage stays visible next to a historical valid
        # snapshot, which is only labeled last-known.
        directory = self._directory()
        output = directory / (self.SCOPE + ".geojson")
        error, _ = self._run(self.SCOPE, output, {"default": "ok"})
        self.assertIsNone(error)
        first = json.loads(output.read_text())["checked_at"]
        error, _ = self._run(self.SCOPE, output, {"default": "transient"})
        self.assertIsNone(error)
        status = self._status(directory)
        self.assertEqual(status["status"], "upstream_unavailable")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [])
        self.assertIn("upstream_unavailable", lines[1])
        self.assertIn("last-known charted-danger snapshot from " + first, "\n".join(lines))

    def test_outage_then_success_retires_outage(self):
        directory = self._directory()
        output = directory / (self.SCOPE + ".geojson")
        error, _ = self._run(self.SCOPE, output, {"default": "transient"})
        self.assertIsNone(error)
        self.assertTrue((directory / (self.SCOPE + ".unavailable.json")).is_file())
        error, _ = self._run(self.SCOPE, output, {"default": "ok"})
        self.assertIsNone(error)
        self.assertEqual(self._status(directory)["status"], "success")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [])
        self.assertIn("charted features across 18 complete layer queries", lines[1])
        self.assertNotIn("upstream_unavailable", "\n".join(lines))

    def test_stale_snapshot_and_receipt_cannot_satisfy_new_invocation(self):
        directory = self._directory()
        stale_snapshot = directory / (self.SCOPE + ".geojson")
        stale_receipt = directory / (self.SCOPE + ".unavailable.json")
        write_json(stale_snapshot, {"status": "charted-danger-screen-only",
            "scope_id": self.SCOPE, "query_receipts": [{}] * 18, "features": [],
            "checked_at": "2000-01-01T00:00:00Z"})
        write_json(stale_receipt, {"status": "upstream_unavailable", "scope_id": self.SCOPE,
            "checked_at": "2000-01-01T00:00:00Z"})
        # A new invocation that succeeds must not be satisfied by the stale files.
        output = directory / (self.SCOPE + ".geojson")
        error, _ = self._run(self.SCOPE, output, {"default": "ok"})
        self.assertIsNone(error)
        fresh = json.loads(output.read_text())["checked_at"]
        self.assertNotEqual(fresh, "2000-01-01T00:00:00Z")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [])
        self.assertIn(fresh, lines[1])
        self.assertNotIn("2000-01-01", "\n".join(lines))

    def test_hard_failure_not_masked_by_prior_output(self):
        directory = self._directory()
        output = directory / (self.SCOPE + ".geojson")
        # Prior invocation produced a valid snapshot and terminal status.
        error, _ = self._run(self.SCOPE, output, {"default": "ok"})
        self.assertIsNone(error)
        self.assertEqual(self._status(directory)["status"], "success")
        # New invocation hard-fails; the prior success must not satisfy the run.
        error, _ = self._run(self.SCOPE, output, {"enc_harbour": {0: "malformed_count"}})
        self.assertIsInstance(error, ValueError)
        self.assertEqual(self._status(directory)["status"], "failed")
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [self.SCOPE])
        self.assertIn("failed", lines[1])

    def test_three_scopes_share_invocation_and_report_together(self):
        directory = self._directory()
        for scope in reporter.SCOPES:
            output = directory / (scope + ".geojson")
            error, _ = self._run(scope, output, {"default": "ok"})
            self.assertIsNone(error)
        lines, unhealthy = reporter.report_bound(directory)
        self.assertEqual(unhealthy, [])
        self.assertEqual(len([line for line in lines if "charted features across" in line]), 3)

    def test_bare_stale_snapshot_without_status_fails_closed(self):
        directory = self._directory()
        write_json(directory / (self.SCOPE + ".geojson"), {
            "status": "charted-danger-screen-only", "scope_id": self.SCOPE,
            "query_receipts": [{}] * 18, "features": [], "checked_at": "2000-01-01T00:00:00Z"})
        lines, unhealthy = reporter.report_bound(directory, (self.SCOPE,))
        self.assertEqual(unhealthy, [self.SCOPE])
        self.assertIn("no current invocation status", lines[1])


if __name__ == "__main__":
    unittest.main()
