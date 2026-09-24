"""The cloud packet is evidence only when its identity and bytes still match."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from verify_legal_review_artifact import verify  # noqa: E402
from skippercast.pipeline.parsers import watch_content  # noqa: E402
from skippercast.pipeline.regulations import content_hash  # noqa: E402


class LegalReviewArtifactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.archive = Path(self.temp.name) / "legal.zip"
        self.html = "<html><body>Official source <a href='https://example.org/rules'>Rules</a></body></html>"
        self.registry = {"sources": {"rules-test": {"url": "https://example.org/rules", "normalization": "text-and-links-v3"}}}
        self.jurisdiction = {"id": "test-coast"}
        self.packet = {"jurisdiction_id": "test-coast", "collected_at": "2026-09-24T14:00:00Z",
                       "rules_content_sha256": content_hash(self.registry),
                       "sources": {"rules-test": {"status": "ok", "url": "https://example.org/rules",
                                                  "data": {"normalization": "text-and-links-v3",
                                                           "content_sha256": hashlib.sha256(watch_content(self.html).encode()).hexdigest()}}}}

    def write_zip(self, html=None, extra=None):
        with zipfile.ZipFile(self.archive, "w") as zipped:
            zipped.writestr("packet.json", json.dumps(self.packet))
            zipped.writestr("coverage.json", json.dumps({"jurisdiction_id": "test-coast"}))
            zipped.writestr("rules-test.html", self.html if html is None else html)
            if extra:
                zipped.writestr(*extra)

    def check(self):
        with patch("verify_legal_review_artifact.jurisdiction_files", return_value=(self.jurisdiction, self.registry, None)):
            return verify(self.archive, "test-coast")

    def test_matching_source_passes(self):
        self.write_zip()
        self.assertEqual(self.check()["verified_source_count"], 1)

    def test_changed_source_fails(self):
        self.write_zip(html=self.html.replace("Official", "Altered"))
        with self.assertRaisesRegex(ValueError, "fingerprint mismatch"):
            self.check()

    def test_path_traversal_fails(self):
        self.write_zip(extra=("../other-file", "untrusted"))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            self.check()

    def test_wrong_jurisdiction_fails(self):
        self.write_zip()
        self.packet["jurisdiction_id"] = "another-coast"
        self.write_zip()
        with self.assertRaisesRegex(ValueError, "Jurisdiction mismatch"):
            self.check()


if __name__ == "__main__":
    unittest.main()
