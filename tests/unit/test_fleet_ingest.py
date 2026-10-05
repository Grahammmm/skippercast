"""Ingest and the ``run`` orchestrator end to end on the SqliteSink (design section 9, CF-17).

Two synthetic discovery sources (``landing-pages`` and ``uscg-psix``) and a fake
``operator-site`` enricher stand in for the adapters; every name, number and URL
is invented (example.com/example.gov, 555-01XX phones). ``Pipeline`` is shared
with ``test_fleet_refresh``.
"""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from skippercast.fleet import cli, ops
from skippercast.fleet.adapters.base import Candidate, Departure, Fact, Offering, RunContext
from skippercast.fleet.config import Binding, load_region
from skippercast.fleet.ingest import candidate_from_dict, load_snapshot
from skippercast.fleet.resolve import ResolverConfig, Snapshot, resolve
from skippercast.fleet.runs import Run
from skippercast.fleet.sinks import SqliteSink

BASE = load_region("CA")
REGION = replace(BASE, sources=(
    Binding("landing-pages", "landing-pages", True, {}, "facts-only"),
    Binding("uscg-psix", "uscg-psix", True, {}, "public-domain"),
    Binding("operator-site", "operator-site", True, {}, "facts-only")))
DAY0 = "2026-10-05T09:47:00Z"
REGISTRY = ("fleet_operators", "fleet_vessels", "fleet_vessel_facts", "fleet_aliases", "fleet_offerings",
            "fleet_departures", "fleet_reviews", "fleet_changes")


def day(n: int) -> str:
    return f"2026-{10 + (5 + n - 1) // 31:02d}-{(5 + n - 1) % 31 + 1:02d}T09:47:00Z"


def landing(name, at, *, operator=None, offerings=(), keys=None, departures=()):
    url = f"https://landing.example.com/fleet/{name.lower().replace(' ', '-')}"
    facts = [Fact("name", name, "landing-pages", url, "page", 0.9, "facts-only", at)]
    if operator:
        facts.append(Fact("operator", operator, "landing-pages", url, "page", 0.9, "facts-only", at))
    offers = []
    for label, cents, departs in offerings:
        trip = Fact("trip_types[]", {"name": label, "price_cents": cents, "departs": departs}, "landing-pages", url,
                    "page", 0.9, "facts-only", at)
        facts.append(trip)
        offers.append(Offering(label, "half-day" if "Half" in label else "full-day", (trip,), cents, "per-person",
                               departs_local=departs, days=("sat", "sun")))
    deps = tuple(Departure(offers[0], date, offers[0].departs_local, offers[0].price_cents, "10 of 30", url, at)
                 for date in departures)
    return Candidate("landing-pages", name, "morro-bay", "morro-bay-landing", dict(keys or {}), tuple(facts), url,
                     tuple(offers), deps)


def psix(name, doc, at):
    url = f"https://psix.example.gov/vessel/{doc}"
    return Candidate("uscg-psix", name, "morro-bay", None, {"uscg_doc": doc},
                     (Fact("name", name, "uscg-psix", url, "registry", 0.8, "public-domain", at),
                      Fact("uscg_doc", doc, "uscg-psix", url, "registry", 0.9, "public-domain", at)), url)


class Source:
    """A discovery adapter returning whatever the test set for its binding."""
    kind = "discover"

    def __init__(self, error=None):
        self.candidates, self.error = [], error

    def discover(self, binding, ctx):
        if self.error:
            raise self.error
        return list(self.candidates)


class Enricher:
    """operator-site stand-in: a business phone, and a flagged (webmail) email for the named vessel."""
    kind = "enrich"
    report = {}

    def __init__(self, name):
        self.name = name

    def enrich(self, vessel, binding, ctx):
        if vessel["name"] != self.name:
            return []
        url, at = "https://seaexample.example.com/contact", ctx.clock()
        return [Fact("phone_business", "+18055550123", "operator-site", url, "page", 0.9, "facts-only", at),
                Fact("email_business", "captain@example.com", "operator-site", url, "page", 0.9, "facts-only", at,
                     ("webmail",))]


class Pipeline:
    """Runs of ``cli.execute`` over one staging database; ``worker=True`` resolves against the Worker's snapshot shape."""

    def __init__(self, tmp, worker=False):
        self.var, self.worker, self.count = Path(tmp), worker, 0
        self.landing, self.psix, self.enricher = Source(), Source(), Enricher("Sea Example")

    def load(self, sink, region):
        return Snapshot.from_sqlite(sink.db, region, facts=not self.worker)

    def run(self, at, landing=(), psix=(), steps=cli.PIPELINE, run_id=None):
        self.count += 1
        self.landing.candidates, self.psix.candidates = list(landing), list(psix)
        run = Run("CA", run_id or at.replace("-", "").replace(":", "")[:15] + f"Z-{self.count:06x}", var=self.var)
        self.last = sink = SqliteSink(self.var / "CA.sqlite", "CA", run.id)
        ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: at)
        try:
            options = {"discover": {"adapters": {"landing-pages": self.landing, "uscg-psix": self.psix}},
                       "resolve": {"load": self.load}, "ingest": {"load": self.load},
                       "enrich-code": {"adapters": {"operator-site": self.enricher}}}
            report = cli.execute(run, ctx, sink, steps, options)
            report["run_id"] = run.id
            return report
        finally:
            sink.close()

    def db(self):
        return SqliteSink(self.var / "CA.sqlite", "CA", "check").db

    def rows(self, table):
        db = self.db()
        cursor = db.execute(f"SELECT * FROM {table} ORDER BY 1, 2")
        names = [d[0] for d in cursor.description]
        out = [dict(zip(names, row)) for row in cursor.fetchall()]
        db.close()
        return out

    def vessel(self, name):
        return next(v for v in self.rows("fleet_vessels") if v["name"] == name)


def without_run_id(rows):
    return [{k: v for k, v in row.items() if k != "run_id"} for row in rows]


def baseline(at, *, rockfish=True):
    """Day-0 fleet: five boats from two sources (Bluewater's two names share a doc number: an alias)."""
    land = [landing("Sea Example", at, operator="Example Charters LLC", offerings=[("Half Day", 9500, "06:30")],
                    departures=["2026-10-10"]),
            landing("Kelp Test", at, operator="Example Charters LLC", offerings=[("Full Day", 15000, "05:00")]),
            landing("Bluewater Example", at, keys={"uscg_doc": "1000003"})]
    if rockfish:
        land.append(landing("Rockfish Test", at))
    return land, [psix("SEA EXAMPLE", "1000001", at), psix("KELP TEST", "1000002", at),
                  psix("BLUEWATER EX", "1000003", at), psix("Tide Runner Test", "1000005", at)]


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_from_empty_a_two_source_run_fills_the_registry(self):
        p = Pipeline(self.tmp.name)
        report = p.run(DAY0, *baseline(DAY0))
        self.assertEqual(report["status"], "ok", report)
        self.assertEqual(sorted(v["name"] for v in p.rows("fleet_vessels")),
                         ["Bluewater Example", "Kelp Test", "Rockfish Test", "Sea Example", "Tide Runner Test"])
        sea = p.vessel("Sea Example")
        self.assertEqual((sea["uscg_doc"], sea["phone_business"], sea["email_business"]), ("1000001", "+18055550123", None))
        self.assertEqual({a["alias_norm"] for a in p.rows("fleet_aliases")}, {"BLUEWATEREX"})
        self.assertEqual(sorted((o["name"], o["price_cents"]) for o in p.rows("fleet_offerings")),
                         [("Full Day", 15000), ("Half Day", 9500)])
        self.assertEqual(len(p.rows("fleet_departures")), 1)
        self.assertEqual(len(p.rows("fleet_operators")), 1)
        self.assertEqual(sea["operator_id"], p.vessel("Kelp Test")["operator_id"])
        facts = p.rows("fleet_vessel_facts")
        self.assertGreater(len(facts), 10)
        self.assertTrue(all(ops.https_url(f["source_url"]) for f in facts), "every fact keeps an https source_url")
        self.assertNotIn("captain@example.com", json.dumps(facts), "a flagged fact is held back")
        held = [r for r in p.rows("fleet_reviews") if r["kind"] == "fact-conflict"]
        self.assertEqual(len(held), 1)
        self.assertEqual([c["kind"] for c in p.rows("fleet_changes")], ["new"] * 5)
        runs = {r["step"]: r["status"] for r in p.rows("fleet_runs")}
        self.assertEqual(runs, {step: "ok" for step in cli.PIPELINE})
        saved = json.loads((p.var / "CA" / "runs" / report["run_id"] / "report.json").read_text())
        self.assertEqual(set(saved["steps"]), set(cli.PIPELINE))

    def test_a_second_identical_run_writes_nothing(self):
        for worker in (False, True):
            with self.subTest(worker=worker), tempfile.TemporaryDirectory() as tmp:
                p = Pipeline(tmp, worker)
                first = p.run(DAY0, *baseline(DAY0))
                before = {t: p.rows(t) for t in REGISTRY}
                again = p.run(DAY0, *baseline(DAY0), run_id=first["run_id"])  # the same run again
                self.assertEqual({t: p.rows(t) for t in REGISTRY}, before)
                self.assertEqual(again["steps"]["ingest"]["counts"]["changed"], 0)
                self.assertEqual(again["steps"]["refresh"]["counts"]["changed"], 0)
                # A new run of the same input changes no registry value; only each fact's run_id (the run that
                # last retrieved it, set by the Worker and the SqliteSink alike) moves to the new run.
                second = p.run(DAY0, *baseline(DAY0))
                self.assertEqual({t: without_run_id(p.rows(t)) for t in REGISTRY},
                                 {t: without_run_id(rows) for t, rows in before.items()})
                self.assertEqual({f["run_id"] for f in p.rows("fleet_vessel_facts")}, {second["run_id"]})
                self.assertEqual(second["steps"]["refresh"]["counts"]["changed"], 0)

    def test_a_confirmed_flagged_fact_is_ingested(self):
        p = Pipeline(self.tmp.name)
        p.run(DAY0, *baseline(DAY0))
        db = p.db()
        db.execute("UPDATE fleet_reviews SET status='decided', decision_json='{\"action\":\"confirm\"}' WHERE kind='fact-conflict'")
        db.close()
        p.run(day(1), *baseline(day(1)))
        self.assertEqual(p.vessel("Sea Example")["email_business"], "captain@example.com")

    def test_a_new_scalar_value_supersedes_the_same_sources_old_fact(self):
        for worker in (False, True):
            with self.subTest(worker=worker), tempfile.TemporaryDirectory() as tmp:
                p = Pipeline(tmp, worker)
                p.run(DAY0, [], [psix("Tide Runner Test", "1000005", DAY0)])
                p.run(day(7), [], [psix("Fog Cutter Test", "1000005", day(7))])
                names = {f["value_json"]: f["superseded_by"] for f in p.rows("fleet_vessel_facts") if f["field"] == "name"}
                self.assertIsNotNone(names['"Tide Runner Test"'])
                self.assertIsNone(names['"Fog Cutter Test"'])

    def test_a_worker_snapshot_never_lets_a_lower_source_overwrite_the_name(self):
        p = Pipeline(self.tmp.name, worker=True)
        sea = landing("Sea Example", DAY0)
        p.run(DAY0, [sea], [psix("SEA EXAMPLE", "1000001", DAY0)])
        for n in range(1, 7):  # alternate: psix alone with another name, then both sources
            at = day(7 * n)
            p.run(at, [landing("Sea Example", at)] if n % 2 == 0 else [], [psix("Example Star", "1000001", at)])
            self.assertEqual(p.vessel("Sea Example")["name_norm"], "SEAEXAMPLE", n)
        self.assertEqual([c["kind"] for c in p.rows("fleet_changes")], ["new"], "no renamed back and forth")

    def test_a_new_vessel_never_takes_an_advisor_boat_slug_from_the_worker_snapshot(self):
        pages = [{"region": "CA", "cursor": "o:", "operators": [], "vessels": [], "reviews": [], "next": "v:",
                  "advisor_slugs": ["sea-example", "sea-example-morro-bay"]},
                 {"region": "CA", "cursor": "v:", "operators": [], "vessels": [], "reviews": [], "next": None}]
        snapshot = Snapshot.from_pages(pages)
        result = resolve(snapshot, [landing("Sea Example", DAY0)], ResolverConfig.from_region(REGION), DAY0)
        slugs = [op["slug"] for op in result.ops if op["op"] == "vessel.upsert"]
        self.assertEqual(len(slugs), 1)
        self.assertNotIn(slugs[0], snapshot.advisor_slugs)

    def test_worker_snapshot_pages_are_read_with_the_job_token(self):
        pages = [{"operators": [], "vessels": [], "reviews": [], "advisor_slugs": ["sea-example"], "next": "v:"},
                 {"operators": [], "vessels": [{"id": "a" * 32, "slug": "x", "name": "X", "name_norm": "X",
                                                "sources": []}], "reviews": [], "next": None}]
        seen = []

        class Response:
            def __init__(self, body):
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self, *args):
                return json.dumps(self.body).encode()

        class FakeWorker:
            base, user_agent = "https://skippercast.com", "test"

            def token(self):
                return "tok"

            def opener(self, request, timeout):
                seen.append((request.full_url, request.headers["Authorization"]))
                return Response(pages[len(seen) - 1])

        snapshot = load_snapshot(FakeWorker(), "CA")
        self.assertEqual(snapshot.advisor_slugs, frozenset({"sea-example"}))
        self.assertIsNone(snapshot.facts)
        self.assertEqual(seen, [("https://skippercast.com/api/fleet/jobs/snapshot?region=CA", "Bearer tok"),
                                ("https://skippercast.com/api/fleet/jobs/snapshot?region=CA&cursor=v%3A", "Bearer tok")])

    def test_candidates_round_trip_through_the_run_directory(self):
        cand = landing("Sea Example", DAY0, operator="Example Charters LLC", offerings=[("Half Day", 9500, "06:30")],
                       departures=["2026-10-10"])
        self.assertEqual(candidate_from_dict(json.loads(json.dumps(cand.as_dict()))), cand)


if __name__ == "__main__":
    unittest.main()
