"""A damaged, encrypted or unsupported legal-review ZIP member is refused by name; the hash binds the verified bytes."""

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import verify_legal_review_artifact as verifier
from skippercast.pipeline.regulations import content_hash

PDF = b"%PDF-1.4 official rules " * 20
REGISTRY = {"sources": {"rules-test": {"url": "https://example.org/rules.pdf", "normalization": "pdf-bytes-v1"}}}


class DamagedLegalArchiveTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "legal.zip"
        files = patch.object(verifier, "jurisdiction_files", return_value=({"id": "test-coast"}, REGISTRY, None))
        files.start()
        self.addCleanup(files.stop)

    def zip_bytes(self):
        packet = {"jurisdiction_id": "test-coast", "collected_at": "2026-09-24T14:00:00Z",
                  "rules_content_sha256": content_hash(REGISTRY), "padding": "x" * 400,
                  "sources": {"rules-test": {"status": "ok", "url": "https://example.org/rules.pdf",
                                             "data": {"normalization": "pdf-bytes-v1",
                                                      "content_sha256": hashlib.sha256(PDF).hexdigest()}}}}
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as zipped:
            zipped.writestr("packet.json", json.dumps(packet), compress_type=zipfile.ZIP_DEFLATED)
            zipped.writestr("coverage.json", json.dumps({"jurisdiction_id": "test-coast"}))
            zipped.writestr("rules-test.pdf", PDF)
            zipped.writestr("notes.txt", "reviewer notes")
        return bytearray(buffer.getvalue())

    @staticmethod
    def central(data, name):
        """Offset of the central-directory header for member ``name``."""
        at = data.find(b"PK\x01\x02")
        while at >= 0:
            size = struct.unpack_from("<H", data, at + 28)[0]
            if bytes(data[at + 46:at + 46 + size]) == name.encode():
                return at
            at = data.find(b"PK\x01\x02", at + 1)
        raise AssertionError(name)

    @staticmethod
    def local(data, name):
        with zipfile.ZipFile(io.BytesIO(bytes(data))) as zipped:
            return zipped.getinfo(name).header_offset

    def refused(self, message):
        with self.assertRaises(ValueError) as caught:
            verifier.verify(self.archive, "test-coast")
        self.assertEqual(str(caught.exception), message)

    def run_cli(self, output):
        stdout, stderr = io.StringIO(), io.StringIO()
        argv = ["verify_legal_review_artifact.py", str(self.archive), "--jurisdiction", "test-coast", "--output", str(output)]
        with patch("sys.argv", argv), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            try:
                verifier.main()
                code = 0
            except SystemExit as exit_:
                code = exit_.code
        return code, stdout.getvalue(), stderr.getvalue()

    def test_corrupt_deflated_packet_refused_by_name_without_traceback(self):
        data = self.zip_bytes()
        head = self.local(data, "packet.json")
        name_len, extra_len = struct.unpack_from("<HH", data, head + 26)
        start = head + 30 + name_len + extra_len
        compressed = struct.unpack_from("<I", data, self.central(data, "packet.json") + 20)[0]
        data[start + compressed // 2] ^= 0xFF
        self.archive.write_bytes(data)
        output = self.root / "verification.json"
        code, stdout, stderr = self.run_cli(output)
        self.assertEqual((code, stdout), (1, ""))
        self.assertEqual(stderr, "Legal review artifact refused: unreadable archive member packet.json\n")
        self.assertNotIn("Traceback", stderr)
        self.assertFalse(output.exists())

    def test_wrong_crc_on_intact_pdf_refused(self):
        data = self.zip_bytes()
        crc_at = self.central(data, "rules-test.pdf") + 16
        struct.pack_into("<I", data, crc_at, struct.unpack_from("<I", data, crc_at)[0] ^ 1)
        self.archive.write_bytes(data)
        self.refused("unreadable archive member rules-test.pdf")

    def test_encrypted_flag_refused_up_front(self):
        for name in ("notes.txt", "rules-test.pdf"):
            with self.subTest(name=name):
                data = self.zip_bytes()
                data[self.central(data, name) + 8] |= 0x1
                self.archive.write_bytes(data)
                self.refused(f"encrypted archive member {name}")

    def test_unsupported_compression_method_refused(self):
        data = self.zip_bytes()
        struct.pack_into("<H", data, self.central(data, "rules-test.pdf") + 10, 99)
        struct.pack_into("<H", data, self.local(data, "rules-test.pdf") + 8, 99)
        self.archive.write_bytes(data)
        self.refused("unreadable archive member rules-test.pdf")

    def test_oversized_file_refused_before_zip_parsing(self):
        self.archive.write_bytes(self.zip_bytes())
        self.assertGreater(self.archive.stat().st_size, 1024)
        with patch.object(verifier, "MAX_ARCHIVE_BYTES", 1024), \
                patch.object(verifier.zipfile, "ZipFile", side_effect=AssertionError("opened as ZIP")):
            self.refused("Archive exceeds the bounded review size")
            small = os.stat_result((stat.S_IFREG | 0o644, 0, 0, 1, 0, 0, 10, 0, 0, 0))
            with patch.object(verifier.os, "stat", return_value=small):
                self.refused("Archive exceeds the bounded review size")

    def test_hash_is_of_the_bytes_verified_with_no_second_read(self):
        data = bytes(self.zip_bytes())
        self.archive.write_bytes(data)
        with patch.object(Path, "read_bytes", side_effect=AssertionError("second read")):
            receipt = verifier.verify(self.archive, "test-coast")
        self.assertEqual(receipt["archive_sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(receipt["source_ids"], ["rules-test"])

    def test_directory_or_fifo_is_not_a_regular_file(self):
        fifo = self.root / "pipe.zip"
        os.mkfifo(fifo)
        for path in (self.root, fifo):
            with self.subTest(path=path.name):
                self.archive = path
                self.refused("Not a regular file")


if __name__ == "__main__":
    unittest.main()
