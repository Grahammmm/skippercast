"""NDBC archive decode: every gzip member is decoded or the archive is refused."""
import gzip
import hashlib
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

from skippercast.http import FakeSession
from skippercast.pipeline import ndbc_history as nh

HEAD = b"#YY MM DD hh mm WVHT WTMP\n2025 01 01 00 00 1.0 10\n"
ROW2 = b"2025 01 01 01 00 2.0 11\n"
WHOLE = HEAD + ROW2
URL = nh.annual_url("46215", 2025)


def gz(data):
    return gzip.compress(data, mtime=0)


class GzipMemberTests(TestCase):
    def test_all_members_kept(self):
        self.assertEqual(nh.decode(gz(HEAD) + gz(ROW2)).encode(), WHOLE)
        self.assertEqual(nh.decode(gz(HEAD) + gz(b"") + gz(ROW2[:10]) + gz(ROW2[10:])).encode(), WHOLE)
        self.assertEqual(nh.decode(gz(b"") + gz(WHOLE)).encode(), WHOLE)
        self.assertEqual(nh.decode(gz(WHOLE)).encode(), WHOLE)
        self.assertEqual(nh.decode(b"abc"), "abc")
        self.assertEqual(nh.decode(b""), "")

    def test_aggregate_limit(self):
        with patch.object(nh, "MAX_DECODED", 10):
            self.assertEqual(nh.decode(gz(b"a" * 4) + gz(b"b" * 6)), "a" * 4 + "b" * 6)
            with self.assertRaises(ValueError):
                nh.decode(gz(b"a" * 4) + gz(b"b" * 7))
            with self.assertRaises(ValueError):
                nh.decode(gz(b"a" * 10) + gz(b"b"))
            with self.assertRaises(ValueError):
                nh.decode(gz(b"a") + gz(b"b" * 100_000))

    def test_later_damage_never_returns_prefix(self):
        second = gz(ROW2)
        bad_crc = second[:-8] + bytes([second[-8] ^ 1]) + second[-7:]
        cases = {"crc": gz(HEAD) + bad_crc, "header": gz(HEAD) + second[:5], "body": gz(HEAD) + second[:-9],
                 "trailer": gz(HEAD) + second[:-3], "junk": gz(HEAD) + b"garbage",
                 "after-empty": gz(b"") + bad_crc, "pad-junk": gz(HEAD) + b"\0\0junk"}
        for name, body in cases.items():
            with self.subTest(name), self.assertRaises(ValueError):
                nh.decode(body)

    def test_padding_and_utf8(self):
        self.assertEqual(nh.decode(gz(HEAD) + b"\0" * 7).encode(), HEAD)
        self.assertEqual(nh.decode(gz(HEAD) + gz(ROW2) + b"\0" * 7).encode(), WHOLE)
        raw = "é".encode()
        self.assertEqual(nh.decode(gz(raw[:1]) + gz(raw[1:])), "é")
        with self.assertRaises(ValueError):
            nh.decode(gz(b"\xff\xfe"))

    def _ctx(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        return Path(tmp.name), {"records": {}}

    def test_fresh_receipt_complete_or_error(self):
        cache, checkpoint = self._ctx()
        body = gz(HEAD) + gz(ROW2)
        text, source = nh.annual_receipt(FakeSession({URL: body}), cache, checkpoint, "46215", 2025)
        sha = hashlib.sha256(body).hexdigest()
        self.assertEqual(text.encode(), WHOLE)
        self.assertEqual((source["sha256"], source["decodedBytes"], source["bytes"]), (sha, len(WHOLE), len(body)))
        self.assertEqual((cache / source["objectKey"]).read_bytes(), body)

        cache, checkpoint = self._ctx()
        with self.assertRaises(ValueError):
            nh.annual_receipt(FakeSession({URL: gz(HEAD) + b"garbage"}), cache, checkpoint, "46215", 2025)
        record = checkpoint["records"]["46215:annual:2025"]
        self.assertEqual(record["outcome"], "error")
        self.assertNotIn("objectKey", record)
        self.assertEqual(list(cache.rglob("*.bin")), [])

    def test_cached_archive_is_redecoded_completely(self):
        for body, ok in ((gz(HEAD) + gz(ROW2), True), (gz(HEAD) + b"garbage", False)):
            with self.subTest(ok=ok):
                cache, checkpoint = self._ctx()
                sha = hashlib.sha256(body).hexdigest()
                key = f"ndbc/stdmet/46215/2025/{sha}.bin"
                (cache / key).parent.mkdir(parents=True)
                (cache / key).write_bytes(body)
                saved = {"url": URL, "role": "annual", "year": 2025, "outcome": "ok", "sha256": sha, "objectKey": key}
                checkpoint["records"]["46215:annual:2025"] = dict(saved)
                session = FakeSession({})
                if ok:
                    text, source = nh.annual_receipt(session, cache, checkpoint, "46215", 2025)
                    self.assertEqual(text.encode(), WHOLE)
                    self.assertEqual(source, saved)
                else:
                    with self.assertRaises(ValueError):
                        nh.annual_receipt(session, cache, checkpoint, "46215", 2025)
                    self.assertEqual(checkpoint["records"]["46215:annual:2025"], saved)
                self.assertEqual((cache / key).read_bytes(), body)
