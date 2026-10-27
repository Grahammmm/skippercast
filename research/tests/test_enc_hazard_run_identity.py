"""Run/attempt identity regressions for the NOAA ENC hazard inventory reporter.

Each research-daily run (and each rerun attempt) has one invocation identity
shared by the three refresh commands and the coverage reporter. These tests
drive the real CLIs (``refresh_enc_hazards.main`` and
``report_enc_hazard_coverage.main``) over a real directory, mocking only
``urllib.request.urlopen`` and ``time.sleep``.

The first three tests are Sol's offline review probe (binding_review_probe.py,
review of 74f83141) kept as regressions: before this change a terminal status
or outage left by an earlier run satisfied a later run, and a status naming the
wrong artifact was accepted.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research.scripts import refresh_enc_hazards as enc
from research.scripts import report_enc_hazard_coverage as reporter
from research.tests.test_enc_hazard_invocation_binding import make_opener

IDENTITY_KEYS = ("ENC_INVOCATION_ID", "GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT")


@contextlib.contextmanager
def identity_env(**values):
    """Patch os.environ with only the given identity variables set."""
    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": ""}):
        for key in IDENTITY_KEYS:
            os.environ.pop(key, None)
        os.environ.update(values)
        yield


def github(run_id, attempt=1):
    return {"GITHUB_RUN_ID": str(run_id), "GITHUB_RUN_ATTEMPT": str(attempt)}


class EncRunIdentityTests(unittest.TestCase):
    STALE = reporter.SCOPES[-1]

    def setUp(self):
        (enc.ROOT / "var").mkdir(exist_ok=True)
        directory = tempfile.TemporaryDirectory(dir=enc.ROOT / "var")
        self.addCleanup(directory.cleanup)
        self.directory = Path(directory.name)

    def refresh(self, scope, env, mode="ok", args=()):
        argv = ["refresh_enc_hazards.py", "--scope", scope,
                "--output", str(self.directory / (scope + ".geojson")), *args]
        with patch.object(enc.urllib.request, "urlopen", side_effect=make_opener({"default": mode})), \
             patch.object(enc.time, "sleep"), identity_env(**env), patch("sys.argv", argv), \
             contextlib.redirect_stdout(io.StringIO()):
            enc.main()

    def report(self, env, args=()):
        out = io.StringIO()
        argv = ["report_enc_hazard_coverage.py", "--directory", str(self.directory), *args]
        code = 0
        with identity_env(**env), patch("sys.argv", argv), contextlib.redirect_stdout(out):
            try:
                reporter.main()
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def status_path(self, scope):
        return self.directory / (scope + enc.RUN_STATUS_SUFFIX)

    def status(self, scope):
        return json.loads(self.status_path(scope).read_text())

    def refresh_all(self, env, mode="ok"):
        for scope in reporter.SCOPES:
            self.refresh(scope, env, mode)

    # Sol probe 1: prior terminal status satisfied a new run.
    def test_probe_prior_terminal_status_cannot_satisfy_new_run(self):
        self.refresh_all(github(1001))
        prior = json.loads((self.directory / (self.STALE + ".geojson")).read_text())["checked_at"]
        for scope in reporter.SCOPES[:-1]:
            self.refresh(scope, github(1002))
        code, text = self.report(github(1002))
        self.assertNotEqual(code, 0)
        self.assertIn(self.STALE, str(code))
        self.assertNotIn("retrieved " + prior, text)
        self.assertIn("belongs to invocation 'github:1001:1'", text)
        _, unhealthy = reporter.report_bound(self.directory, invocation="github:1002:1")
        self.assertEqual(unhealthy, [self.STALE])

    # Sol probe 2: a status naming the wrong artifact was accepted.
    def test_probe_wrong_artifact_rejected(self):
        self.refresh_all(github(2001))
        self.assertEqual(self.report(github(2001))[0], 0)
        status = self.status(self.STALE)
        status["artifact"] = "nonexistent.geojson"
        self.status_path(self.STALE).write_text(json.dumps(status))
        code, text = self.report(github(2001))
        self.assertNotEqual(code, 0)
        self.assertIn("expected 'h11967-greenwood-tile.geojson'", text)
        _, unhealthy = reporter.report_bound(self.directory, invocation="github:2001:1")
        self.assertEqual(unhealthy, [self.STALE])

    # Sol probe 3: a prior outage and its status satisfied a later run.
    def test_probe_prior_outage_cannot_satisfy_later_run(self):
        self.refresh_all(github(3001))
        self.refresh(self.STALE, github(3002), mode="transient")
        self.assertEqual(self.status(self.STALE)["status"], "upstream_unavailable")
        code, text = self.report(github(3003))
        self.assertNotEqual(code, 0)
        _, unhealthy = reporter.report_bound(self.directory, invocation="github:3003:1")
        self.assertEqual(unhealthy, list(reporter.SCOPES))
        self.assertNotIn("upstream_unavailable - NOAA", text)

    def test_current_outage_with_same_identity_is_green_warning(self):
        for scope in reporter.SCOPES[:-1]:
            self.refresh(scope, github(3101))
        self.refresh(self.STALE, github(3101), mode="transient")
        code, text = self.report(github(3101))
        self.assertEqual(code, 0)
        self.assertIn(self.STALE + ": upstream_unavailable", text)
        receipt = json.loads((self.directory / (self.STALE + ".unavailable.json")).read_text())
        self.assertEqual(receipt["invocation"], "github:3101:1")

    def test_rerun_attempt_does_not_inherit_previous_attempt(self):
        self.refresh_all(github(4001, attempt=1))
        code, text = self.report(github(4001, attempt=2))
        self.assertNotEqual(code, 0)
        self.assertIn("belongs to invocation 'github:4001:1'", text)
        self.refresh_all(github(4001, attempt=2))
        self.assertEqual(self.report(github(4001, attempt=2))[0], 0)

    def test_skipped_scope_with_prior_failed_or_in_progress_status_fails(self):
        self.refresh_all(github(5001))
        with self.assertRaises(ValueError):
            self.refresh(self.STALE, github(5002), mode="hard")
        self.assertEqual(self.status(self.STALE)["status"], "failed")
        for scope in reporter.SCOPES[:-1]:
            self.refresh(scope, github(5003))
        code, text = self.report(github(5003))
        self.assertNotEqual(code, 0)
        self.assertIn("belongs to invocation 'github:5002:1'", text)
        # A current-run refresh that died mid-flight leaves in-progress.
        scope = {"id": self.STALE, "region_id": "fort-bragg-point-arena"}
        enc._write_run_status(scope, self.directory / (self.STALE + ".geojson"),
                              "in-progress", invocation="github:5003:1")
        code, text = self.report(github(5003))
        self.assertNotEqual(code, 0)
        self.assertIn("status is in-progress", text)

    def test_replaced_artifact_bytes_fail_closed(self):
        self.refresh_all(github(6001))
        snapshot_path = self.directory / (self.STALE + ".geojson")
        snapshot = json.loads(snapshot_path.read_text())
        snapshot["features"] = [{"geometry": {"type": "Point", "coordinates": [0, 0]}}]
        snapshot_path.write_text(json.dumps(snapshot))  # same scope and checked_at
        code, text = self.report(github(6001))
        self.assertNotEqual(code, 0)
        self.assertIn("does not match the status SHA-256", text)

    def test_missing_or_corrupt_artifact_fails_closed(self):
        self.refresh_all(github(7001))
        (self.directory / (self.STALE + ".geojson")).unlink()
        code, text = self.report(github(7001))
        self.assertNotEqual(code, 0)
        self.assertIn("without its artifact", text)
        corrupt = b"{not json"
        (self.directory / (self.STALE + ".geojson")).write_bytes(corrupt)
        status = self.status(self.STALE)
        status["artifact_sha256"] = hashlib.sha256(corrupt).hexdigest()
        self.status_path(self.STALE).write_text(json.dumps(status))
        code, text = self.report(github(7001))
        self.assertNotEqual(code, 0)
        self.assertIn("corrupt artifact", text)
        status.pop("artifact_sha256")
        self.status_path(self.STALE).write_text(json.dumps(status))
        code, text = self.report(github(7001))
        self.assertNotEqual(code, 0)
        self.assertIn("no valid artifact_sha256", text)

    def test_corrupt_or_wrong_scope_status_fails_closed(self):
        self.refresh_all(github(7101))
        self.status_path(self.STALE).write_text("[]")
        code, text = self.report(github(7101))
        self.assertNotEqual(code, 0)
        self.assertIn("corrupt current invocation status", text)
        self.status_path(self.STALE).write_text("{oops")
        self.assertNotEqual(self.report(github(7101))[0], 0)

    def test_reporter_without_expected_identity_fails_closed(self):
        for scope in reporter.SCOPES:
            self.refresh(scope, {}, args=("--invocation", "local-8001"))
        code, text = self.report({})
        self.assertNotEqual(code, 0)
        self.assertIn("No expected invocation identity", text)
        with self.assertRaises(ValueError):
            reporter.report_bound(self.directory, invocation=None)

    def test_refresh_without_identity_never_satisfies_a_reporter(self):
        for scope in reporter.SCOPES:
            self.refresh(scope, {})
        self.assertIsNone(self.status(self.STALE)["invocation"])
        code, text = self.report({}, args=("--invocation", "local-anything"))
        self.assertNotEqual(code, 0)
        self.assertIn("belongs to invocation None", text)

    def test_local_equivalent_flag_and_environment(self):
        for scope in reporter.SCOPES:
            self.refresh(scope, {"ENC_INVOCATION_ID": "local-20261019T120000Z"})
        self.assertEqual(self.report({}, args=("--invocation", "local-20261019T120000Z"))[0], 0)
        self.assertEqual(self.report({"ENC_INVOCATION_ID": "local-20261019T120000Z"})[0], 0)
        self.assertNotEqual(self.report({"ENC_INVOCATION_ID": "local-20261019T130000Z"})[0], 0)

    def test_invalid_identity_rejected_before_any_request(self):
        with patch.object(enc.urllib.request, "urlopen") as opened, \
             identity_env(), patch("sys.argv", ["refresh_enc_hazards.py", "--scope", self.STALE,
                 "--output", str(self.directory / "x.geojson"), "--invocation", "bad id/../x"]):
            with self.assertRaisesRegex(ValueError, "Invalid ENC invocation identity"):
                enc.main()
        opened.assert_not_called()
        self.assertFalse(self.status_path(self.STALE).exists())


class EncInvocationResolverParityTests(unittest.TestCase):
    CASES = (
        ((None, {}), None),
        ((None, {"GITHUB_RUN_ID": "9"}), None),
        ((None, {"GITHUB_RUN_ID": "9", "GITHUB_RUN_ATTEMPT": "2"}), "github:9:2"),
        ((None, {"ENC_INVOCATION_ID": "local-1", "GITHUB_RUN_ID": "9", "GITHUB_RUN_ATTEMPT": "2"}), "local-1"),
        ((None, {"ENC_INVOCATION_ID": "", "GITHUB_RUN_ID": "9", "GITHUB_RUN_ATTEMPT": "2"}), "github:9:2"),
        (("cli-1", {"ENC_INVOCATION_ID": "local-1"}), "cli-1"),
    )

    def test_refresh_and_reporter_resolve_identically(self):
        for (explicit, environ), expected in self.CASES:
            with self.subTest(explicit=explicit, environ=environ):
                self.assertEqual(enc.resolve_invocation(explicit, environ), expected)
                self.assertEqual(reporter.resolve_invocation(explicit, environ), expected)
        for bad in ("", "has space", "../x", "x" * 201):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    enc.resolve_invocation(bad, {})
                with self.assertRaises(ValueError):
                    reporter.resolve_invocation(bad, {})


if __name__ == "__main__":
    unittest.main()
