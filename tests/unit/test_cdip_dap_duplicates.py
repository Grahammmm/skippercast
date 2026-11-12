"""RF2340-7: a CDIP DAP ASCII body that defines a variable twice is ambiguous and must refuse."""

from datetime import timedelta
import json
from unittest import TestCase

from skippercast.http import FakeSession
from skippercast.pipeline import cdip_nearshore as cdip
from tests.unit.test_cdip_nearshore import ASCII, BINDING, DAS, NOW, PISMO, parse, routes

DUPLICATE = "Duplicate CDIP variable"
HEIGHTS_9M = "waveHs[8]\n9, 9, 9, 9, 9, 9, 9, 9"


def appended(*records, text=ASCII):
    return text.rstrip("\n") + "".join("\n\n" + r for r in records) + "\n"


def sibling_ascii():
    """Synthetic matching data for the PISMO binding: the excerpt relabelled, no live endpoint."""
    return (ASCII.replace('"SL345"', '"SL097"').replace("35.36503", "35.13593")
            .replace("-120.87659", "-120.6609"))


def error_feed(feed):
    return feed["sources"][0]["outcome"], feed["health"]


class DuplicateParserTests(TestCase):
    def test_duplicate_arrays_refuse_even_when_complete(self):
        for name, repeat in (("waveHs", HEIGHTS_9M),
                             ("waveHs", "waveHs[8]\n" + "1.0720557, 1.0604185, 1.05244, 1.0469304, "
                                        "1.040345, 1.0325757, 1.0297607, 1.0276713"),
                             ("waveTime", "waveTime[8]\n1, 2, 3, 4, 5, 6, 7, 8"),
                             ("waveFlagPrimary", "waveFlagPrimary[8]\n1, 1, 1, 1, 1, 1, 1, 1"),
                             ("waveFlagSecondary", "waveFlagSecondary[8]\n2, 2, 2, 2, 2, 2, 2, 2")):
            text = appended(repeat)
            with self.subTest(name=name, repeat=repeat[:20]):
                with self.assertRaisesRegex(ValueError, f"{DUPLICATE}: {name}"):
                    cdip.parse_dap_ascii(text)
                with self.assertRaisesRegex(ValueError, f"{DUPLICATE}: {name}"):
                    parse(text=text)

    def test_duplicate_identity_never_repairs_a_conflicting_record(self):
        wrong_first = ASCII.replace('metaSiteLabel, "SL345"', 'metaSiteLabel, "WRONG"') + 'metaSiteLabel, "SL345"\n'
        right_first = ASCII + 'metaSiteLabel, "WRONG"\n'  # adjacent scalar, no blank line
        equal = ASCII + 'metaSiteLabel, "SL345"\n'
        coordinate = appended("metaLatitude, 35.36503")
        depth = appended("metaWaterDepth, 14.99")
        for label, text, name in (("wrong-first", wrong_first, "metaSiteLabel"),
                                  ("wrong-last", right_first, "metaSiteLabel"),
                                  ("equal", equal, "metaSiteLabel"),
                                  ("separate group", appended('metaSiteLabel, "SL345"'), "metaSiteLabel"),
                                  ("latitude", coordinate, "metaLatitude"),
                                  ("depth", depth, "metaWaterDepth")):
            with self.subTest(label):
                with self.assertRaisesRegex(ValueError, f"{DUPLICATE}: {name}"):
                    cdip.parse_dap_ascii(text)
                with self.assertRaisesRegex(ValueError, f"{DUPLICATE}: {name}"):
                    parse(text=text)

    def test_cross_form_duplicates_share_one_namespace(self):
        for text, name in ((appended("metaSiteLabel[1]\n\"SL345\""), "metaSiteLabel"),
                           (appended("waveHs, 9"), "waveHs")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, f"{DUPLICATE}: {name}"):
                cdip.parse_dap_ascii(text)
        with self.assertRaisesRegex(ValueError, f"{DUPLICATE}: metaNote"):
            cdip.parse_dap_ascii(appended("metaNote, 1", "metaNote[1]\n2"))

    def test_case_differences_and_quoted_text_are_not_duplicates(self):
        base = cdip.parse_dap_ascii(ASCII)
        parsed = cdip.parse_dap_ascii(appended("wavehs, 9", 'metaNote, "waveHs, 9"'))
        self.assertEqual(parsed["wavehs"], [9.0])
        self.assertEqual(parsed["metaNote"], ["waveHs, 9"])
        self.assertEqual({k: v for k, v in parsed.items() if k in base}, base)
        parse(text=appended("wavehs, 9", 'metaNote, "waveHs, 9"'))  # still a valid site

    def test_unambiguous_excerpt_is_identical(self):
        first = parse()
        self.assertEqual(first, parse(text=ASCII.rstrip("\n")))
        self.assertEqual(len(cdip.parse_dap_ascii(ASCII)), 10)
        self.assertEqual(len(first["hours"]), 7)
        self.assertEqual((first["availability"], first["issuedAt"], first["temporalResolutionMinutes"]),
                         ("available", "2026-10-08T13:47:44.000Z", 180))


class DuplicateCollectorTests(TestCase):
    ambiguous = appended(HEIGHTS_9M)

    def session(self, text):
        return FakeSession({**routes(BINDING), cdip.data_url("SL345"): text.encode()})

    def test_duplicate_collector_degrades_and_isolates_sites(self):
        session = FakeSession({**routes(BINDING), cdip.data_url("SL345"): self.ambiguous.encode(),
                               cdip.das_url("SL097"): DAS.encode(), cdip.data_url("SL097"): sibling_ascii().encode()})
        feed = cdip.collect("morro-bay", [BINDING, PISMO], NOW, session=session)
        morro, pismo = feed["nearshore"]
        self.assertEqual((morro["availability"], morro["hours"]), ("error", []))
        self.assertIn(DUPLICATE, morro["error"])
        self.assertEqual((pismo["availability"], len(pismo["hours"])), ("available", 7))
        self.assertEqual([s["outcome"] for s in feed["sources"]], ["error", "ok"])
        self.assertEqual(feed["health"], {"status": "degraded", "issues": ["cdip-SL345"]})
        self.assertTrue(all(url.startswith(cdip.BASE) for _, url, _ in session.calls))

    def test_duplicate_retention_boundaries_and_recovery(self):
        recent = {"region_id": "morro-bay", "nearshore": [parse()]}
        cases = (("none", None, False),
                 ("one hour", timedelta(hours=1), True),
                 ("three hours", timedelta(hours=3), False),
                 ("future", timedelta(hours=-1), False),
                 ("foreign region", timedelta(hours=1), False))
        for label, age, retained in cases:
            prior = None
            if age is not None:
                prior = {**recent, "nearshore": [{**parse(), "fetchedAt": cdip.iso(NOW - age)}]}
                if label == "foreign region":
                    prior["region_id"] = "cambria-san-simeon"
            original = json.dumps(prior, sort_keys=True)
            with self.subTest(label):
                feed = cdip.collect("morro-bay", [BINDING], NOW, prior, session=self.session(self.ambiguous))
                self.assertEqual(error_feed(feed), ("error", {"status": "degraded", "issues": ["cdip-SL345"]}))
                self.assertIn(DUPLICATE, feed["sources"][0]["error"])
                if retained:
                    assert prior is not None and age is not None
                    self.assertEqual(feed["nearshore"][0], prior["nearshore"][0])
                    self.assertEqual(feed["nearshore"][0]["fetchedAt"], cdip.iso(NOW - age))
                else:
                    self.assertEqual((feed["nearshore"][0]["availability"], feed["nearshore"][0]["hours"]), ("error", []))
                self.assertEqual(json.dumps(prior, sort_keys=True), original)
                recovered = cdip.collect("morro-bay", [BINDING], NOW, feed, session=FakeSession(routes(BINDING)))
                self.assertEqual(error_feed(recovered), ("ok", {"status": "ok", "issues": []}))
                self.assertEqual(recovered["nearshore"][0]["hours"], parse()["hours"])
