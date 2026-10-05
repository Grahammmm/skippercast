"""Entity resolution (design section 7, CF-15): table-driven synthetic cases.

Every boat, key and URL here is invented: names contain "Example" or "Test",
URLs are on example.com/example.gov, MMSIs and call signs are made up.
"""
from dataclasses import replace
import json
from pathlib import Path
import random
import tempfile
import unittest

from skippercast.fleet import ops
from skippercast.fleet.adapters.base import Candidate, Fact
from skippercast.fleet.config import ResolverRule
from skippercast.fleet.normalize import (clean_url, is_new_variant, jaro_winkler, name_norm, name_similarity, phone_e164,
                                         roman_to_int, slugify)
from skippercast.fleet.resolve import ResolverConfig, Snapshot, fingerprint, resolve
from skippercast.fleet.sinks import SqliteSink
from tests._support import ROOT

NOW = "2026-10-05T09:47:00.000Z"
EARLIER = "2026-09-01T09:47:00.000Z"
RULES = {k: ResolverRule(tuple(v["priority"]), float(v["min_confidence"]))
         for k, v in json.loads((ROOT / "catalog/fleet/resolver.json").read_text())["fields"].items()}
CONFIG = ResolverConfig("CA", RULES, 0.9, 0.6, {"morro-bay": "Morro Bay", "port-san-luis": "Port San Luis"},
                        {"example-landing": ("Example Landing", "morro-bay")})
SOURCE_URL = {"uscg-psix": "https://psix.example.gov/vessel/{}", "fcc-uls": "https://uls.example.gov/ship/{}",
              "landing-pages": "https://landing.example.com/fleet/{}", "operator-site": "https://boat.example.com/{}",
              "teck-reports": "https://reports.example.com/boat/{}", "osint": "https://news.example.com/{}"}


def fact(field, value, source="landing-pages", ident="x", confidence=0.9, at=NOW):
    return Fact(field, value, source, SOURCE_URL[source].format(ident), "page" if source != "fcc-uls" else "registry",
                confidence, "facts-only", at)


def cand(name, source="landing-pages", ident=None, port="morro-bay", landing=None, keys=None, facts=(), name_fact=True):
    ident = ident or slugify(name)
    extra = (fact("name", name, source, ident),) if name_fact else ()
    return Candidate(source, name, port, landing, dict(keys or {}), extra + tuple(facts), record_id=ident)


def stored(name, *, n, port="morro-bay", pinned=(), aliases=(), **cols):
    key = f"name-port:{slugify(name)}|{port}-{n}"
    row = {"id": ops.vessel_id("CA", key), "slug": slugify(name) + (f"-{n}" if n > 1 else ""), "name": name,
           "name_norm": name_norm(name), "operator_id": None, "port_id": port, "landing_id": None, "vessel_class": None,
           "waters": None, "uscg_doc": None, "state_reg": None, "hull_id": None, "call_sign": None, "mmsi": None,
           "status": "active", "profile_status": "hidden", "pinned": list(pinned), "completeness": 0.1,
           "first_seen_at": EARLIER, "last_seen_at": EARLIER,
           "aliases": [{"alias": a, "alias_norm": name_norm(a), "kind": "spelling"} for a in aliases]}
    row.update(cols)
    return row


def of(result, kind):
    return [op for op in result.ops if op["op"] == kind]


def vessel_op(result, vid):
    return next(op for op in of(result, "vessel.upsert") if op["id"] == vid)


class NormalizeTests(unittest.TestCase):
    def test_name_norm(self):
        for raw, expected in [("Sea Example", "SEAEXAMPLE"), ("The Sea Example", "SEAEXAMPLE"),
                              ("F/V Sea-Example", "SEAEXAMPLE"), ("M/V sea example ii", "SEAEXAMPLE2"),
                              ("Example Star IV", "EXAMPLESTAR4"), ("New Example Star", "NEWEXAMPLESTAR"),
                              ("Niña Example", "NINAEXAMPLE"), ("X", "X"), ("The", "THE"), ("Example XX", "EXAMPLE20"),
                              ("Reel Example 2", "REELEXAMPLE2"), ("", "")]:
            with self.subTest(raw=raw):
                self.assertEqual(name_norm(raw), expected)

    def test_new_is_kept_apart(self):
        self.assertTrue(is_new_variant("NEWEXAMPLESTAR", "EXAMPLESTAR"))
        self.assertEqual(name_similarity("NEWEXAMPLESTAR", "EXAMPLESTAR"), 0.0)
        self.assertGreater(name_similarity("EXAMPLESTAR", "EXAMPLESTARR"), 0.95)
        # exactly one leading NEW is a different boat, even when the rest differs too
        self.assertEqual(name_similarity("NEWEXAMPLESTARR", "EXAMPLESTAR"), 0.0)
        self.assertGreater(name_similarity("NEWEXAMPLESTAR", "NEWEXAMPLESTARR"), 0.95)

    def test_jaro_winkler_reference_values(self):
        self.assertAlmostEqual(jaro_winkler("MARTHA", "MARHTA"), 0.9611, places=4)
        self.assertAlmostEqual(jaro_winkler("DIXON", "DICKSONX"), 0.8133, places=4)
        self.assertEqual((jaro_winkler("A", "A"), jaro_winkler("", "A")), (1.0, 0.0))

    def test_roman_phone_url_slug(self):
        self.assertEqual([roman_to_int(t) for t in ("I", "IV", "IX", "XIV", "XXXIX", "IIII", "MIX", "")],
                         [1, 4, 9, 14, 39, None, None, None])
        for raw, expected in [("(805) 555-0101", "+18055550101"), ("1-805-555-0102 ext. 4", "+18055550102"),
                              ("+44 20 7946 0103", "+442079460103"), ("555-0101", None), (None, None)]:
            self.assertEqual(phone_e164(raw), expected, raw)
        self.assertEqual(clean_url("https://Boat.Example.com/book?utm_source=x&trip=half&fbclid=1#top"),
                         "https://boat.example.com/book?trip=half")
        self.assertIsNone(clean_url("http://boat.example.com/"))
        self.assertEqual((slugify("Sea Example II"), slugify("¡!")), ("sea-example-ii", "vessel"))


class ResolveCases(unittest.TestCase):
    """The CF-15 acceptance cases, each a (snapshot, candidates) -> expected outcome row."""

    def test_rename_by_doc_number(self):
        old = stored("Sea Example", n=1, uscg_doc="1234567")
        new = cand("Ocean Example", "uscg-psix", "1234567", port=None, keys={"uscg_doc": "1234 567"})
        result = resolve(Snapshot([old]), [new], CONFIG, NOW)
        self.assertEqual((result.assignments[fingerprint(new)], result.created), (old["id"], []))
        self.assertEqual(result.scores[fingerprint(new)], 1.0)
        op = vessel_op(result, old["id"])
        self.assertEqual((op["name"], op["name_norm"], op["slug"]), ("Ocean Example", "OCEANEXAMPLE", "sea-example"))
        self.assertEqual([(a["alias"], a["alias_norm"], a["kind"]) for a in of(result, "alias.upsert")],
                         [("Sea Example", "SEAEXAMPLE", "former-name")])
        self.assertEqual([(c["kind"], c["before_json"], c["after_json"]) for c in of(result, "change.record")],
                         [("renamed", {"name": "Sea Example"}, {"name": "Ocean Example"})])

    def test_cases(self):
        star = stored("Example Star", n=1, mmsi="366000001", call_sign="WDX1001", length_ft=60)
        cs = stored("Test Runner", n=2, call_sign="WDX2002")
        cs_mmsi = stored("Test Runner Two", n=3, call_sign="WDX3003", mmsi="366000003")
        sea = stored("Sea Example", n=4, landing_id="example-landing")
        cases = [
            # name, snapshot vessels, candidate, expected: "assign:<id>" | "create" | "review"
            ("same name, same port, different MMSI -> a second vessel", [star],
             cand("Example Star", "fcc-uls", "b", keys={"mmsi": "366000002"}), "create"),
            ("same name, same port, same MMSI -> the vessel", [star],
             cand("Example Star", "fcc-uls", "a", keys={"mmsi": "366000001"}), f"assign:{star['id']}"),
            ("same name, same port, no keys -> fuzzy 0.9 assigns", [star],
             cand("Example Star", "landing-pages"), f"assign:{star['id']}"),
            ("New-X is not X", [star], cand("New Example Star"), "create"),
            ("X is not New-X", [stored("New Example Star", n=5)], cand("Example Star"), "create"),
            ("call sign alone -> 0.9", [cs], cand("Test Runner Renamed", "fcc-uls", "c", port=None,
                                                     keys={"call_sign": "wdx 2002"}), f"assign:{cs['id']}"),
            ("call sign reissued to a boat with another MMSI -> no key match", [cs_mmsi],
             cand("Other Example", "fcc-uls", "d", port=None, keys={"call_sign": "WDX3003", "mmsi": "366000009"}),
             "create"),
            ("misspelt, port unknown -> one merge review", [sea], cand("Sea Exampel", "teck-reports", port=None),
             "review"),
            ("alias match at the same port -> assign", [stored("Example Queen", n=6, aliases=["Example Queen 2"])],
             cand("Example Queen II"), "assign:" + stored("Example Queen", n=6)["id"]),
            ("unrelated name -> new vessel", [sea], cand("Test Wanderer"), "create"),
        ]
        for name, vessels, candidate, expected in cases:
            with self.subTest(name):
                result = resolve(Snapshot(vessels), [candidate], CONFIG, NOW)
                got = result.assignments[fingerprint(candidate)]
                reviews = of(result, "review.open")
                if expected == "create":
                    self.assertEqual((got, len(result.created), reviews), (result.created[0], 1, []))
                    self.assertNotIn(got, {v["id"] for v in vessels})
                elif expected == "review":
                    self.assertIsNone(got)
                    self.assertEqual(len(reviews), 1)
                    self.assertEqual(reviews[0]["kind"], "merge")
                    self.assertTrue(0.6 <= reviews[0]["score"] < 0.9, reviews[0]["score"])
                    self.assertEqual(reviews[0]["proposal_json"]["vessel_id"], vessels[0]["id"])
                    self.assertEqual(of(result, "vessel.upsert"), [])
                else:
                    self.assertEqual((got, result.created, reviews), (expected.split(":")[1], [], []))
                self.assertEqual(ops.validate_ops(result.ops, "CA")[1], [])
        result = resolve(Snapshot([cs]), [cases[5][2]], CONFIG, NOW)
        self.assertEqual(result.scores[fingerprint(cases[5][2])], 0.9)
        strict = replace(CONFIG, auto_merge=0.95)
        self.assertEqual(of(resolve(Snapshot([cs]), [cases[5][2]], strict, NOW), "review.open")[0]["score"], 0.9)

    def test_two_new_vessels_same_name_same_port_get_distinct_ids_and_slugs(self):
        a = cand("Example Star", "fcc-uls", "a", keys={"mmsi": "366000001"})
        b = cand("Example Star", "fcc-uls", "b", keys={"mmsi": "366000002"})
        result = resolve(Snapshot(advisor_slugs=frozenset({"example-star"})), [a, b], CONFIG, NOW)
        self.assertEqual(len(result.created), 2)
        self.assertEqual(sorted(op["slug"] for op in of(result, "vessel.upsert")),
                         ["example-star-morro-bay", "example-star-morro-bay-2"])
        self.assertEqual({result.assignments[fingerprint(a)], result.assignments[fingerprint(b)]},
                         {ops.vessel_id("CA", "mmsi:366000001"), ops.vessel_id("CA", "mmsi:366000002")})

    def test_keys_on_two_vessels_open_a_merge_review(self):
        one, two = stored("Example One", n=1, uscg_doc="1111111"), stored("Example Two", n=2, mmsi="366000002")
        candidate = cand("Example One", "fcc-uls", "z", keys={"uscg_doc": "1111111", "mmsi": "366000002"})
        result = resolve(Snapshot([one, two]), [candidate], CONFIG, NOW)
        (review,) = of(result, "review.open")
        self.assertEqual([v["vessel_id"] for v in review["proposal_json"]["vessels"]], [one["id"], two["id"]])
        self.assertEqual(review["fingerprint"], fingerprint(candidate))

    def test_decided_reviews_are_honoured(self):
        sea = stored("Sea Example", n=4)
        candidate = cand("Sea Exampel", "teck-reports", port=None)
        rid = ops.review_id("merge", fingerprint(candidate))
        for decision, status, expected in [({"action": "same-vessel", "vessel_id": sea["id"]}, "decided", sea["id"]),
                                           ({"action": "new-vessel"}, "decided", "new"),
                                           ({"action": "dismiss"}, "dismissed", None)]:
            with self.subTest(decision["action"]):
                review = {"id": rid, "kind": "merge", "status": status, "decision": decision}
                result = resolve(Snapshot([sea], [review]), [candidate], CONFIG, NOW)
                self.assertEqual(of(result, "review.open"), [])
                got = result.assignments[fingerprint(candidate)]
                self.assertEqual(got, result.created[0] if expected == "new" else expected)

    def test_pinned_fields_untouched(self):
        sea = stored("Sea Example", n=4, uscg_doc="1234567", mmsi="366000004",
                     pinned=["name", "name_norm", "mmsi", "vessel_class"])
        candidate = cand("Ocean Example", "uscg-psix", "1234567", keys={"uscg_doc": "1234567"},
                         facts=[fact("mmsi", "366000099", "uscg-psix", "1234567"),
                                fact("vessel_class", "long-range", "uscg-psix", "1234567"),
                                fact("length_ft", 61.5, "uscg-psix", "1234567")])
        result = resolve(Snapshot([sea]), [candidate], CONFIG, NOW)
        op = vessel_op(result, sea["id"])
        self.assertEqual((op["name"], op["name_norm"], op["length_ft"]), ("Sea Example", "SEAEXAMPLE", 61.5))
        self.assertNotIn("mmsi", op)
        self.assertNotIn("vessel_class", op)
        self.assertEqual((of(result, "change.record"), of(result, "alias.upsert")[0]["kind"]), ([], "spelling"))
        everything = stored("Sea Example", n=4, uscg_doc="1234567", pinned=["*"])
        op = vessel_op(resolve(Snapshot([everything]), [candidate], CONFIG, NOW), sea["id"])
        self.assertEqual(sorted(op), sorted(["op", "id", "slug", "name", "name_norm", "first_seen_at", "last_seen_at",
                                             "completeness"]))

    def test_admin_null_fact_means_no_value_wins(self):
        sea = stored("Sea Example", n=4, website=None)
        admin = {"id": "a" * 32, "vessel_id": sea["id"], "field": "website", "value": None, "source_id": "admin",
                 "source_url": "admin:user-1", "method": "admin", "confidence": 1, "retrieved_at": EARLIER}
        candidate = cand("Sea Example", "operator-site", facts=[fact("website", "https://boat.example.com/?utm_source=x",
                                                                     "operator-site")])
        with_admin = vessel_op(resolve(Snapshot([sea], facts=[admin]), [candidate], CONFIG, NOW), sea["id"])
        without = vessel_op(resolve(Snapshot([sea], facts=[]), [candidate], CONFIG, NOW), sea["id"])
        self.assertIsNone(with_admin["website"])
        self.assertEqual(without["website"], "https://boat.example.com/")

    def test_column_winner_priority_confidence_and_minimum(self):
        candidate = cand("Sea Example", "landing-pages", facts=[
            fact("length_ft", 58, "osint", "1"), fact("length_ft", 60, "landing-pages", "1", confidence=0.7),
            fact("length_ft", 65, "uscg-psix", "1", confidence=0.5),   # below min_confidence 0.6
            fact("phone_business", "(805) 555-0101", "operator-site", "1"),
            fact("waters", ["ocean", "bay"], "landing-pages", "1")])
        result = resolve(Snapshot(), [candidate], CONFIG, NOW)
        (op,) = of(result, "vessel.upsert")
        self.assertEqual((op["length_ft"], op["phone_business"], op["waters_json"]), (60, "+18055550101", ["ocean", "bay"]))
        self.assertEqual((op["vessel_class"] if "vessel_class" in op else None, op["status"], op["profile_status"]),
                         (None, "active", "hidden"))
        self.assertEqual(len(of(result, "fact.upsert")), 6)

    def test_class_disagreement_opens_a_class_review(self):
        candidates = [cand("Sea Example", "landing-pages", facts=[fact("vessel_class", "inspected-party")]),
                      cand("Sea Example", "uscg-psix", "1234567", keys={"uscg_doc": "1234567"},
                           facts=[fact("vessel_class", "six-pack", "uscg-psix", "1234567", confidence=0.8)])]
        result = resolve(Snapshot(), candidates, CONFIG, NOW)
        (vessel,) = of(result, "vessel.upsert")
        self.assertEqual(vessel["vessel_class"], "six-pack")  # uscg-psix ranks above landing-pages
        (review,) = of(result, "review.open")
        self.assertEqual((review["kind"], review["subject_id"], review["proposal_json"]["vessel_class"]),
                         ("class", vessel["id"], "six-pack"))

    def test_out_of_scope_is_excluded(self):
        candidate = cand("Example Whale Watcher", facts=[fact("scope", {"in_scope": False, "reason": "whale-watch-only"})])
        (op,) = of(resolve(Snapshot(), [candidate], CONFIG, NOW), "vessel.upsert")
        self.assertEqual(op["status"], "excluded")

    def test_deterministic_and_order_independent(self):
        snapshot = Snapshot([stored("Sea Example", n=1, uscg_doc="1234567"), stored("Example Star", n=2, mmsi="366000001")])
        candidates = [cand("Ocean Example", "uscg-psix", "1234567", keys={"uscg_doc": "1234567"}),
                      cand("Example Star", "fcc-uls", "b", keys={"mmsi": "366000002"}),
                      cand("Example Star", "landing-pages"), cand("New Example Star"), cand("Sea Exampel", port=None),
                      cand("Test Wanderer", "teck-reports", facts=[fact("length_ft", 42, "teck-reports", "tw")])]
        first = resolve(snapshot, candidates, CONFIG, NOW)
        again = resolve(snapshot, candidates, CONFIG, NOW)
        shuffled = list(candidates)
        random.Random(7).shuffle(shuffled)
        third = resolve(snapshot, shuffled, CONFIG, NOW)
        self.assertEqual(ops.canonical_json(first.ops), ops.canonical_json(again.ops))
        self.assertEqual(ops.canonical_json(first.ops), ops.canonical_json(third.ops))
        self.assertEqual(first.assignments, third.assignments)


class ReviewFixes(unittest.TestCase):
    """PR #316 review: shared-page fingerprints, the null rule and the slug cap."""

    PAGE = "https://landing.example.com/fleet?utm_source=x"

    def page_cand(self, name):
        return Candidate("landing-pages", name, None, None, {}, (
            Fact("name", name, "landing-pages", self.PAGE, "page", 0.9, "facts-only", NOW),))

    def test_boats_on_one_page_keep_distinct_fingerprints_and_reviews(self):
        sea, star = stored("Sea Example", n=1), stored("Example Star", n=2)
        cands = [self.page_cand("Sea Exampel"), self.page_cand("Example Stra"), self.page_cand("Test Wanderer")]
        prints = [fingerprint(c) for c in cands]
        self.assertEqual(len(set(prints)), 3)
        self.assertEqual(prints[0], "landing-pages|SEAEXAMPEL||https://landing.example.com/fleet")
        first = resolve(Snapshot([sea, star]), cands, CONFIG, NOW)
        for seed in range(5):
            shuffled = list(cands)
            random.Random(seed).shuffle(shuffled)
            again = resolve(Snapshot([sea, star]), shuffled, CONFIG, NOW)
            self.assertEqual((again.assignments, ops.canonical_json(again.ops)),
                             (first.assignments, ops.canonical_json(first.ops)))
        reviews = of(first, "review.open")
        self.assertEqual(len(reviews), 2)
        self.assertEqual(len({ops.review_id("merge", r["fingerprint"]) for r in reviews}), 2)
        self.assertEqual({r["proposal_json"]["vessel_id"] for r in reviews}, {sea["id"], star["id"]})
        self.assertEqual(len(first.created), 1)

    def test_only_an_admin_null_clears_a_column(self):
        sea = stored("Sea Example", n=4)
        null = {"id": "b" * 32, "vessel_id": sea["id"], "field": "website", "value": None, "source_id": "operator",
                "source_url": "https://boat.example.com/", "method": "operator", "confidence": 1, "retrieved_at": EARLIER}
        candidate = cand("Sea Example", "operator-site", facts=[
            fact("website", "https://boat.example.com/book", "operator-site"),
            fact("booking_url", None, "landing-pages")])
        op = vessel_op(resolve(Snapshot([sea], facts=[null]), [candidate], CONFIG, NOW), sea["id"])
        self.assertEqual(op["website"], "https://boat.example.com/book")  # the operator's null is no fact
        self.assertNotIn("booking_url", op)                                # nor is a landing page's

    def test_slugs_are_capped_at_80(self):
        long_name = "Example " * 20
        taken = frozenset({slugify(long_name)[:80].strip("-")})
        a = cand(long_name, "fcc-uls", "a", keys={"mmsi": "366000001"})
        b = cand(long_name, "fcc-uls", "b", keys={"mmsi": "366000002"})
        c = cand(long_name, "fcc-uls", "c", keys={"mmsi": "366000003"})
        slugs = [op["slug"] for op in of(resolve(Snapshot(advisor_slugs=taken), [a, b, c], CONFIG, NOW), "vessel.upsert")]
        self.assertEqual(len(set(slugs)), 3)
        self.assertTrue(all(len(x) <= 80 and ops.SLUG.match(x) for x in slugs), slugs)
        self.assertTrue(all(x.endswith(("-morro-bay", "-morro-bay-2", "-morro-bay-3")) for x in slugs), slugs)


class StagingRoundTrip(unittest.TestCase):
    """Resolve -> SqliteSink -> snapshot -> resolve again: the second pass changes nothing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = SqliteSink(Path(self.tmp.name) / "CA.sqlite", "CA", "run-1")

    def tearDown(self):
        self.sink.close()
        self.tmp.cleanup()

    def candidates(self):
        return [cand("Sea Example", "uscg-psix", "1234567", keys={"uscg_doc": "1234567"},
                     facts=[fact("length_ft", 61.5, "uscg-psix", "1234567")]),
                cand("Sea Example", "landing-pages", landing="Example Landing",
                     facts=[fact("waters", ["ocean"]), fact("website", "https://boat.example.com/?gclid=1",
                                                            "landing-pages")]),
                cand("Example Star", "fcc-uls", "a", keys={"mmsi": "366000001", "call_sign": "WDX1001"}),
                cand("Example Star", "fcc-uls", "b", keys={"mmsi": "366000002"}),
                cand("New Example Star", "landing-pages")]

    def test_second_run_writes_nothing_and_slugs_avoid_advisor_boats(self):
        self.sink.db.execute("INSERT INTO advisor_boats(id, slug, name, port, region, created_at, updated_at) "
                             "VALUES ('b1', 'example-star', 'Example Star', 'morro-bay', 'morro-bay', ?, ?)", (NOW, NOW))
        first = resolve(Snapshot.from_sqlite(self.sink.db, "CA"), self.candidates(), CONFIG, NOW)
        self.assertEqual(self.sink.apply(first.ops)["changed"] > 0, True)
        snapshot = Snapshot.from_sqlite(self.sink.db, "CA")
        self.assertEqual(len(snapshot.vessels), 4)
        self.assertNotIn("example-star", {v["slug"] for v in snapshot.vessels})
        second = resolve(snapshot, self.candidates(), CONFIG, NOW)
        self.assertEqual(second.created, [])
        self.assertEqual({v for v in second.assignments.values() if v}, {v for v in first.assignments.values() if v})
        self.assertEqual(self.sink.apply(second.ops)["changed"], 0)
        # without facts in the snapshot (the Worker's), a re-run changes nothing either
        worker = Snapshot(snapshot.vessels, snapshot.reviews, snapshot.operators, snapshot.advisor_slugs, None)
        self.assertEqual(self.sink.apply(resolve(worker, self.candidates(), CONFIG, NOW).ops)["changed"], 0)

    def test_pinned_columns_survive_the_sink(self):
        self.sink.apply(resolve(Snapshot(), self.candidates()[:1], CONFIG, NOW).ops)
        self.sink.db.execute("""UPDATE fleet_vessels SET length_ft=70, pinned_json='{"length_ft":{"by":"u1"}}'""")
        later = "2026-10-12T09:47:00.000Z"
        candidate = cand("Sea Example", "uscg-psix", "1234567", keys={"uscg_doc": "1234567"},
                         facts=[fact("length_ft", 62, "uscg-psix", "1234567", at=later)])
        result = resolve(Snapshot.from_sqlite(self.sink.db, "CA"), [candidate], CONFIG, later)
        self.assertNotIn("length_ft", of(result, "vessel.upsert")[0])
        self.sink.apply(result.ops)
        self.assertEqual(self.sink.db.execute("SELECT length_ft FROM fleet_vessels").fetchone(), (70,))


class SnapshotPagesTests(unittest.TestCase):
    def test_from_pages_joins_sections(self):
        pages = [{"operators": [{"id": "o1"}], "vessels": [], "reviews": [], "next": "v:"},
                 {"operators": [], "vessels": [stored("Sea Example", n=1)], "reviews": [], "next": "r:"},
                 {"operators": [], "vessels": [], "reviews": [{"id": "r1", "status": "decided"}], "next": None}]
        snapshot = Snapshot.from_pages(pages)
        self.assertEqual((len(snapshot.operators), len(snapshot.vessels), len(snapshot.reviews), snapshot.facts),
                         (1, 1, 1, None))


if __name__ == "__main__":
    unittest.main()
