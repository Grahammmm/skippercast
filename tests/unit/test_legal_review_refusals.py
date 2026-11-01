"""A legal-review ZIP that cannot be verified is refused by name, never with a traceback."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import verify_legal_review_artifact as verifier
from skippercast.pipeline.parsers import watch_content
from skippercast.pipeline.regulations import content_hash

HTML = "<html><body>Official source <a href='https://example.org/rules'>Rules</a></body></html>"
REGISTRY = {"sources": {"rules-test": {"url": "https://example.org/rules", "normalization": "text-and-links-v3"}}}


class LegalReviewRefusalTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "legal.zip"
        self.packet = {"jurisdiction_id": "test-coast", "collected_at": "2026-09-24T14:00:00Z",
                       "rules_content_sha256": content_hash(REGISTRY),
                       "sources": {"rules-test": {"status": "ok", "url": "https://example.org/rules",
                                                  "data": {"normalization": "text-and-links-v3",
                                                           "content_sha256": hashlib.sha256(watch_content(HTML).encode()).hexdigest()}}}}
        files = patch.object(verifier, "jurisdiction_files", return_value=({"id": "test-coast"}, REGISTRY, None))
        files.start()
        self.addCleanup(files.stop)

    def write_zip(self, members=None, **replace):
        content = {"packet.json": json.dumps(self.packet), "coverage.json": json.dumps({"jurisdiction_id": "test-coast"}),
                   "rules-test.html": HTML, **(members or {})}
        with zipfile.ZipFile(self.archive, "w") as zipped:
            for name, body in content.items():
                if name not in replace.get("drop", ()):
                    zipped.writestr(name, body)

    def refused(self, message):
        with self.assertRaises(ValueError) as caught:
            verifier.verify(self.archive, "test-coast")
        self.assertEqual(str(caught.exception), message)

    def run_cli(self, *extra):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["verify_legal_review_artifact.py", str(self.archive), "--jurisdiction", "test-coast", *extra]
        with patch("sys.argv", argv), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                verifier.main()
                code = 0
            except SystemExit as exit_:
                code = exit_.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_missing_member_is_named(self):
        self.write_zip(drop=("rules-test.html",))
        self.refused("Missing source file: rules-test.html")

    def test_non_utf8_text_is_named(self):
        self.write_zip({"rules-test.html": b"\xff\xfe<html>"})
        self.refused("Unreadable text (not UTF-8): rules-test.html")

    def test_not_a_zip(self):
        self.archive.write_bytes(b"not a zip")
        self.refused("Not a ZIP archive")

    def test_bad_packet_and_coverage(self):
        for name, body, message in (("packet.json", "{", "packet.json is not valid JSON"),
                                    ("packet.json", b"\xff{}", "packet.json is not valid JSON"),
                                    ("packet.json", "[]", "packet.json is not a JSON object"),
                                    ("coverage.json", "5", "coverage.json is not a JSON object"),
                                    ("coverage.json", "null", "coverage.json is not a JSON object")):
            with self.subTest(name=name, body=body):
                self.write_zip({name: body})
                self.refused(message)

    def test_record_shape(self):
        self.packet["sources"]["rules-test"] = "ok"
        self.write_zip()
        self.refused("Unusable source or URL mismatch: rules-test")
        self.packet["sources"]["rules-test"] = {"status": "ok", "url": "https://example.org/rules", "data": ["x"]}
        self.write_zip()
        self.refused("Normalizer mismatch: rules-test")
        self.packet["sources"] = ["rules-test"]
        self.write_zip()
        self.refused("Source inventory mismatch")

    def test_collected_at_required(self):
        for value in (None, "", 5):
            with self.subTest(collected_at=value):
                self.packet["collected_at"] = value
                if value is None:
                    del self.packet["collected_at"]
                self.write_zip()
                self.refused("packet.json collected_at is missing")

    def test_existing_messages_still_win(self):
        self.write_zip({"rules-test.html": HTML.replace("Official", "Altered")})
        self.refused("Source fingerprint mismatch: rules-test")
        self.write_zip(drop=("coverage.json",))
        self.refused("Legal review packet and coverage are required")

    def test_extra_member_accepted(self):
        self.write_zip({"notes.txt": "reviewer notes"})
        self.assertEqual(verifier.verify(self.archive, "test-coast")["verified_source_count"], 1)

    def test_cli_refusal_keeps_existing_receipt(self):
        self.write_zip(drop=("rules-test.html",))
        output = self.root / "verification.json"
        output.write_bytes(b'{"old": true}\n')
        code, stdout, stderr = self.run_cli("--output", str(output))
        self.assertEqual(code, 1)
        self.assertTrue(stderr.startswith("Legal review artifact refused: Missing source file"), stderr)
        self.assertNotIn("Traceback", stderr)
        self.assertEqual(stdout, "")
        self.assertEqual(output.read_bytes(), b'{"old": true}\n')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), ["legal.zip", "verification.json"])

    def test_cli_missing_archive_refused(self):
        code, _, stderr = self.run_cli()
        self.assertEqual(code, 1)
        self.assertTrue(stderr.startswith("Legal review artifact refused: "), stderr)
        self.assertNotIn("Traceback", stderr)

    def test_cli_success_writes_whole_receipt(self):
        self.write_zip()
        output = self.root / "sub" / "verification.json"
        output.parent.mkdir()
        output.write_text("stale receipt")
        code, stdout, stderr = self.run_cli("--output", str(output))
        self.assertEqual((code, stderr), (0, ""))
        receipt = json.loads(stdout)
        self.assertEqual(json.loads(output.read_text()), receipt)
        self.assertEqual(receipt["verified_source_count"], 1)
        self.assertEqual([p.name for p in output.parent.iterdir()], ["verification.json"])

    def test_cli_write_failure_removes_temp(self):
        self.write_zip()
        output = self.root / "sub" / "verification.json"
        with patch.object(verifier.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.run_cli("--output", str(output))
        self.assertEqual(list(output.parent.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
