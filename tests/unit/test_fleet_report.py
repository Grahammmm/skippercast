"""The fleet report (``python -m skippercast.fleet report``, design sections 13, 18, 19; CF-61).

Every boat here is synthetic: invented ids, MMSIs 999xxxxxx, fictional 555-01XX
phones and example.com/.org addresses, which the report must count but never print.
The expected numbers are worked out by hand in the comments.
"""
from contextlib import redirect_stdout
from datetime import datetime, timezone
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import tempfile
import unittest
from unittest import mock

from skippercast.fleet import cli, report
from skippercast.fleet.ais.process import State
from skippercast.fleet.config import load_region
from skippercast.fleet.sinks import SqliteSink
from tests._support import ROOT

_spec = importlib.util.spec_from_file_location("check_repository", ROOT / "scripts/check_repository.py")
check_repository = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_repository)

HOUR, DAY = report.HOUR, report.DAY


def ms(text: str) -> int:
    return round(datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp() * 1000)


NOW = ms("2026-10-05T12:30:00")        # current hour 12:00 is excluded; 30-day "seen" cut 2026-09-05T12:30:00.000Z
PHONE_1 = "+1" + "805" + "55501" + "23"   # fictional 555-01XX series
PHONE_2 = "+1" + "805" + "55501" + "42"


def vessel(n, port, cls, completeness, status="active", **cols):
    return {"id": f"{n:032x}", "slug": f"test-boat-{n}", "name": f"Test Boat {n}", "status": status, "port_id": port,
            "vessel_class": cls, "completeness": completeness, **cols}


VESSELS = [
    # identity 4/4, registry 2/5, specs 2/6, contact 3/5
    vessel(1, "morro-bay", "six-pack", 0.5, waters=["ocean"], landing_id="test-landing", mmsi="999000001",
           call_sign="WDX0001", year_built=1990, passengers_max=6, website="https://boat-one.example.com/",
           phone_business=PHONE_1, email_business="captain@boat-one.example.com"),
    # identity 2/4 (no waters, no landing), registry 0/5, specs 0/6, contact 2/5
    vessel(2, "morro-bay", "six-pack", 0.25, waters=[], booking_url="https://book.example.com/boat-two",
           phone_business=PHONE_2),
    # identity 3/4, registry 2/5, specs 3/6 (bunks 0 is a value), contact 0/5
    vessel(3, "morro-bay", "inspected-party", 0.75, waters=["bay"], mmsi="999000003", uscg_doc="1000003",
           passengers_max=40, length_ft=65.0, bunks=0),
    # identity 1/4, registry 1/5, specs 0/6, contact 1/5
    vessel(4, "port-san-luis", None, 0.0, state_reg="CF 0004 XY", email_business="office@boat-four.example.org"),
    # not active: never counted
    vessel(5, "morro-bay", "six-pack", 1.0, status="excluded", mmsi="999000005", website="https://five.example.com/"),
]
WATCH = [
    {"vessel_id": f"{1:032x}", "mmsi": "999000001", "status": "watched", "last_seen_at": "2026-10-01T00:00:00.000Z"},
    {"vessel_id": f"{3:032x}", "mmsi": "999000003", "status": "watched", "last_seen_at": "2026-09-01T00:00:00.000Z"},
    {"vessel_id": f"{2:032x}", "mmsi": "999000002", "status": "candidate", "last_seen_at": "2026-10-04T00:00:00.000Z"},
    {"vessel_id": f"{5:032x}", "mmsi": "999000005", "status": "watched", "last_seen_at": "2026-10-04T00:00:00.000Z"},
]


def hours() -> dict[int, int]:
    """Up all of 2026-09-10, and from 2026-09-20 to now except 09-27 05:00 (a zero row) and 10-02 10:00 (missing)."""
    out = {ms("2026-09-01T00:00:00"): 50}                            # before the 30-day window
    out.update({ms("2026-09-10T00:00:00") + i * HOUR: 100 for i in range(24)})
    t = ms("2026-09-20T00:00:00")
    while t <= ms("2026-10-05T12:00:00"):                          # the current hour too, which is not counted
        out[t] = 100
        t += HOUR
    out[ms("2026-09-27T05:00:00")] = 0
    del out[ms("2026-10-02T10:00:00")]
    return out


RUNS = [   # (run id, report status or None, failed step, Places searches + details)
    ("20261001T060000Z-aaaaaa", "ok", None, (12, 30)),
    ("20261003T060000Z-bbbbbb", "failed", "resolve", None),
    ("20261004T060000Z-cccccc", "partial", None, (2, 3)),
    ("20261005T060000Z-dddddd", None, None, None),                 # still running: no status in report.json
    ("20260801T060000Z-eeeeee", "failed", "ingest", (60, 40)),     # older than 30 days and another month
    ("20260920T060000Z-ffffff", "ok", None, (3, 4)),               # inside 30 days, September
]
VALIDATION = {"trips": {"scored": 31, "missing": 2, "ports": 3}, "fishing": {"precision": 0.842, "recall": 0.761},
              "target": {"trips": 30, "met": True}, "classifier_version": "cls-test", "computed_at": "2026-10-05T06:00:00.000Z"}


def run_rows():
    return [{"id": rid, "created_at": f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}T06:00:00Z", "status": status or "incomplete",
             "failed_steps": [failed] if failed else [], "places_calls": sum(places or ())}
            for rid, status, failed, places in RUNS]


EXPECTED_PORTS = [
    {"port_id": "morro-bay", "boats": 3, "mmsi": (2, 66.7), "seen": (1, 33.3), "mean": 50.0, "classes": [
        ("inspected-party", 1, (1, 100.0), (0, 0.0), 75.0), ("six-pack", 2, (1, 50.0), (1, 50.0), 37.5)]},
    {"port_id": "port-san-luis", "boats": 1, "mmsi": (0, 0.0), "seen": (0, 0.0), "mean": 0.0, "classes": [
        (None, 1, (0, 0.0), (0, 0.0), 0.0)]},
]
STATUS = ("- 2026-10-05: CA fleet report: 4 active boats (morro-bay 3 (inspected-party 1, six-pack 2); port-san-luis 1 "
          "(unclassified 1)); MMSI 50.0%, seen in 30 days 25.0%; AIS ingestion 2 consecutive full days (longest 7; "
          "uptime 7 d 99.4%, 30 d 54.7%); 31 labelled trips, fishing precision 0.842, recall 0.761; 3 open reviews.")
# The fleet privacy scan's patterns (scripts/check_repository.py) and any email address, URL or MMSI.
FORBIDDEN = {"phone": check_repository.E164_NANP, "handle": check_repository.MENTION,
             "phone digits": re.compile(r"805\D?555"), "email": re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"),
             "url": re.compile(r"https?:|www\.|\b[\w-]+\.(?:com|org|net)\b"), "mmsi": re.compile(r"\b999\d{6}\b"),
             "name": re.compile(r"Test Boat|test-boat|test-landing|WDX0001|1000003|CF 0004")}


class ReportNumbersTests(unittest.TestCase):
    def build(self, **extra):
        return report.build("CA", vessels=VESSELS, watch=WATCH, hours=hours(), runs=run_rows(),
                            validation_doc=VALIDATION, open_reviews=3, now_ms=NOW, **extra)

    def test_boats_by_port_and_class(self):
        r = self.build()
        t = r["totals"]
        self.assertEqual(t["boats"], 4)
        self.assertEqual(t["mmsi"], {"n": 2, "pct": 50.0})
        self.assertEqual(t["seen_30d"], {"n": 1, "pct": 25.0})     # only boat 1: boat 3 is stale, 2 a candidate
        self.assertEqual(t["completeness"]["mean_pct"], 37.5)      # (0.5 + 0.25 + 0.75 + 0) / 4
        # identity 10/16, registry 5/20, specs 5/24 = 20.83, contact 6/20
        self.assertEqual(t["completeness"]["groups"], {"identity": 62.5, "registry": 25.0, "specs": 20.8, "contact": 30.0})
        self.assertEqual(len(r["ports"]), len(EXPECTED_PORTS))
        for port, want in zip(r["ports"], EXPECTED_PORTS):
            self.assertEqual((port["port_id"], port["boats"]), (want["port_id"], want["boats"]))
            self.assertEqual((port["mmsi"]["n"], port["mmsi"]["pct"]), want["mmsi"])
            self.assertEqual((port["seen_30d"]["n"], port["seen_30d"]["pct"]), want["seen"])
            self.assertEqual(port["completeness"]["mean_pct"], want["mean"])
            got = [(c["vessel_class"], c["boats"], (c["mmsi"]["n"], c["mmsi"]["pct"]),
                    (c["seen_30d"]["n"], c["seen_30d"]["pct"]), c["completeness"]["mean_pct"]) for c in port["classes"]]
            self.assertEqual(got, want["classes"])

    def test_uptime_and_full_days(self):
        u = self.build()["uptime"]
        # 7 d: 2026-09-28 12:00 to 10-05 12:00, 168 hours, all up but 10-02 10:00
        self.assertEqual(u["d7"], {"pct": 99.4, "up_hours": 167, "hours": 168})
        # 30 d from 09-05 12:00: 24 (09-10) + 372 (09-20 00:00 to 10-05 11:00) - 2 = 394 of 720
        self.assertEqual(u["d30"], {"pct": 54.7, "up_hours": 394, "hours": 720})
        # complete days 09-06 .. 10-04 (29): 09-10; 09-20..26 (7); 09-28..10-01 (4); 10-03..04 (2)
        self.assertEqual(u["full_days"], {"longest": 7, "current": 2, "days": 29})
        self.assertEqual(u["hours_recorded"], 1 + 24 + 373 - 1)

    def test_validation_runs_reviews_and_cost(self):
        r = self.build(d1="48 MB stored, 1.2M rows read")
        self.assertEqual(r["validation"], {"trips_scored": 31, "precision": 0.842, "recall": 0.761, "target_met": True,
                                           "classifier_version": "cls-test", "computed_at": "2026-10-05T06:00:00.000Z"})
        runs = r["runs"]
        self.assertEqual((runs["runs"], runs["ok"], runs["partial"], runs["failed"], runs["incomplete"]), (5, 2, 1, 1, 1))
        self.assertEqual(runs["failed_steps"], [{"run_id": "20261003T060000Z-bbbbbb", "step": "resolve"}])
        self.assertEqual(r["open_reviews"], 3)
        self.assertEqual(r["cost"], {"month": "2026-10", "places_calls": 47, "d1": "48 MB stored, 1.2M rows read",
                                     "paid_items": "none", "estimate_usd": 0})   # 42 + 5 in October

    def test_status_line(self):
        self.assertEqual(report.status_line(self.build()), STATUS)
        empty = report.build("CA", vessels=[], watch=[], hours={}, runs=[], now_ms=NOW)
        self.assertEqual(report.status_line(empty), (
            "- 2026-10-05: CA fleet report: 0 active boats (none); MMSI —, seen in 30 days —; AIS ingestion 0 "
            "consecutive full days (longest 0; uptime 7 d 0.0%, 30 d 0.0%); no validation report; open reviews not counted."))
        self.assertIn("No validation report on this runner.", report.markdown(empty))

    def test_half_up_rounding_matches_the_admin_views(self):
        self.assertEqual(report.pct(1, 8), 12.5)
        self.assertEqual(report.pct(1, 1600), 0.1)     # 0.0625 -> 0.1, as JavaScript Math.round
        self.assertIsNone(report.pct(0, 0))


def seed(var: Path) -> None:
    """The same registry, counters, runs and validation report as a runner's FLEET_VAR."""
    (var / "staging").mkdir(parents=True)
    sink = SqliteSink(var / "staging" / "CA.sqlite", "CA", "20261005T000000Z-000000")
    stamp = "2026-09-01T00:00:00.000Z"
    for v in VESSELS:
        row = {**{k: x for k, x in v.items() if k != "waters"}, "region": "CA", "name_norm": v["name"].lower(),
               "first_seen_at": stamp, "last_seen_at": stamp, "created_at": stamp, "updated_at": stamp}
        if "waters" in v:
            row["waters_json"] = json.dumps(v["waters"])
        sink.db.execute(f"INSERT INTO fleet_vessels ({','.join(row)}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
    for w in WATCH:
        sink.db.execute("INSERT INTO fleet_ais_watch (region,mmsi,vessel_id,match_method,confidence,status,first_seen_at,"
                        "last_seen_at,updated_at) VALUES ('CA',?,?,'admin',1,?,?,?,?)",
                        (w["mmsi"], w["vessel_id"], w["status"], stamp, w["last_seen_at"], stamp))
    for n, status in enumerate(("open", "open", "open", "decided")):
        sink.db.execute("INSERT INTO fleet_reviews (id,region,kind,status,opened_at) VALUES (?,?,?,?,?)",
                        (f"{n:032x}", "CA", "mmsi", status, stamp))
    sink.close()
    state = State(var / "CA" / "ais" / "state.sqlite")
    for hour, messages in hours().items():
        state.set_hour(hour, {"messages": messages, "watched_messages": 0, "vessels": 1, "max_gap_s": 60})
    state.close()
    (var / "CA" / "ais" / "validation").mkdir()
    (var / "CA" / "ais" / "validation" / "report.json").write_text(json.dumps(VALIDATION))
    for rid, status, failed, places in RUNS:
        directory = var / "CA" / "runs" / rid
        directory.mkdir(parents=True)
        steps = {"discover": {"status": "done"}, **({failed: {"status": "failed", "error": "HTTPError: https://x.example.com/"}}
                                                    if failed else {}), **({} if status else {"resolve": {"status": "running"}})}
        created = f"{rid[:4]}-{rid[4:6]}-{rid[6:8]}T06:00:00Z"
        (directory / "state.json").write_text(json.dumps({"run_id": rid, "region": "CA", "created_at": created, "steps": steps}))
        (directory / "report.json").write_text(json.dumps({"run_id": rid, **({"status": status} if status else {})}))
        if places:
            (directory / "enrich-code.json").write_text(json.dumps({"bindings": {
                "google-places": {"status": "ok", "searches": places[0], "details": places[1]},
                "operator-site": {"searches": 900, "details": 900}}}))   # not a Places binding: not counted


class ReportCommandTests(unittest.TestCase):
    def run_report(self, *args):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": tmp}):
            var = Path(tmp)
            seed(var)
            out = io.StringIO()
            with redirect_stdout(out):
                code = cli.main(["report", "--region", "CA", *args])
            written = {p.suffix: p.read_text() for p in (var / "CA" / "reports").iterdir()}
            self.assertEqual(sorted(p.name for p in (var / "CA" / "reports").iterdir()), ["2026-10-05.json", "2026-10-05.md"])
        return code, out.getvalue(), written

    def setUp(self):
        patcher = mock.patch.object(report.time, "time", return_value=NOW / 1000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_seeded_runner_gives_the_hand_computed_report(self):
        code, printed, written = self.run_report("--d1", "48 MB stored, 1.2M rows read")
        self.assertEqual(code, 0)
        self.assertEqual(printed, written[".md"])
        result = json.loads(written[".json"])
        expected = report.build("CA", vessels=VESSELS, watch=WATCH, hours=hours(), runs=run_rows(), validation_doc=VALIDATION,
                                open_reviews=3, d1="48 MB stored, 1.2M rows read", now_ms=NOW)
        self.assertEqual(result, json.loads(json.dumps(expected)))
        self.assertEqual(result["totals"]["boats"], 4)
        self.assertEqual(result["open_reviews"], 3)
        self.assertEqual(result["cost"]["places_calls"], 47)
        self.assertIn("| morro-bay | six-pack | 2 | 1 (50.0%) | 1 (50.0%) | 37.5% |", printed)
        self.assertIn("| **All ports** | all | 4 | 2 (50.0%) | 1 (25.0%) | 37.5% |", printed)
        self.assertIn("fishing precision 0.842, recall 0.761; target met", printed)
        self.assertIn("- Failed: run `20261003T060000Z-bbbbbb` step `resolve`", printed)

    def test_status_line_option(self):
        code, printed, _ = self.run_report("--status-line", "--open-reviews", "5")
        self.assertEqual(code, 0)
        self.assertEqual(printed, STATUS.replace("3 open reviews", "5 open reviews") + "\n")

    def test_no_contact_data_in_the_output(self):
        _, printed, written = self.run_report()
        _, line, _ = self.run_report("--status-line")
        for name, text in {"markdown": written[".md"], "json": written[".json"], "status line": line}.items():
            for label, pattern in FORBIDDEN.items():
                with self.subTest(output=name, pattern=label):
                    self.assertIsNone(pattern.search(text))
        self.assertEqual(printed, written[".md"])

    def test_d1_takes_figures_only(self):
        for value in ("see https://dash.example.com/d1", "billing@example.com", "call " + PHONE_1):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                with redirect_stdout(io.StringIO()), mock.patch("sys.stderr", io.StringIO()):
                    report.main(["--region", "CA", "--d1", value])

    def test_missing_local_inputs_still_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            region = load_region("CA")
            inputs = report.collect(region, "staging", Path(tmp))
        self.assertEqual((inputs["vessels"], inputs["watch"], inputs["hours"], inputs["runs"]), ([], [], {}, []))
        self.assertIsNone(inputs["validation_doc"])
        self.assertEqual(inputs["open_reviews"], 0)


if __name__ == "__main__":
    unittest.main()
