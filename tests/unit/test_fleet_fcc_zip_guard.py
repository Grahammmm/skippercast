"""RF0420-3: fcc-uls refuses a bad ship file with FccFormatError before any candidate.

A body that is not a zip, an EN/HD/SH member present twice (any case), a member
whose stated size is past the cap and a damaged member each get one plain reason;
a good archive gives exactly the same candidates and stats as before. In-memory
zips built from the synthetic fixtures only; no network.
"""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings
import zipfile

from skippercast.fleet import ingest
from skippercast.fleet.adapters import fcc_uls
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.adapters.fcc_uls import FccFormatError, parse_ship_zip
from tests._support import FIXTURES

FCC = FIXTURES / "fleet" / "fcc"
NOW = "2026-10-05T09:47:00Z"
HTML = b"<html>Service unavailable</html>"
ORIGINAL_OPEN = zipfile.ZipFile.open


def files(**extra):
    return {**{p.name: p.read_bytes() for p in sorted(FCC.glob("*.dat"))}, **extra}


def make_zip(members, method=zipfile.ZIP_DEFLATED):
    buffer = io.BytesIO()
    with warnings.catch_warnings(), zipfile.ZipFile(buffer, "w", method) as archive:
        warnings.simplefilter("ignore")  # a repeated name is the point of one test
        for name, body in members.items() if isinstance(members, dict) else members:
            archive.writestr(name, body)
    return buffer.getvalue()


def corrupt(data, name):
    """Flip one bit inside ``name``'s stored data, so its CRC no longer matches."""
    info = zipfile.ZipFile(io.BytesIO(data)).getinfo(name)
    at = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra) + 5
    return data[:at] + bytes([data[at] ^ 1]) + data[at + 1:]


def run(data, stats=None):
    return list(parse_ship_zip(data, "CA", source_id="fcc-uls", rights="public-domain", retrieved_at=NOW,
                               ports={"MORROBAY": "morro-bay", "SANDIEGO": "san-diego"}, stats=stats))


class ZipGuardTests(unittest.TestCase):
    def refused(self, data, pattern):
        stats = {}
        with patch.object(zipfile.ZipFile, "open", autospec=True, side_effect=ORIGINAL_OPEN) as spy, \
                self.assertRaises(FccFormatError) as caught:
            run(data, stats)
        self.assertRegex(str(caught.exception), pattern)
        self.assertNotIn("candidates", stats)  # the run never finished, so no candidate list exists
        return caught.exception, spy, stats

    def test_body_that_is_not_a_zip_is_named(self):
        for body in (HTML, b"", io.BytesIO(HTML)):
            with self.subTest(body=body):
                error, spy, _ = self.refused(body, "^ship file is not a readable zip$")
                self.assertTrue(error.__suppress_context__)  # no BadZipFile chained into the message
                spy.assert_not_called()

    def test_truncated_zip_is_not_a_readable_zip(self):
        good = make_zip(files())
        for cut in (len(good) // 2, len(good) - 1):
            with self.subTest(cut=cut):
                self.refused(good[:cut], "^(ship file is not a readable zip|[A-Z]{2}\\.dat is damaged)$")

    def test_member_present_twice_is_refused_before_any_record(self):
        cases = {"EN": files(**{"en.DAT": files()["EN.dat"]}),
                 "HD": files(**{"hd.dat": files()["HD.dat"]}),
                 "SH": files(**{"Sh.Dat": files()["SH.dat"]}),
                 "same name": list(files().items()) + [("SH.dat", files()["SH.dat"])]}
        for label, members in cases.items():
            with self.subTest(label):
                kind = "SH" if label == "same name" else label
                _, spy, stats = self.refused(make_zip(members), f"^{kind}\\.dat appears more than once in the ship file$")
                spy.assert_not_called()  # SH is checked before EN is read
                self.assertNotIn("en_records", stats)

    def test_member_past_the_size_cap_is_refused_unopened(self):
        largest = max(len(body) for body in files().values())
        with patch.object(fcc_uls, "MAX_MEMBER_BYTES", largest):
            self.assertTrue(run(make_zip(files())))  # a member exactly at the cap is read
            big = make_zip(files(**{"SH.dat": files()["SH.dat"] + b"X" * largest}))
            _, spy, _ = self.refused(big, "^SH\\.dat expands past the size cap$")
            spy.assert_not_called()
        with patch.object(fcc_uls, "MAX_MEMBER_BYTES", 10):
            _, spy, _ = self.refused(make_zip(files()), "^EN\\.dat expands past the size cap$")
            spy.assert_not_called()

    def test_damaged_member_is_named(self):
        for name in ("EN.dat", "SH.dat"):
            for method in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                with self.subTest(name=name, method=method):
                    data = corrupt(make_zip(files(), method), name)
                    self.refused(data, f"^{name[:2]}\\.dat is damaged$")

    def test_good_archive_gives_todays_candidates_and_stats(self):
        stats, baseline_stats = {}, {}
        with patch.object(fcc_uls, "MAX_MEMBER_BYTES", 10 ** 15):
            baseline = [c.as_dict() for c in run(make_zip(files()), baseline_stats)]
        self.assertEqual([c.as_dict() for c in run(make_zip(files()), stats)], baseline)
        self.assertEqual(stats, baseline_stats)
        self.assertEqual(stats["candidates"], len(baseline))
        self.assertTrue(baseline)
        lower = make_zip({name.lower(): body for name, body in files().items()})  # one variant is not ambiguous
        self.assertEqual([c.as_dict() for c in run(lower)], baseline)


class DiscoverTests(unittest.TestCase):
    def test_html_body_is_a_failed_binding_named_fcc_format_error(self):
        response = SimpleNamespace(body=HTML, receipt=SimpleNamespace(from_cache=False, bytes=len(HTML)))
        net = SimpleNamespace(skips=[], get=lambda url, **kw: response)
        source = SimpleNamespace(id="fcc-uls", adapter="fcc-uls", enabled=True, rights="public-domain",
                                 params={"state": "CA"})
        region = SimpleNamespace(id="CA", ports=[], enabled_sources=lambda: (source,))
        with tempfile.TemporaryDirectory() as tmp:
            result = ingest.discover(RunContext(region, net, Path(tmp), lambda: NOW), None)
            doc = json.loads((Path(tmp) / "discover.json").read_text(encoding="utf-8"))
            rows = (Path(tmp) / "candidates.jsonl").read_text(encoding="utf-8")
        self.assertEqual(doc["bindings"]["fcc-uls"],
                         {"status": "failed", "error": "FccFormatError: ship file is not a readable zip"})
        self.assertEqual((result["candidates"], result["failed"], rows), (0, 1, ""))


if __name__ == "__main__":
    unittest.main()
