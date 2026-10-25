"""SP-10-v1: identity-bound annual receipts, exclusively synthetic and offline.

Ordinary unittest/pytest discovery has no process-global safety hooks or environment
mutation. The acceptance child installs its own pre-import offline boundary.
"""
from contextlib import ExitStack
import gzip
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/sp106_history_receipt"
URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/46215h2025.txt.gz"
OTHER_URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/46028h2025.txt.gz"
STATION, YEAR, RECORD = "46215", 2025, "46215:annual:2025"


class RegressionTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(__file__).resolve().parents[2]
        self.stack.enter_context(patch.dict(os.environ, {
            "SKIPPERCAST_ROOT": str(root), "SKIPPERCAST_HTTP_CACHE": "",
        }))
        # No import-time filesystem API calls; every test owns its fresh cache.
        from skippercast.pipeline import ndbc_history
        from skippercast.http import FakeSession
        self.nh, self.FakeSession = ndbc_history, FakeSession
        self.assertEqual(Path(ndbc_history.__file__).resolve(),
                         root / "src/skippercast/pipeline/ndbc_history.py")
        self.tmp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.cache = Path(self.tmp)
        self.body = (FIXTURES / "cached.txt").read_bytes()
        self.refill = (FIXTURES / "refill.txt").read_bytes()
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.other_digest = hashlib.sha256(self.refill).hexdigest()
        self.saved = {
            "url": URL, "role": "annual", "year": YEAR, "outcome": "ok",
            "fetchedAt": "2026-01-01T00:00:00.000Z", "sha256": self.digest,
            "bytes": len(self.body), "decodedBytes": len(self.body),
            "objectKey": f"ndbc/stdmet/{STATION}/{YEAR}/{self.digest}.bin",
        }
        self.original = self.cache / self.saved["objectKey"]
        self.original.parent.mkdir(parents=True)
        self.original.write_bytes(self.body)
        self.checkpoint = {"schemaVersion": 1, "regionId": "synthetic-example",
                           "records": {RECORD: self.saved.copy()}}

    def session(self, body=None):
        return self.FakeSession({URL: self.refill if body is None else body})

    def call(self, session, **options):
        return self.nh.annual_receipt(session, self.cache, self.checkpoint,
                                      STATION, YEAR, **options)

    def assert_request(self, session):
        self.assertEqual(session.calls, [("GET", URL, {
            "timeout": 15, "max_bytes": 2_000_000,
            "allowed_hosts": ["www.ndbc.noaa.gov"],
            "allowed_prefixes": ["https://www.ndbc.noaa.gov/"],
        })])

    def assert_refill(self, session, returned, body=None):
        body = self.refill if body is None else body
        text, receipt = returned
        digest = hashlib.sha256(body).hexdigest()
        self.assert_request(session)
        self.assertEqual(text, self.nh.decode(body))
        self.assertEqual({k: receipt[k] for k in ("url", "role", "year", "outcome", "sha256", "objectKey")}, {
            "url": URL, "role": "annual", "year": YEAR, "outcome": "ok",
            "sha256": digest, "objectKey": f"ndbc/stdmet/{STATION}/{YEAR}/{digest}.bin",
        })
        self.assertIs(type(receipt["year"]), int)
        self.assertEqual((self.cache / receipt["objectKey"]).read_bytes(), body)
        self.assertEqual(self.checkpoint["records"][RECORD], receipt)

    def test_primary_regression(self):
        # Hash-valid body and producer-shaped receipt, but bound to another station.
        wrong = {**self.saved, "url": OTHER_URL,
                 "objectKey": f"ndbc/stdmet/46028/{YEAR}/{self.digest}.bin"}
        path = self.cache / wrong["objectKey"]
        path.parent.mkdir(parents=True)
        path.write_bytes(self.body)
        self.checkpoint["records"][RECORD] = wrong
        session = self.session()
        observed_exception, returned = None, None
        try:
            returned = self.call(session)
        except (TypeError, KeyError) as error:
            # Known metadata exceptions are observed data, never an accepted
            # baseline harness error. An offline guard refusal is NOT caught.
            observed_exception = f"{type(error).__name__}: {error}"
        self.assertIsNone(observed_exception, observed_exception)
        self.assert_refill(session, returned)
        self.assertEqual(path.read_bytes(), self.body)
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_healthy_control(self):
        session = self.FakeSession({})
        text, receipt = self.call(session)
        self.assertEqual(text, self.body.decode())
        self.assertIs(receipt, self.checkpoint["records"][RECORD])
        self.assertEqual(receipt, self.saved)
        self.assertEqual(session.calls, [])
        self.assertEqual(self.original.read_bytes(), self.body)

    def check_metadata_miss(self, saved):
        # For valid-shaped changed object keys, bytes at that exact key also
        # retain valid integrity. This isolates station/year/key identity.
        if isinstance(saved, dict):
            key = saved.get("objectKey")
            if isinstance(key, str) and self.nh.KEY.fullmatch(key):
                target = self.cache / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(self.body)
        self.checkpoint["records"][RECORD] = saved
        session = self.session()
        try:
            returned = self.call(session)
        except (TypeError, KeyError) as error:
            self.fail(f"Malformed metadata caused incidental {type(error).__name__}: {error}")
        self.assert_refill(session, returned)
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_missing_body_refills(self):
        # The missing object never existed; no deletion of existing archives.
        empty_cache = self.cache / "fresh-empty-cache"
        empty_cache.mkdir()
        session = self.session()
        returned = self.nh.annual_receipt(session, empty_cache, self.checkpoint, STATION, YEAR)
        self.assert_request(session)
        self.assertEqual(returned[0], self.refill.decode())
        self.assertEqual((empty_cache / returned[1]["objectKey"]).read_bytes(), self.refill)
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_corrupt_body_refills(self):
        self.original.write_bytes(b"synthetic corruption")
        session = self.session()
        self.assert_refill(session, self.call(session))
        self.assertEqual(self.original.read_bytes(), b"synthetic corruption")

    def test_missing_body_failure_records_error(self):
        empty_cache = self.cache / "fresh-missing-failure"
        empty_cache.mkdir()
        session = self.FakeSession({URL: OSError("synthetic missing-body failure")})
        with self.assertRaisesRegex(OSError, "synthetic missing-body failure"):
            self.nh.annual_receipt(session, empty_cache, self.checkpoint, STATION, YEAR)
        self.assert_request(session)
        self.assertEqual(self.checkpoint["records"][RECORD]["outcome"], "error")
        self.assertEqual(list(empty_cache.iterdir()), [])
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_corrupt_body_failure_records_error(self):
        self.original.write_bytes(b"synthetic corruption")
        session = self.FakeSession({URL: OSError("synthetic corrupt-body failure")})
        with self.assertRaisesRegex(OSError, "synthetic corrupt-body failure"):
            self.call(session)
        self.assert_request(session)
        self.assertEqual(self.checkpoint["records"][RECORD]["outcome"], "error")
        self.assertEqual(self.original.read_bytes(), b"synthetic corruption")

    def test_revalidate_fetches(self):
        session = self.session()
        self.assert_refill(session, self.call(session, revalidate=True))
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_failure_never_returns_mismatched_bytes(self):
        self.checkpoint["records"][RECORD]["url"] = OTHER_URL
        session = self.FakeSession({URL: OSError("synthetic fetch failure")})
        with self.assertRaisesRegex(OSError, "synthetic fetch failure"):
            self.call(session)
        self.assert_request(session)
        receipt = self.checkpoint["records"][RECORD]
        self.assertEqual({k: receipt[k] for k in ("url", "role", "year", "outcome", "error")}, {
            "url": URL, "role": "annual", "year": YEAR, "outcome": "error",
            "error": "synthetic fetch failure",
        })
        self.assertNotIn("objectKey", receipt)
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_revalidate_failure_records_error(self):
        session = self.FakeSession({URL: OSError("synthetic revalidate failure")})
        with self.assertRaisesRegex(OSError, "synthetic revalidate failure"):
            self.call(session, revalidate=True)
        self.assert_request(session)
        self.assertEqual(self.checkpoint["records"][RECORD]["outcome"], "error")
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_refill_checkpoint_restart_is_zero_request(self):
        self.checkpoint["records"][RECORD]["role"] = "recent"
        session = self.session()
        returned = self.call(session)
        self.assert_refill(session, returned)
        checkpoint_path = self.cache / "synthetic-checkpoint.json"
        self.nh.atomic(checkpoint_path, self.checkpoint, compact=False)
        self.checkpoint = json.loads(checkpoint_path.read_text())
        restart = self.FakeSession({})
        second = self.call(restart)
        self.assertEqual(second, returned)
        self.assertIs(second[1], self.checkpoint["records"][RECORD])
        self.assertEqual(restart.calls, [])
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_gzip_fetch_and_cache_decode_unchanged(self):
        compressed = gzip.compress(self.refill, mtime=0)
        session = self.session(compressed)
        returned = self.call(session, revalidate=True)
        self.assert_refill(session, returned, compressed)
        self.assertEqual(returned[1]["bytes"], len(compressed))
        self.assertEqual(returned[1]["decodedBytes"], len(self.refill))
        self.assertEqual(self.call(self.FakeSession({})), returned)

    def test_bad_fetched_gzip_records_error(self):
        session = self.session(b"\x1f\x8b\x08\x00garbage")
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.call(session, revalidate=True)
        self.assert_request(session)
        self.assertEqual(self.checkpoint["records"][RECORD]["outcome"], "error")
        self.assertEqual(self.original.read_bytes(), self.body)

    def test_integrity_valid_bad_cached_decode_preserves_error_behavior(self):
        body = b"\x1f\x8b\x08\x00garbage"
        digest = hashlib.sha256(body).hexdigest()
        saved = {**self.saved, "sha256": digest,
                 "objectKey": f"ndbc/stdmet/{STATION}/{YEAR}/{digest}.bin"}
        target = self.cache / saved["objectKey"]
        target.write_bytes(body)
        self.checkpoint["records"][RECORD] = saved
        session = self.session()
        with self.assertRaisesRegex(ValueError, "truncated"):
            self.call(session)
        self.assertEqual(session.calls, [])
        self.assertEqual(target.read_bytes(), body)
        self.assertEqual(self.checkpoint["records"][RECORD], saved)


def _metadata_test(field, value, missing=False):
    def test(self):
        saved = self.saved.copy()
        if missing:
            saved.pop(field)
        else:
            saved[field] = (value.format(digest=self.digest, other_digest=self.other_digest,
                                        upper_digest=self.digest.upper())
                            if isinstance(value, str) else value)
        self.check_metadata_miss(saved)
    return test


def _nonobject_test(value):
    def test(self):
        self.check_metadata_miss(value)
    return test


# Committed table bytes are shared unchanged by the historical pair and final
# focused run; each deciding gate has its own named unittest identity.
_cases = json.loads((FIXTURES / "metadata.json").read_text())
for _name, _field, _value in _cases["mutations"]:
    setattr(RegressionTests, "test_metadata_" + _name, _metadata_test(_field, _value))
for _field in _cases["missing"]:
    setattr(RegressionTests, "test_metadata_missing_" + _field, _metadata_test(_field, None, True))
for _name, _value in _cases["nonobjects"]:
    setattr(RegressionTests, "test_metadata_receipt_" + _name, _nonobject_test(_value))
