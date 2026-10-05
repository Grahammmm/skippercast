"""The OSINT agent step: plan-agent manifests and ``ingest --profiles`` (design section 8, CF-20).

Synthetic throughout: the registry is test_fleet_ingest's invented fleet on the
SqliteSink, and every profile is built from the synthetic fixtures in
tests/fixtures/fleet/profiles/ (invented boats, 555-01XX phones, handles from
catalog/advisor/fixture-handles.json, 999xxxxxx MMSIs, .example URLs). Profile
ingest validates against the JSON Schema, so those tests need the optional
jsonschema package and skip without it (the survey-science CI job runs them).
"""
from contextlib import redirect_stderr
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from skippercast import validate
from skippercast.fleet import agent, cli, ops, profile
from skippercast.fleet.adapters.base import RunContext
from skippercast.fleet.resolve import Snapshot
from skippercast.fleet.runs import Run
from skippercast.fleet.sinks import SqliteSink
from tests._support import FIXTURES
from tests.unit.test_fleet_ingest import DAY0, REGION, REGISTRY, Pipeline, baseline, day, without_run_id

PROFILES = FIXTURES / "fleet/profiles"
SEA, KELP = ops.vessel_id("CA", "uscg:1000001"), ops.vessel_id("CA", "uscg:1000002")
BOAT_KEYS = {"vessel_id", "name", "aliases", "port", "landing", "vessel_class_hint", "known", "missing", "refresh"}
MANIFEST_KEYS = {"manifest_version", "region", "run_id", "batch_id", "created_at", "output_dir", "output_file", "schema",
                 "validate", "policy", "boats"}


NEEDS_JSONSCHEMA = unittest.skipUnless(
    validate.available(), "jsonschema not installed (pip install -r requirements-test.txt); the survey-science CI job runs these")


def party(vessel_id=SEA, name="Sea Example", run_id="20261006T081700Z-a1b2c3", at="2026-10-06T08:20:00Z", **boat):
    """The synthetic party-boat fixture re-pointed at a staged vessel; ``boat`` replaces leaves (None clears one)."""
    doc = json.loads((PROFILES / "party.json").read_text(encoding="utf-8"))
    doc.update(vessel_id=vessel_id, run_id=run_id)
    text = json.dumps(doc).replace("2026-10-04T10:20:00Z", at)
    doc = json.loads(text)
    doc["boat"]["name"]["value"] = name
    for key, value in boat.items():
        doc["boat"][key] = value
    return doc


def leaf(value, at="2026-10-06T08:20:00Z", method="page", confidence=0.9, url="https://kelp-test-charters.example/"):
    return {"value": value, "source_url": url, "retrieved_at": at, "method": method, "confidence": confidence}


def kelp(run_id="20261006T081700Z-a1b2c3", at="2026-10-06T08:20:00Z", **boat):
    mmsi = leaf("999000102", at)
    leaves = {"mmsi": mmsi, "call_sign": leaf("EXAMPLE2", at), "phone_business": leaf("+18055550145", at), **boat}
    doc = party(KELP, "Kelp Test", run_id, at, **leaves)
    doc["boat"]["ais"]["mmsi"] = dict(mmsi, source_url="https://ais.example/statics/999000102")
    return doc


def write(folder, name, doc):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")


class Registry(Pipeline):
    """test_fleet_ingest's pipeline plus the two CF-20 steps on the same staging database."""

    def step(self, step, at, options, run_id=None):
        self.count += 1
        run = Run("CA", run_id or at.replace("-", "").replace(":", "")[:15] + f"Z-{self.count:06x}", var=self.var)
        sink = SqliteSink(self.var / "CA.sqlite", "CA", run.id)
        ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: at)
        try:
            report = cli.execute(run, ctx, sink, (step,), {step: {"load": self.load, **options}})
        finally:
            sink.close()
        return run, report["steps"][step]

    def ingest(self, at, folder, run_id=None):
        return self.step("ingest", at, {"profiles": folder}, run_id)

    def plan(self, at, mode="full"):
        run, result = self.step("plan-agent", at, {"mode": mode})
        return [json.loads(p.read_text()) for p in sorted((run.dir / "manifests").glob("*.json"))], result, run

    def facts(self, vessel_id, field, source="osint"):
        return [f for f in self.rows("fleet_vessel_facts")
                if f["vessel_id"] == vessel_id and f["field"] == field and f["source_id"] == source]


def vessel_row(i, **extra):
    row = {"id": f"{i:032x}", "slug": f"boat-{i}", "name": f"Boat {i}", "name_norm": f"BOAT{i}", "status": "active",
           "port_id": "morro-bay", "landing_id": None, "vessel_class": "six-pack", "website": "https://boat.example/",
           "mmsi": f"999000{i:03d}", "passengers_max": 6, "call_sign": None, "uscg_doc": None, "aliases": [],
           "offerings": [{"name": "Half Day", "status": "active"}], "last_profiled_at": None,
           "first_seen_at": DAY0, "last_seen_at": DAY0}
    row.update(extra)
    return row


class SelectionTests(unittest.TestCase):
    NOW = "2026-10-11T10:17:00Z"

    def test_new_stale_and_missing_vessels_are_selected_in_order(self):
        recent, old = "2026-10-01T00:00:00Z", "2026-07-01T00:00:00Z"
        vessels = [vessel_row(1, last_profiled_at=recent),                        # complete, fresh: not selected
                   vessel_row(2, last_profiled_at=recent, mmsi=None),             # missing only
                   vessel_row(3, last_profiled_at=old),                           # stale
                   vessel_row(4),                                                 # new
                   vessel_row(5, last_profiled_at=recent, offerings=[{"name": "Half Day", "status": "retired"}]),
                   vessel_row(6, status="excluded"), vessel_row(7, status="sold"),
                   vessel_row(8, removal_requested_at="2026-09-01T00:00:00.000Z"),
                   vessel_row(9, last_profiled_at="2026-05-01T00:00:00Z")]       # staler
        full = agent.select(vessels, self.NOW, 60, "full")
        self.assertEqual([(v["id"][-1], r) for v, r in full],
                         [("4", ["new"]), ("9", ["stale"]), ("3", ["stale"]), ("2", ["missing"]), ("5", ["missing"])])
        refresh = agent.select(vessels, self.NOW, 60, "refresh")
        self.assertEqual([v["id"][-1] for v, _r in refresh], ["4", "9", "3"])
        with self.assertRaises(ValueError):
            agent.select(vessels, self.NOW, 60, "everything")

    def test_batches_hold_at_most_twenty_boats_and_a_rerun_drops_stale_manifests(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("CA", "20261011T101700Z-abcdef", var=Path(tmp))
            vessels = [vessel_row(i) for i in range(1, 46)]
            ctx = RunContext(region=REGION, net=None, run_dir=run.dir, clock=lambda: self.NOW)
            counts = agent.plan_agent(ctx, None, load=lambda sink, region: Snapshot(vessels))
            names = sorted(p.name for p in (run.dir / "manifests").iterdir())
            self.assertEqual(names, ["batch-001.json", "batch-002.json", "batch-003.json"])
            docs = [json.loads((run.dir / "manifests" / n).read_text()) for n in names]
            self.assertEqual([len(d["boats"]) for d in docs], [20, 20, 5])
            self.assertEqual((counts["selected"], counts["batches"], counts["new"]), (45, 3, 45))
            doc = docs[0]
            self.assertEqual(set(doc), MANIFEST_KEYS)
            self.assertEqual((doc["manifest_version"], doc["region"], doc["run_id"], doc["batch_id"], doc["created_at"]),
                             (1, "CA", run.id, "batch-001", self.NOW))
            self.assertEqual(doc["output_dir"], str(run.dir / "profiles"))
            self.assertEqual(doc["policy"]["cache_dir"], str(Path(tmp) / "CA" / "http-cache" / "agent"))
            self.assertEqual(doc["policy"]["off_limits"], "catalog/fleet/off-limits.json")
            self.assertTrue((run.dir / "profiles").is_dir())
            agent.plan_agent(ctx, None, load=lambda sink, region: Snapshot(vessels[:15]))
            self.assertEqual(sorted(p.name for p in (run.dir / "manifests").iterdir()), ["batch-001.json"])
            with self.assertRaises(ValueError):
                agent.manifests("CA", run.id, run.dir, self.NOW, [], batch_size=21)

    def test_a_profiled_boat_carries_its_refresh_focus(self):
        vessel = vessel_row(3, last_profiled_at="2026-07-01T00:00:00.000Z", mmsi=None,
                            aliases=[{"alias": "Boat Three", "alias_norm": "BOATTHREE", "kind": "spelling"}])
        (boat,) = agent.manifests("CA", "20261011T101700Z-abcdef", Path("/var/fleet/CA/runs/20261011T101700Z-abcdef"),
                                  self.NOW, agent.select([vessel], self.NOW, 60))[0]["boats"]
        self.assertEqual(boat, {"vessel_id": vessel["id"], "name": "Boat 3", "aliases": ["Boat Three"],
                                "port": "morro-bay", "landing": None, "vessel_class_hint": "six-pack",
                                "known": {"website": "https://boat.example/"}, "missing": ["mmsi"],
                                "refresh": {"last_profiled_at": "2026-07-01T00:00:00.000Z",
                                            "focus": ["booking_url", "trip_types"]}})


class ManifestFromRegistryTests(unittest.TestCase):
    def test_manifests_hold_only_snapshot_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Registry(tmp)
            p.run(DAY0, *baseline(DAY0))
            docs, result, run = p.plan(day(1))
            self.assertEqual(result["status"], "ok")
            stored = {v["id"]: v for v in p.rows("fleet_vessels")}
            aliases = {}
            for a in p.rows("fleet_aliases"):
                aliases.setdefault(a["vessel_id"], set()).add(a["alias"])
            boats = [b for d in docs for b in d["boats"]]
            self.assertEqual(sorted(b["vessel_id"] for b in boats), sorted(stored), "every boat is new")
            for boat in boats:
                row = stored[boat["vessel_id"]]
                self.assertLessEqual(set(boat), BOAT_KEYS)
                self.assertEqual((boat["name"], boat["port"], boat["landing"], boat["vessel_class_hint"]),
                                 (row["name"], row["port_id"], row["landing_id"], row["vessel_class"]))
                self.assertEqual(set(boat["aliases"]), aliases.get(row["id"], set()))
                self.assertTrue(all(row[k] == v for k, v in boat["known"].items()), boat)
                self.assertLessEqual(set(boat["missing"]), set(agent.TARGET_FIELDS))
            text = (run.dir / "manifests" / "batch-001.json").read_text()
            self.assertNotIn("+1805", text, "contact values stay out of manifests")
            self.assertNotIn("@", text)
            plan = json.loads((run.dir / "agent-plan.json").read_text())
            self.assertEqual(plan["counts"]["selected"], 5)


@NEEDS_JSONSCHEMA
class ProfileIngestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = Registry(self.tmp.name)
        self.p.run(DAY0, *baseline(DAY0))
        self.dir = Path(self.tmp.name) / "profiles"

    def test_invalid_profiles_are_refused_and_listed_and_valid_ones_ingest(self):
        before = self.p.vessel("Sea Example")
        write(self.dir, f"{SEA}.json", party())
        write(self.dir, "invalid.json", (PROFILES / "invalid.json").read_text(encoding="utf-8"))
        write(self.dir, "unknown.json", party(vessel_id="f" * 32))
        write(self.dir, "other-region.json", dict(party(), region="OR"))
        write(self.dir, "broken.json", "{not json")
        run, result = self.p.ingest(day(1), self.dir)
        self.assertEqual(result["status"], "partial")
        self.assertEqual((result["counts"]["files"], result["counts"]["ingested"], result["counts"]["refused"]), (5, 1, 4))
        report = json.loads((run.dir / "profiles-ingest.json").read_text())
        self.assertEqual(report["ingested"], [f"{SEA}.json"])
        refused = {r["file"]: r["errors"] for r in report["refused"]}
        self.assertEqual(set(refused), {"invalid.json", "unknown.json", "other-region.json", "broken.json"})
        self.assertTrue(any("off-limits" in e for e in refused["invalid.json"]), refused["invalid.json"])
        self.assertIn("no vessel", refused["unknown.json"][0])
        self.assertIn("region", refused["other-region.json"][0])
        self.assertTrue(refused["broken.json"][0].startswith("JSONDecodeError"))

        sea = self.p.vessel("Sea Example")
        self.assertEqual((sea["mmsi"], sea["passengers_max"], sea["vessel_class"]), ("999000101", 40, "inspected-party"))
        self.assertEqual((sea["uscg_doc"], sea["name"]), ("1000001", "Sea Example"), "higher-priority sources keep theirs")
        self.assertEqual(sea["last_seen_at"], before["last_seen_at"], "a profile does not list the vessel")
        self.assertEqual(sea["last_profiled_at"], "2026-10-06T08:17:00.000Z")
        facts = [f for f in self.p.rows("fleet_vessel_facts") if f["source_id"] == "osint"]
        self.assertTrue(facts and all(f["vessel_id"] == SEA and f["rights"] == "facts-only" for f in facts))
        self.assertTrue(all(f["confidence"] <= 0.8 for f in facts if f["method"] in ("search", "inference")))
        self.assertEqual(self.p.facts(SEA, "ais.match_method")[0]["confidence"], 0.8, "inference is capped at 0.8")
        self.assertFalse([f for f in facts if f["field"].startswith("reputation.google")], "Places rating never stored")
        self.assertEqual(len(self.p.facts(SEA, "trip_types[]")), 1)
        offering = next(o for o in self.p.rows("fleet_offerings") if o["name"] == "3/4 Day Rockfish")
        self.assertEqual((offering["trip_type"], offering["price_cents"], offering["departs_local"],
                          json.loads(offering["target_species_json"])), ("three-quarter-day", 12000, "06:30",
                                                                           ["rockfish", "lingcod"]))
        self.assertEqual(offering["updated_at"], "2026-10-06T08:17:00.000Z")

    def test_reingesting_the_same_profiles_changes_nothing(self):
        for worker in (False, True):
            with self.subTest(worker=worker), tempfile.TemporaryDirectory() as tmp:
                p = Registry(tmp, worker)
                p.run(DAY0, *baseline(DAY0))
                folder = Path(tmp) / "profiles"
                write(folder, f"{SEA}.json", party())
                write(folder, f"{KELP}.json", kelp())
                six = json.loads((PROFILES / "six-pack.json").read_text(encoding="utf-8"))
                write(folder, "six.json", dict(six, vessel_id=ops.vessel_id("CA", "uscg:1000005")))
                run, first = p.ingest(day(1), folder)
                self.assertEqual(first["status"], "ok", first)
                self.assertGreater(first["counts"]["changed"], 0)
                before = {t: p.rows(t) for t in REGISTRY}
                _run, again = p.ingest(day(1), folder, run_id=run.id)
                self.assertEqual(again["counts"]["changed"], 0)
                self.assertEqual({t: p.rows(t) for t in REGISTRY}, before)
                _run, later = p.ingest(day(9), folder)  # a later run of the same profiles
                self.assertEqual({t: without_run_id(p.rows(t)) for t in REGISTRY},
                                 {t: without_run_id(rows) for t, rows in before.items()})
                conflict = [r for r in p.rows("fleet_reviews") if r["kind"] == "fact-conflict"
                            and json.loads(r["candidate_json"])["source_id"] == "osint"]
                self.assertEqual(len(conflict), 1, "the six-pack profile's length conflict opens one review")
                self.assertEqual(json.loads(conflict[0]["candidate_json"])["field"], "length_ft")

    def test_a_missing_value_in_a_newer_profile_does_not_supersede_an_older_fact(self):
        for worker in (False, True):
            with self.subTest(worker=worker), tempfile.TemporaryDirectory() as tmp:
                p, folder = Registry(tmp, worker), Path(tmp) / "profiles"
                p.run(DAY0, *baseline(DAY0))
                write(folder, f"{KELP}.json", kelp())
                p.ingest(day(1), folder)
                self.assertEqual(p.vessel("Kelp Test")["phone_business"], "+18055550145")
                newer = kelp("20261020T081700Z-d4e5f6", "2026-10-20T08:20:00Z", phone_business=None,
                             passengers_max=leaf(42, "2026-10-20T08:20:00Z"))
                write(folder, f"{KELP}.json", newer)
                _run, result = p.ingest(day(16), folder)
                self.assertEqual(result["status"], "ok", result)
                (phone,) = p.facts(KELP, "phone_business")
                self.assertIsNone(phone["superseded_at"], "absence is not evidence")
                row = p.vessel("Kelp Test")
                self.assertEqual((row["phone_business"], row["passengers_max"]), ("+18055550145", 42))
                passengers = {json.loads(f["value_json"]): f["superseded_by"] for f in p.facts(KELP, "passengers_max")}
                self.assertIsNotNone(passengers[40], "a new value from the same source supersedes the old one")
                self.assertIsNone(passengers[42])
                self.assertEqual(row["last_profiled_at"], "2026-10-20T08:17:00.000Z")

    def test_one_profile_per_vessel_the_newest_wins(self):
        write(self.dir, "a.json", kelp("20261006T081700Z-a1b2c3"))
        write(self.dir, "b.json", kelp("20261008T081700Z-a1b2c3", "2026-10-08T08:20:00Z",
                                       passengers_max=leaf(44, "2026-10-08T08:20:00Z")))
        run, result = self.p.ingest(day(4), self.dir)
        report = json.loads((run.dir / "profiles-ingest.json").read_text())
        self.assertEqual(report["ingested"], ["b.json"])
        self.assertEqual(report["skipped"], [{"file": "a.json", "reason": "a newer profile of the same vessel: b.json"}])
        self.assertEqual(self.p.vessel("Kelp Test")["passengers_max"], 44)

    def test_a_webmail_address_is_held_for_review(self):
        write(self.dir, f"{KELP}.json", kelp(email_business=leaf("captain@example.com")))
        with mock.patch.object(profile, "WEBMAIL_DOMAINS", frozenset({"example.com"})):
            _run, result = self.p.ingest(day(1), self.dir)
        self.assertEqual(result["counts"]["held"], 1)
        self.assertIsNone(self.p.vessel("Kelp Test")["email_business"])
        self.assertFalse(self.p.facts(KELP, "email_business"))

    def test_an_existing_trip_is_never_overwritten_or_duplicated(self):
        trip = deepcopy(party()["boat"]["trip_types"][0])
        trip["name"]["value"], trip["price_usd"]["value"] = "Full Day", 999
        write(self.dir, f"{KELP}.json", kelp(trip_types=[trip]))
        self.p.ingest(day(1), self.dir)
        self.assertEqual([(o["name"], o["price_cents"]) for o in self.p.rows("fleet_offerings") if o["vessel_id"] == KELP],
                         [("Full Day", 15000)])

    def test_an_impossible_or_future_time_refuses_only_that_profile(self):
        later = "2026-10-07T08:20:00Z"  # after the ingest clock, day(1)
        cases = {"bad-run.json": party(run_id="20269999T999999Z-x"),
                 "bad-date.json": kelp(passengers_max=leaf(44, "2026-02-30T08:20:00Z")),
                 "future-run.json": party(run_id="20991006T081700Z-a1b2c3"),
                 "future-leaf.json": kelp(passengers_max=leaf(44, later))}
        for name, doc in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                p, folder = Registry(tmp), Path(tmp) / "profiles"
                p.run(DAY0, *baseline(DAY0))
                write(folder, name, doc)
                other = kelp() if doc["vessel_id"] == SEA else party()
                write(folder, "valid.json", other)
                run, result = p.ingest(day(1), folder)
                self.assertEqual((result["status"], result["counts"]["ingested"], result["counts"]["refused"]),
                                 ("partial", 1, 1))
                report = json.loads((run.dir / "profiles-ingest.json").read_text())
                (refused,) = report["refused"]
                self.assertEqual(refused["file"], name)
                self.assertTrue(any("valid UTC time" in e or "later than the run clock" in e for e in refused["errors"]),
                                refused)
                profiled = {v["id"]: v["last_profiled_at"] for v in p.rows("fleet_vessels")}
                self.assertEqual(profiled[other["vessel_id"]], "2026-10-06T08:17:00.000Z")
                self.assertIsNone(profiled[doc["vessel_id"]], "a refused profile moves nothing forward")

    def test_a_missing_profiles_directory_fails_the_step(self):
        with self.assertRaises(FileNotFoundError):
            self.p.ingest(day(1), self.dir / "absent")


class ProfileFactsTests(unittest.TestCase):
    def test_each_provenance_object_maps_to_an_osint_fact(self):
        mapped = profile.profile_facts(party())
        fields = {f.field for f in mapped.facts}
        self.assertTrue({"name", "mmsi", "operator", "waters", "trip_types[]", "captains[]", "photos[]",
                         "social.instagram.handle", "ais.mmsi", "reputation.other[]"} <= fields, fields)
        self.assertFalse({"home_marina", "reputation.google_rating", "reputation.google_reviews"} & fields)
        doc = party()
        other = doc["boat"]["reputation"]["other"]
        other.append(dict(other[0], value=4.7, source_url="https://www.google.com/maps/place/placeholder-example"))
        other.append(dict(other[0], value=4.8, source_url="https://maps.googleapis.com/maps/api/place/x"))
        values = [f.value for f in profile.profile_facts(doc).facts if f.field == "reputation.other[]"]
        self.assertEqual(values, [4.5], "a number read off a Google host is never stored")
        self.assertTrue(all(f.source_id == "osint" and f.rights == "facts-only" for f in mapped.facts))
        (waters,) = [f for f in mapped.facts if f.field == "waters"]
        self.assertEqual((waters.value, waters.method, waters.confidence), (["ocean", "bay"], "inference", 0.6))
        self.assertEqual(mapped.profiled_at, "2026-10-06T08:17:00Z")
        self.assertEqual(profile.profiled_at(dict(party(), run_id="manual")), "2026-10-06T08:20:00Z")


class CliTests(unittest.TestCase):
    def test_options_reach_their_step(self):
        with mock.patch.object(cli, "run_step", side_effect=ValueError("stop")) as run_step, \
                redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["plan-agent", "--region", "CA", "--mode", "refresh"]), 2)
            self.assertEqual(run_step.call_args.args[-1], {"plan-agent": {"mode": "refresh"}})
            cli.main(["ingest", "--region", "CA", "--profiles", "some/dir"])
            self.assertEqual(run_step.call_args.args[-1], {"ingest": {"profiles": Path("some/dir")}})
            for argv in (["ingest", "--region", "CA", "--mode", "full"], ["plan-agent", "--region", "CA", "--profiles", "x"]):
                with self.assertRaises(SystemExit):
                    cli.main(argv)
        self.assertIs(cli.STEPS["plan-agent"], agent.plan_agent)


if __name__ == "__main__":
    unittest.main()
