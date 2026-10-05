"""Fleet sinks: ids, SqliteSink migrations and rules, WorkerSink on the CF-11 job contract, dry-run refusal, CLI.

The SqliteSink's full parity with the Worker's registry route is checked in
tests/test_fleet_sink_parity.mjs (both on the same operations).
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock
from urllib.request import ProxyHandler, build_opener

from skippercast.fleet import cli, config, ops
from skippercast.fleet.adapters import ADAPTERS, REGISTRY
from skippercast.fleet.runs import Run
from skippercast.fleet.sinks import BatchTooLarge, SinkError, SinkRefused, SqliteSink, WorkerSink, open_sink
from tests._support import ROOT

T0, T1 = "2026-10-05T09:47:00Z", "2026-10-12T09:47:00.000Z"
OPERATOR = "op-test-0000000000000001"


def vid(n):
    return ops.vessel_id("CA", f"name-port:test-boat-{n}|morro-bay")


def vessel(n=1, **extra):
    return {"op": "vessel.upsert", "id": vid(n), "creation_key": f"name-port:test-boat-{n}|morro-bay",
            "slug": f"test-boat-{n}", "name": f"Test Boat {n}", "name_norm": f"TESTBOAT{n}", "port_id": "morro-bay",
            "waters_json": ["ocean", "bay"], "length_ft": 58.5, "status": "active", "profile_status": "listed",
            "completeness": 0.5, "first_seen_at": T0, "last_seen_at": T0, **extra}


def fact(n=1, **extra):
    return {"op": "fact.upsert", "vessel_id": vid(n), "field": "mmsi", "value_json": str(366000000 + n),
            "source_id": "fcc-uls", "source_url": f"https://registry.example.gov/vessel/{n}", "method": "registry",
            "confidence": 0.9, "rights": "public-domain", "retrieved_at": T0, **extra}


class IdTests(unittest.TestCase):
    def test_ids_match_the_typescript_implementation(self):
        # Computed by running server/fleet/ids.ts with node (CF-10 PR).
        value = {"b": [2, {"d": 1, "c": "é", "e": 58.5}], "a": None, "n": 30.0}
        self.assertEqual(ops.canonical_json(value), '{"a":null,"b":[2,{"c":"é","d":1,"e":58.5}],"n":30}')
        self.assertEqual(ops.vessel_id("CA", "uscg:1234567"), "04b230cc8a0756197411670e0c63ff49")
        self.assertEqual(ops.value_key(value), "2a7f401a72bbed57")
        self.assertEqual(ops.fact_id("a" * 32, "length_ft", "fcc-uls", "https://registry.example.gov/vessel/1",
                                     ops.value_key(65.0)), "5e9fb5a690509eca9b365edcf75ba1bc")
        self.assertEqual(ops.offering_id("a" * 32, "HALFDAY", "summer"), "52502e83da360cda9abd0930619b5b5e")
        self.assertEqual(ops.departure_id("b" * 32, "2026-10-10", "06:30"), "6fae240b0ea8f4b62cf4ebfb2595dcd4")
        self.assertEqual(ops.review_id("merge", "fcc-uls:WDZ0000"), "02a0ed814b135fc2a95526e313a128c2")
        self.assertEqual(ops.change_id("a" * 32, "new", ops.canonical_json({"name": "Test Boat 1"})),
                         "d1980f986efa397a1210635812f93924")

    def test_wire_form(self):
        out = ops.wire(vessel(length_ft=60.0, last_seen_at="2026-10-12T09:47:00.123456Z"))
        self.assertEqual((out["length_ft"], type(out["length_ft"])), (60, int))
        self.assertEqual((out["first_seen_at"], out["last_seen_at"]), ("2026-10-05T09:47:00.000Z", "2026-10-12T09:47:00.123Z"))
        self.assertEqual(out["waters_json"], ["ocean", "bay"])  # a JSON value, not a string


class SqliteSinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = SqliteSink(Path(self.tmp.name) / "CA.sqlite", "CA", "run-1")

    def tearDown(self):
        self.sink.close()
        self.tmp.cleanup()

    def test_creates_every_fleet_table_in_journal_order(self):
        schema = (ROOT / "db" / "schema.ts").read_text(encoding="utf-8")
        expected = set(re.findall(r"sqliteTable\('(fleet_[a-z_]+)'", schema))
        tables = {name for (name,) in self.sink.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(expected)
        self.assertLessEqual(expected, tables)
        journal = json.loads((ROOT / "drizzle" / "meta" / "_journal.json").read_text())
        applied = [tag for (tag,) in self.sink.db.execute("SELECT tag FROM _skippercast_migrations ORDER BY rowid")]
        self.assertEqual(applied, [e["tag"] for e in sorted(journal["entries"], key=lambda e: e["idx"])])
        self.sink.migrate(ROOT)  # reopening applies nothing twice

    def test_round_trip_is_idempotent_and_sets_worker_columns(self):
        batch = [vessel(), fact(), {"op": "review.open", "kind": "merge", "fingerprint": "fcc-uls:WDZ0000", "opened_at": T0}]
        first = self.sink.apply(batch)
        self.assertEqual((first["ops"], first["changed"]), (3, 3))
        self.assertEqual(self.sink.apply(batch)["changed"], 0)
        row = self.sink.db.execute("SELECT region, created_at, first_seen_at, waters_json FROM fleet_vessels").fetchone()
        self.assertEqual(row[0], "CA")
        self.assertRegex(row[1], r"\.\d{3}Z$")
        self.assertEqual(row[2:], ("2026-10-05T09:47:00.000Z", '["ocean","bay"]'))
        self.assertEqual(self.sink.db.execute("SELECT id, run_id, status FROM fleet_reviews").fetchone(),
                         (ops.review_id("merge", "fcc-uls:WDZ0000"), "run-1", "open"))

    def test_guards(self):
        self.sink.apply([vessel(), fact()])
        self.sink.db.execute("""UPDATE fleet_vessels SET pinned_json='{"name":"admin"}'""")
        self.sink.apply([vessel(name="Renamed", length_ft=61, last_seen_at=T1)])
        self.assertEqual(self.sink.db.execute("SELECT name, length_ft FROM fleet_vessels").fetchone(), ("Test Boat 1", 61))
        self.sink.apply([vessel(length_ft=40, first_seen_at="2026-09-01T00:00:00Z", last_seen_at="2026-09-01T00:00:00Z")])
        self.assertEqual(self.sink.db.execute("SELECT length_ft, first_seen_at, last_seen_at FROM fleet_vessels").fetchone(),
                         (61, "2026-09-01T00:00:00.000Z", T1))  # older replay: only first_seen_at moves back

    def test_worker_rules_reject_with_every_index(self):
        bad = [vessel(), fact(source_url="admin:user-1"), fact(method="admin"), vessel(2, region="CA"),
               {"op": "review.open", "kind": "merge", "opened_at": T0},
               {"op": "operator.upsert", "id": OPERATOR, "slug": "x-landing", "name": "X"}, fact(9)]
        with self.assertRaises(SinkError) as caught:
            self.sink.apply(bad)
        self.assertEqual([(e["index"], e["error"].split(":")[0]) for e in caught.exception.errors],
                         [(1, "source_url"), (2, "method"), (3, "region"), (4, "fingerprint"), (5, "seen_at"), (6, "vessel_id")])
        self.assertEqual(self.sink.db.execute("SELECT count(*) FROM fleet_vessels").fetchone(), (0,))


class _Worker(BaseHTTPRequestHandler):
    """A fake of POST /api/fleet/jobs/registry with the envelope checks and replies of server/fleet/jobs.ts."""

    def do_POST(self):
        data = self.rfile.read(int(self.headers["Content-Length"]))
        body = json.loads(data)
        self.server.calls.append((self.path, self.headers["Authorization"], body))
        extra = set(body) - {"region", "run_id", "batch", "ops"}
        if self.server.replies:
            status, reply = self.server.replies.pop(0)
        elif extra:
            status, reply = 400, {"error": f"unknown field: {sorted(extra)[0]}"}
        elif len(data) > 1024 * 1024 or len(body["ops"]) > 500:
            status, reply = 413, {"error": "at most 500 operations per request"}
        else:
            kinds = {}
            for op in body["ops"]:
                kinds.setdefault(op["op"], {"ops": 0, "changed": 0})
                kinds[op["op"]]["ops"] += 1
                kinds[op["op"]]["changed"] += 1
            status, reply = 200, {"ok": True, "run_id": body["run_id"], "batch": body["batch"], "ops": len(body["ops"]),
                                  "changed": len(body["ops"]), "counts": kinds}
        out = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


class WorkerSinkTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Worker)
        self.server.calls, self.server.replies = [], []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.tmp = tempfile.TemporaryDirectory()
        self.run = Run("CA", var=Path(self.tmp.name))
        self.slept = []
        self.sink = WorkerSink(f"http://127.0.0.1:{self.server.server_address[1]}", "CA", self.run.id, self.run.next_batch,
                               token_source=lambda: "oidc-token", sleep=self.slept.append,
                               opener=build_opener(ProxyHandler({})).open)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def test_batches_on_the_job_envelope_numbered_across_the_run(self):
        batch = [vessel(n) for n in range(1, 601)]
        result = self.sink.apply(batch)
        self.assertEqual((result["ops"], result["changed"], result["counts"]),
                         (600, 600, {"vessel.upsert": {"ops": 600, "changed": 600}}))
        self.sink.apply([vessel()])
        self.assertEqual([(len(c[2]["ops"]), c[2]["batch"]) for c in self.server.calls], [(500, 0), (100, 1), (1, 2)])
        path, auth, body = self.server.calls[0]
        self.assertEqual((path, auth), ("/api/fleet/jobs/registry", "Bearer oidc-token"))
        self.assertEqual(set(body), {"region", "run_id", "batch", "ops"})
        self.assertEqual(body["ops"][0], ops.wire(batch[0]))
        self.assertEqual(body["ops"][0]["last_seen_at"], "2026-10-05T09:47:00.000Z")
        self.assertTrue(self.sink.audience.endswith("/api/fleet/jobs"))

    def test_retries_transient_status_and_maps_every_error_index(self):
        self.server.replies = [(503, {"error": "busy"})]
        self.assertEqual(self.sink.apply([vessel()])["changed"], 1)
        self.assertEqual(self.slept, [2.0])
        errors = [{"index": 3, "op": "fact.upsert", "error": "vessel_id: unknown vessel in this region"},
                  {"index": 7, "op": "fact.upsert", "error": "vessel_id: unknown vessel in this region"}]
        self.server.replies = [(200, {"changed": 0, "counts": {}}), (400, {"error": "invalid operations", "errors": errors})]
        with self.assertRaises(SinkError) as caught:
            self.sink.apply([vessel(n) for n in range(1, 511)])
        self.assertEqual([e["index"] for e in caught.exception.errors], [503, 507])

    def test_413_is_a_batching_bug_and_never_retried(self):
        self.server.replies = [(413, {"error": "body too large"})]
        with self.assertRaises(BatchTooLarge):
            self.sink.apply([vessel()])
        self.assertEqual((len(self.server.calls), self.slept), (1, []))

    def test_invalid_operations_are_refused_before_sending(self):
        with self.assertRaises(SinkError) as caught:
            self.sink.apply([vessel(), fact(source_url="admin:user-1"), fact(method="admin")])
        self.assertEqual([e["index"] for e in caught.exception.errors], [1, 2])
        self.assertEqual(self.server.calls, [])

    def test_https_required_outside_loopback(self):
        with self.assertRaises(SinkRefused):
            WorkerSink("http://skippercast.com", "CA", "run-1", lambda: 0, token_source=lambda: "t")


class RegistryAndCliTests(unittest.TestCase):
    def test_config_uses_the_adapter_registry(self):
        self.assertIs(config.ADAPTERS, ADAPTERS)
        self.assertEqual(ADAPTERS, frozenset(REGISTRY))

    def test_dry_run_region_refuses_worker_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("XX", var=Path(tmp))
            region = SimpleNamespace(id="XX", status="dry-run")
            with self.assertRaises(SinkRefused):
                open_sink("worker", region, run, base="https://skippercast.com")
            open_sink("staging", region, run).close()

    def test_registered_steps_record_state_under_fleet_var(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict("os.environ", {"SKIPPERCAST_FLEET_VAR": tmp}):
            run = cli.run_step("discover", "CA", "staging")
            state = json.loads((run.dir / "state.json").read_text())
            self.assertEqual(run.dir, Path(tmp) / "CA" / "runs" / run.id)
            self.assertEqual(state["steps"]["discover"]["status"], "done")
            self.assertTrue((Path(tmp) / "staging" / "CA.sqlite").exists())
            again = cli.run_step("resolve", "CA", "staging", run.id)
            self.assertEqual(set(again.state["steps"]), {"discover", "resolve"})
        for step in ("discover", "resolve", "enrich-code", "plan-agent", "ingest", "refresh", "run"):
            self.assertIn(step, cli.STEPS)
        with mock.patch.object(cli.profile, "main", return_value=0) as validate:
            self.assertEqual(cli.main(["validate-profile", "a.json"]), 0)
        validate.assert_called_once_with(["a.json"])


if __name__ == "__main__":
    unittest.main()
