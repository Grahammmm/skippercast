"""A partial HTTP documentation response (206) is accessible but never a complete document."""

import copy
import gzip
import hashlib
import unittest
from unittest import mock

from skippercast import http
from skippercast.platform import source_audit

CAP = source_audit.SAMPLE_BYTES
STAMP = "2026-01-01T00:00:00Z"
URL = "https://documentation.example.org/synthetic"
SOURCE = {"id": "synthetic", "documentation_url": URL}


def response(status, size, headers=(), url=URL, body=None):
    body = b"x" * size if body is None else body
    receipt = http.Receipt(url=url, status=status, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(),
                           truncated=len(body) > CAP)
    return http.Response(url=url, final_url=url, status=status, headers=http.Headers(headers), body=body,
                         receipt=receipt)


class RecordingSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        if isinstance(self.result, dict):
            return self.result[url]
        return self.result


def probe(result, source=SOURCE):
    session = RecordingSession(result)
    with mock.patch.object(source_audit, "stamp", lambda: STAMP), \
            mock.patch.object(source_audit.http, "default_session", side_effect=AssertionError("transport fallback")):
        return source_audit.probe(source, session=session), session


class PartialContent(unittest.TestCase):
    def test_short_single_range_is_not_full_document(self):
        r = response(206, 20, [("Content-Range", "bytes 0-19/100")])
        row, session = probe(r)
        self.assertIs(row["body_complete"], False)
        self.assertEqual(row["status"], "accessible")
        self.assertEqual(row["http_status"], 206)
        self.assertEqual(row["sampled_bytes"], 20)
        self.assertEqual(row["sha256"], r.receipt.sha256)
        self.assertEqual(row["final_url"], URL)
        self.assertIsNone(row["source_issue_time"])
        self.assertEqual(row["checked_at"], STAMP)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0][1]["max_bytes"], CAP)
        self.assertIs(session.calls[0][1]["truncate"], True)

    def test_partial_status_does_not_depend_on_headers(self):
        cases = {
            "no content-range": [],
            "header case": [("CONTENT-RANGE", "bytes 0-19/100")],
            "multipart": [("Content-Type", "multipart/byteranges; boundary=synthetic")],
            "range spans whole resource": [("content-range", "bytes 0-19/20"), ("Content-Length", "20")],
        }
        for name, headers in cases.items():
            with self.subTest(name):
                row, _ = probe(response(206, 20, headers))
                self.assertIs(row["body_complete"], False)
                self.assertEqual(row["status"], "accessible")
                self.assertEqual(row["http_status"], 206)


class OrdinarySampling(unittest.TestCase):
    def test_ordinary_cap_boundaries_remain_exact(self):
        for size, complete in ((CAP - 1, True), (CAP, True), (CAP + 1, False)):
            with self.subTest(size=size):
                r = response(200, size)
                row, _ = probe(r)
                self.assertIs(row["body_complete"], complete)
                self.assertEqual(row["sampled_bytes"], size)
                self.assertEqual(row["sha256"], r.receipt.sha256)
                self.assertEqual(row["status"], "accessible")
                self.assertEqual(row["http_status"], 200)

    def test_oversized_partial_and_empty_response_preserve_error_policy(self):
        row, _ = probe(response(206, CAP + 1))
        self.assertEqual(row["status"], "accessible")
        self.assertIs(row["body_complete"], False)
        self.assertEqual(row["sampled_bytes"], CAP + 1)
        for body in (b"", b"  \n"):
            with self.subTest(body=body):
                row, _ = probe(response(206, 0, body=body))
                self.assertEqual(row["status"], "unavailable")
                self.assertEqual(row["error"], "ValueError: Empty documentation response")
                self.assertIsNot(row["body_complete"], True)

    def test_complete_gzip_is_judged_on_the_decoded_document(self):
        # Contract: "empty" is a property of the document, not of the transport bytes. An empty
        # document is 20 gzip bytes, so a check on the raw body credits an unreachable source.
        # Bug caught: judging len/strip of the compressed body only (gzip framing is never blank).
        gz = {"Content-Encoding": "gzip"}
        empty = gzip.compress(b"", mtime=0)
        self.assertEqual(len(empty), 20)
        for name, body in (("empty", empty), ("whitespace only", gzip.compress(b"  \n", mtime=0)),
                           ("two empty members", empty + empty)):
            for label in ("gzip", "X-GZIP", " Gzip "):
                with self.subTest(name=name, encoding=label):
                    row, _ = probe(response(200, 0, [("Content-Encoding", label)], body=body))
                    self.assertEqual(row["status"], "unavailable")
                    self.assertEqual(row["error"], "ValueError: Empty documentation response")
                    self.assertEqual(row["sampled_bytes"], len(body))
        # Control, bug caught: treating every gzip body as empty (an over-correction that hides
        # reachable sources). Receipt fields still describe the transport bytes, as before.
        for name, body in (("document", gzip.compress(b"Synthetic documentation", mtime=0)),
                           ("empty then document", empty + gzip.compress(b"Synthetic documentation", mtime=0))):
            with self.subTest(name=name):
                r = response(200, 0, gz.items(), body=body)
                row, _ = probe(r)
                self.assertEqual(row["status"], "accessible")
                self.assertNotIn("error", row)
                self.assertIs(row["body_complete"], True)
                self.assertEqual(row["sampled_bytes"], len(body))
                self.assertEqual(row["sha256"], r.receipt.sha256)

    def test_gzip_header_alone_never_triggers_decoding(self):
        # Bug caught: decoding by magic bytes or without Content-Encoding, or decoding a 206 fragment
        # or an over-cap sample (cut mid-stream, so its decoded text is unknown): those keep today's result.
        empty = gzip.compress(b"", mtime=0)
        cases = {
            "no Content-Encoding": (200, [], empty, True),
            "identity encoding": (200, [("Content-Encoding", "identity")], empty, True),
            "206 fragment": (206, [("Content-Encoding", "gzip"), ("Content-Range", "bytes 0-19/100")], empty, False),
            "over-cap sample": (200, [("Content-Encoding", "gzip")], empty + b"\0" * CAP, False),
            "corrupt gzip": (200, [("Content-Encoding", "gzip")], b"x" * 20, True),
            "cut gzip": (200, [("Content-Encoding", "gzip")], gzip.compress(b"Synthetic documentation")[:12], True),
        }
        for name, (status, headers, body, complete) in cases.items():
            with self.subTest(name):
                row, _ = probe(response(status, 0, headers, body=body))
                self.assertEqual(row["status"], "accessible")
                self.assertIs(row["body_complete"], complete)
                self.assertEqual(row["sampled_bytes"], len(body))

    def test_transport_refusal_is_unchanged(self):
        row, session = probe(http.TransportError("synthetic refusal"))
        self.assertEqual(row["status"], "unavailable")
        self.assertTrue(row["error"].startswith("TransportError: synthetic refusal"))
        self.assertNotIn("body_complete", row)
        self.assertNotIn("http_status", row)
        self.assertEqual(len(session.calls), 1)


class Aggregation(unittest.TestCase):
    def test_aggregation_keeps_access_separate_from_approval(self):
        full_url, part_url = "https://documentation.example.org/full", "https://documentation.example.org/part"
        sources = {"full": {"id": "full", "documentation_url": full_url, "review_status": "pending"},
                   "part": {"id": "part", "documentation_url": part_url, "review_status": "pending"}}
        before = copy.deepcopy(sources)
        session = RecordingSession({
            full_url: response(200, 20, url=full_url),
            part_url: response(206, 20, [("Content-Range", "bytes 0-19/100")], url=part_url)})
        with mock.patch.object(source_audit, "stamp", lambda: STAMP), \
                mock.patch.object(source_audit, "load_catalogs", lambda root=None: ({}, sources)), \
                mock.patch.object(source_audit.http, "default_session", lambda: session):
            result = source_audit.audit()
        rows = {row["source_id"]: row for row in result["sources"]}
        self.assertEqual(set(rows), {"full", "part"})
        self.assertEqual([r["status"] for r in rows.values()], ["accessible", "accessible"])
        self.assertIs(rows["full"]["body_complete"], True)
        self.assertIs(rows["part"]["body_complete"], False)
        self.assertEqual((rows["full"]["http_status"], rows["part"]["http_status"]), (200, 206))
        self.assertTrue(all(r["source_issue_time"] is None for r in rows.values()))
        self.assertEqual(sources, before)
        self.assertEqual(sorted(url for url, _ in session.calls), sorted([full_url, part_url]))


if __name__ == "__main__":
    unittest.main()
