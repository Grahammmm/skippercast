"""Fleet sinks: SqliteSink migrations and upserts, WorkerSink request shape, dry-run refusal, CLI steps."""
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

from skippercast.fleet import cli, config
from skippercast.fleet.adapters import ADAPTERS, REGISTRY
from skippercast.fleet.runs import Run
from skippercast.fleet.sinks import MAX_OPS, SinkError, SinkRefused, SqliteSink, WorkerSink, open_sink
from tests._support import ROOT

T = "2026-10-01T00:00:00Z"


def vessel(ident="v1", name="Example One", **extra):
    return {"kind": "vessel.upsert", "row": {"id": ident, "region": "CA", "slug": ident, "name": name,
                                             "name_norm": name.upper().replace(" ", ""), "first_seen_at": T,
                                             "last_seen_at": T, "created_at": T, "updated_at": T, **extra}}


def fact(ident="f1", source_url="https://reports.example.org/boat/1"):
    return {"kind": "fact.upsert", "row": {
        "id": ident, "vessel_id": "v1", "field": "length_ft", "value_json": "65", "value_key": "65",
        "source_id": "teck-reports", "source_url": source_url, "method": "parse", "confidence": 0.9,
        "rights": "facts-only", "retrieved_at": T, "first_seen_at": T, "last_seen_at": T}}


class SqliteSinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.sink = SqliteSink(Path(self.tmp.name) / "CA.sqlite")

    def tearDown(self):
        self.sink.close()
        self.tmp.cleanup()

    def test_creates_every_fleet_table_from_committed_migrations(self):
        schema = (ROOT / "db" / "schema.ts").read_text(encoding="utf-8")
        expected = set(re.findall(r"sqliteTable\('(fleet_[a-z_]+)'", schema))
        tables = {name for (name,) in self.sink.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue(expected)
        self.assertLessEqual(expected, tables)
        self.sink.migrate(ROOT / "drizzle")  # reopening applies nothing twice

    def test_round_trip_is_idempotent(self):
        ops = [vessel(), fact(), {"kind": "alias.upsert", "row": {
            "vessel_id": "v1", "alias_norm": "EXONE", "alias": "Ex One", "kind": "spelling",
            "first_seen_at": T, "last_seen_at": T}}]
        self.assertEqual(self.sink.apply(ops), {"operations": 3, "changes": 3})
        self.assertEqual(self.sink.apply(ops), {"operations": 3, "changes": 0})
        self.assertEqual(self.sink.apply([vessel(name="Example Two")])["changes"], 1)
        self.assertEqual(self.sink.db.execute("SELECT name FROM fleet_vessels").fetchall(), [("Example Two",)])

    def test_decided_review_is_never_reopened(self):
        review = {"kind": "review.open", "row": {"id": "r1", "region": "CA", "kind": "merge", "score": 0.7,
                                                 "opened_at": T}}
        self.sink.apply([review])
        self.sink.db.execute("UPDATE fleet_reviews SET status='rejected', decided_at=?", (T,))
        review["row"]["score"] = 0.8
        self.assertEqual(self.sink.apply([review])["changes"], 0)
        self.assertEqual(self.sink.db.execute("SELECT status, score FROM fleet_reviews").fetchall(), [("rejected", 0.7)])

    def test_bad_operations_are_rejected_with_their_index(self):
        for bad, message in ((fact(source_url=""), "source_url"), ({"kind": "nope", "row": {}}, "known kind"),
                             (vessel(colour="red"), "unknown column")):
            with self.assertRaises(SinkError) as caught:
                self.sink.apply([vessel(), bad])
            self.assertEqual(caught.exception.index, 1)
            self.assertIn(message, str(caught.exception))
        self.assertEqual(self.sink.db.execute("SELECT count(*) FROM fleet_vessels").fetchone(), (0,))


class _Worker(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.calls.append((self.path, self.headers["Authorization"], body))
        status, reply = self.server.replies.pop(0) if self.server.replies else (200, {"changes": len(body["operations"])})
        data = json.dumps(reply).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class WorkerSinkTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _Worker)
        self.server.calls, self.server.replies = [], []
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.slept = []
        self.sink = WorkerSink(f"http://127.0.0.1:{self.server.server_address[1]}", "CA", "run-1", "ingest",
                               token_source=lambda: "oidc-token", sleep=self.slept.append,
                               opener=build_opener(ProxyHandler({})).open)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_batches_of_500_with_the_job_envelope(self):
        ops = [vessel(f"v{i}") for i in range(MAX_OPS + 100)]
        self.assertEqual(self.sink.apply(ops), {"operations": 600, "changes": 600})
        self.assertEqual([len(c[2]["operations"]) for c in self.server.calls], [500, 100])
        path, auth, body = self.server.calls[0]
        self.assertEqual((path, auth), ("/api/fleet/jobs/registry", "Bearer oidc-token"))
        self.assertEqual(set(body), {"region", "run_id", "step", "operations"})
        self.assertEqual(body["operations"][0], ops[0])
        self.assertTrue(self.sink.audience.endswith("/api/fleet/jobs"))

    def test_retries_transient_status_then_reports_op_index(self):
        self.server.replies = [(503, {"error": "busy"})]
        self.assertEqual(self.sink.apply([vessel()])["changes"], 1)
        self.assertEqual(self.slept, [2.0])
        self.server.calls.clear()
        self.server.replies = [(200, {"changes": 0}), (400, {"error": "fact needs provenance", "index": 3})]
        with self.assertRaises(SinkError) as caught:
            self.sink.apply([vessel(f"v{i}") for i in range(MAX_OPS + 10)])
        self.assertEqual(caught.exception.index, MAX_OPS + 3)

    def test_https_required_outside_loopback(self):
        with self.assertRaises(SinkRefused):
            WorkerSink("http://skippercast.com", "CA", "run-1", "ingest", token_source=lambda: "t")


class RegistryAndCliTests(unittest.TestCase):
    def test_config_uses_the_adapter_registry(self):
        self.assertIs(config.ADAPTERS, ADAPTERS)
        self.assertEqual(ADAPTERS, frozenset(REGISTRY))

    def test_dry_run_region_refuses_worker_sink(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Run("XX", var=Path(tmp))
            region = SimpleNamespace(id="XX", status="dry-run")
            with self.assertRaises(SinkRefused):
                open_sink("worker", region, run, "ingest", base="https://skippercast.com")
            open_sink("staging", region, run, "ingest").close()

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
