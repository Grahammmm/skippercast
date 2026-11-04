"""``confirm``: the private operator-confirmed charter identity ledger.

Everything is synthetic: a temporary ``SKIPPERCAST_FLEET_VAR``, a staging registry built from the committed migrations
with invented vessels, and a fake Worker transport. No network, no real name, contact or URL; nothing here confirms a real
identity.
"""
from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import date
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

from skippercast.fleet import cli, confirm
from skippercast.fleet.sinks import SqliteSink

TODAY = date(2026, 11, 4)
VESSELS = {n: f"{n:032x}" for n in range(1, 9)}
MMSI = {n: f"99900000{n}" for n in range(1, 9)}
NAMES = {n: f"Test Boat {chr(64 + n)}" for n in range(1, 9)}
EVIDENCE = "EVIDENCE-MARKER-123"
METHODS = confirm.METHODS


def tree(root: Path) -> dict:
    """Every path under ``root`` with its type, mode and bytes (a symlink by target)."""
    out = {}
    for path in sorted(root.rglob("*")):
        info = path.lstat()
        body = os.readlink(path) if stat.S_ISLNK(info.st_mode) else path.read_bytes() if path.is_file() else None
        out[str(path.relative_to(root))] = (stat.S_IMODE(info.st_mode), body)
    return out


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    """A Worker transport that records every request and answers the snapshot from ``vessels``."""
    base, user_agent = "https://worker.invalid", "test"

    def __init__(self, vessels, fail=False):
        self.vessels, self.fail, self.requests = vessels, fail, []

    def token(self):
        return "tok"

    def close(self):
        pass

    def opener(self, request, timeout):
        self.requests.append((request.get_method(), request.full_url))
        if self.fail:
            raise OSError("https://secret.example/private-path failed")
        return Response({"operators": [], "reviews": [], "advisor_slugs": [], "next": None, "vessels": self.vessels})


class ConfirmBase(unittest.TestCase):
    template = None

    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.TemporaryDirectory()
        cls.template = Path(cls.tmpdir.name) / "template.sqlite"
        sink = SqliteSink(cls.template, "CA", "template-run")
        for n in VESSELS:
            sink.db.execute(
                "INSERT INTO fleet_vessels (id, region, slug, name, name_norm, mmsi, status, first_seen_at, last_seen_at,"
                " created_at, updated_at) VALUES (?, 'CA', ?, ?, ?, ?, 'active', 't', 't', 't', 't')",
                (VESSELS[n], f"boat-{n}", NAMES[n], NAMES[n].upper(), None if n == 8 else MMSI[n]))
        sink.close()

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir.cleanup()

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.var = Path(tmp.name)
        (self.var / "staging").mkdir()
        self.db = self.var / "staging" / "CA.sqlite"
        shutil.copy(self.template, self.db)
        env = mock.patch.dict(os.environ, {"SKIPPERCAST_FLEET_VAR": str(self.var)})
        env.start()
        self.addCleanup(env.stop)
        today = mock.patch.object(confirm, "today", lambda: TODAY)
        today.start()
        self.addCleanup(today.stop)
        # any network use fails the test: the Worker transport is always a FakeWorker
        deny = mock.patch("urllib.request.urlopen", side_effect=AssertionError("network"))
        deny.start()
        self.addCleanup(deny.stop)

    # -- helpers
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = cli.main(list(argv))
            except SystemExit as exit:
                code = exit.code
        return code, out.getvalue(), err.getvalue()

    def add(self, n=1, *, mmsi=None, method=METHODS[0], on="2026-11-01", ref=EVIDENCE, sink="staging", vessel=None):
        return self.run_cli("confirm", "add", "--region", "CA", "--sink", sink, "--vessel-id", vessel or VESSELS[n],
                            "--mmsi", mmsi or MMSI[n], "--method", method, "--confirmed-on", on, "--evidence-ref", ref)

    def withdraw(self, n=1, *, on="2026-11-03", mmsi=None, sink="staging"):
        return self.run_cli("confirm", "withdraw", "--region", "CA", "--sink", sink, "--vessel-id", VESSELS[n],
                            "--mmsi", mmsi or MMSI[n], "--withdrawn-on", on)

    def listing(self, sink="staging"):
        code, out, err = self.run_cli("confirm", "list", "--region", "CA", "--sink", sink)
        self.assertEqual((code, err), (0, ""), err)
        return json.loads(out)["confirmations"]

    def ledger(self, sink="staging") -> Path:
        return self.var / "CA" / "confirmations" / f"{sink}.json"

    def set_registry_mmsi(self, n, mmsi):
        db = sqlite3.connect(self.db)
        db.execute("UPDATE fleet_vessels SET mmsi=? WHERE id=?", (mmsi, VESSELS[n]))
        db.commit()
        db.close()

    def assert_refused(self, result, *secrets):
        code, out, err = result
        self.assertEqual((code, out), (1, ""), err)
        self.assertEqual(len(err.splitlines()), 1, err)
        for secret in (EVIDENCE, *NAMES.values(), *secrets):
            self.assertNotIn(secret, err)


class AddTests(ConfirmBase):
    def test_confirm_add_registry_match_only(self):
        for n, method in zip((1, 2, 3), METHODS):
            with self.subTest(method=method):
                self.assertEqual(self.add(n, method=method), (0, '{"action": "add", "affected": 1}\n', ""))
        self.assertEqual([(r["vessel_id"], r["method"], r["state"]) for r in self.listing()],
                         [(VESSELS[n], m, "active") for n, m in zip((1, 2, 3), METHODS)])
        before = self.ledger().read_bytes()
        self.assertEqual(self.add(1)[1], '{"action": "add", "affected": 0}\n', "an identical add changes nothing")
        self.assertEqual(self.ledger().read_bytes(), before)

    def test_add_refusals_change_nothing_and_echo_nothing(self):
        cases = {
            "unknown vessel": dict(vessel="f" * 32),
            "foreign vessel id": dict(vessel="zz-foreign-vessel-marker"),
            "another vessel's MMSI": dict(n=1, mmsi=MMSI[2]),
            "an MMSI the registry does not hold": dict(n=1, mmsi="999111222"),
            "a vessel with no registry MMSI": dict(n=8, mmsi="999000008"),
            "an inferred method": dict(method="name-similarity"),
            "an AIS type is not a method": dict(method="ais-type"),
            "a malformed MMSI": dict(mmsi="99900000x"),
            "a short MMSI": dict(mmsi="12345678"),
            "a malformed date": dict(on="2026-13-40"),
            "a compact date": dict(on="20261101"),
            "a date with a time": dict(on="2026-11-01T00:00:00"),
            "a future date": dict(on="2026-11-05"),
            "a url as the reference": dict(ref="https://example.com/x"),
            "a contact as the reference": dict(ref="someone@example.com"),
            "a path as the reference": dict(ref="/var/private/file"),
            "an empty-looking reference": dict(ref="a b"),
            "an over-long reference": dict(ref="a" * 129),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                before = tree(self.var)
                secrets = [v for v in kwargs.values() if isinstance(v, str)]
                self.assert_refused(self.add(**kwargs), *secrets)
                self.assertEqual(tree(self.var), before, "a refusal creates and changes nothing")

    def test_a_different_add_for_a_standing_confirmation_refuses(self):
        self.assertEqual(self.add(1)[0], 0)
        before = self.ledger().read_bytes()
        for label, kwargs in (("method", dict(method=METHODS[1])), ("date", dict(on="2026-11-02")),
                              ("reference", dict(ref="OTHER-REF"))):
            with self.subTest(label):
                self.assert_refused(self.add(1, **kwargs), "OTHER-REF")
                self.assertEqual(self.ledger().read_bytes(), before)


class WithdrawTests(ConfirmBase):
    def test_confirm_withdraw_reconfirm_and_stale(self):
        self.add(1)
        self.assertEqual(self.withdraw(1), (0, '{"action": "withdraw", "affected": 1}\n', ""))
        self.assertEqual([(r["state"], r["withdrawn_on"]) for r in self.listing()], [("withdrawn", "2026-11-03")])
        withdrawn = self.ledger().read_bytes()
        self.assertEqual(self.withdraw(1)[1], '{"action": "withdraw", "affected": 0}\n', "a repeat is a no-op")
        self.assertEqual(self.ledger().read_bytes(), withdrawn)
        for label, result in (("another date", self.withdraw(1, on="2026-11-04")),
                              ("unknown pair", self.withdraw(2)),
                              ("not the registry's MMSI", self.withdraw(1, mmsi=MMSI[2])),
                              ("a malformed date", self.withdraw(1, on="2026-02-30")),
                              ("a future date", self.withdraw(1, on="2026-11-05"))):
            with self.subTest(label):
                self.assert_refused(result)
        self.assertEqual(self.ledger().read_bytes(), withdrawn)

        for label, on in (("the same day as the first confirmation", "2026-11-01"),
                          ("before the withdrawal", "2026-11-02")):
            with self.subTest(label):
                self.assert_refused(self.add(1, on=on, method=METHODS[1]))
                self.assertEqual(self.ledger().read_bytes(), withdrawn)
        self.assertEqual(self.add(1, on="2026-11-03", method=METHODS[1], ref="NEW-REF")[0], 0)
        self.assertEqual([(r["method"], r["confirmed_on"], r["withdrawn_on"], r["state"]) for r in self.listing()],
                         [(METHODS[1], "2026-11-03", None, "active")])

    def test_withdraw_before_the_confirmation_and_the_conflicting_active_edit_refuse(self):
        self.add(1, on="2026-11-02")
        before = self.ledger().read_bytes()
        self.assert_refused(self.withdraw(1, on="2026-11-01"))
        self.assert_refused(self.add(1, on="2026-11-02", method=METHODS[2]))
        self.assertEqual(self.ledger().read_bytes(), before)

    def test_a_reassigned_mmsi_is_stale_and_neither_counts_nor_moves(self):
        self.add(1)
        self.set_registry_mmsi(1, "999777888")
        self.assertEqual([r["state"] for r in self.listing()], ["stale"])
        before = self.ledger().read_bytes()
        self.assert_refused(self.withdraw(1), "999777888")
        self.assert_refused(self.add(1, method=METHODS[1], on="2026-11-02"))
        self.assertEqual(self.ledger().read_bytes(), before, "the old evidence stays with the old pair")
        # the new pair needs its own confirmation; the stale one stays stale
        self.assertEqual(self.add(1, mmsi="999777888", method=METHODS[2], ref="NEW-REF")[0], 0)
        self.assertEqual([(r["mmsi"], r["state"]) for r in self.listing()], [(MMSI[1], "stale"), ("999777888", "active")])
        held = confirm.held_mmsi(confirm.read_registry("CA", "staging"))
        self.assertEqual(held[VESSELS[1]], "999777888")
        # the count itself (one confirmation per vessel, current MMSI only) is in test_fleet_coverage_status
        self.assertEqual(len(confirm.active_pairs(confirm.load_confirmations("CA", "staging"))), 2, "both rows are un-withdrawn")

    def test_withdraw_of_a_vessel_the_registry_dropped_refuses(self):
        self.add(1)
        db = sqlite3.connect(self.db)
        db.execute("UPDATE fleet_vessels SET mmsi=NULL WHERE id=?", (VESSELS[1],))
        db.commit()
        db.close()
        self.assert_refused(self.withdraw(1))
        self.assertEqual([r["state"] for r in self.listing()], ["stale"])


class PrivateIoTests(ConfirmBase):
    def test_confirm_private_io(self):
        empty = tree(self.var)
        self.assertEqual(self.listing(), [])
        self.assertEqual(tree(self.var), empty, "listing an absent ledger creates nothing")
        self.assertEqual(self.add(1)[0], 0)
        self.assertEqual(stat.S_IMODE(self.ledger().stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.ledger().parent.stat().st_mode), 0o700)
        self.assertEqual(sorted(p.name for p in self.ledger().parent.iterdir()), ["staging.json", "staging.lock"])
        text = self.ledger().read_text()
        self.assertEqual(json.loads(text)["version"], 1)
        self.assertEqual(sorted(json.loads(text)["entries"][0]),
                         ["confirmed_on", "evidence_ref", "method", "mmsi", "vessel_id", "withdrawn_on"])
        for name in NAMES.values():
            self.assertNotIn(name, text, "registry names never enter the ledger")
        # nothing it prints holds the evidence reference, a name or a path
        outputs = "".join("".join(self.run_cli(*a)[1:]) for a in (
            ("confirm", "list", "--region", "CA"), ("confirm", "withdraw", "--region", "CA", "--vessel-id", VESSELS[1],
                                                     "--mmsi", MMSI[1], "--withdrawn-on", "2026-11-03")))
        outputs += "".join(self.add(2)[1:]) + "".join(self.add(2, vessel="f" * 32)[1:])
        for forbidden in (EVIDENCE, str(self.var), *NAMES.values()):
            self.assertNotIn(forbidden, outputs)
        self.assertNotIn("evidence_ref", outputs)

    def test_concurrent_local_writers_do_not_lose_updates(self):
        held = lambda: {VESSELS[n]: MMSI[n] for n in VESSELS}  # noqa: E731
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda n: confirm.add("CA", "staging", VESSELS[n], MMSI[n], METHODS[0], "2026-11-01",
                                                          f"ref-{n}", held, var=self.var, now=TODAY), VESSELS))
        self.assertEqual(results, [1] * len(VESSELS))
        self.assertEqual(sorted(e["vessel_id"] for e in confirm.load_confirmations("CA", "staging", self.var)),
                         sorted(VESSELS.values()))

    def test_a_failed_replace_leaves_the_ledger_and_no_temporary_file(self):
        self.assertEqual(self.add(1)[0], 0)
        before = tree(self.var)
        with mock.patch.object(confirm.os, "replace", side_effect=OSError("disk full /private/place")):
            code, out, err = self.add(2)
        self.assertEqual((code, out), (1, ""))
        self.assertEqual(err, "confirm add: the confirmation ledger could not be written\n")
        self.assertEqual(tree(self.var), before, "no temporary file stays and the ledger is unchanged")
        # a first write that fails creates a directory but no ledger and no temporary file
        shutil.rmtree(self.var / "CA")
        with mock.patch.object(confirm.os, "replace", side_effect=OSError("disk full")):
            self.assertEqual(self.add(1)[0], 1)
        self.assertEqual(sorted(p.name for p in (self.var / "CA" / "confirmations").iterdir()), ["staging.lock"])

    def test_a_corrupt_ledger_is_refused_by_every_command_and_never_read_as_zero(self):
        row = {"vessel_id": VESSELS[1], "mmsi": MMSI[1], "method": METHODS[0], "confirmed_on": "2026-11-01",
               "evidence_ref": "r1", "withdrawn_on": None}
        corrupt = {
            "not json": "{", "empty": "", "a list": "[]", "wrong version": json.dumps({"version": 2, "entries": []}),
            "boolean version": json.dumps({"version": True, "entries": []}),
            "extra top-level key": json.dumps({"version": 1, "entries": [], "note": "x"}),
            "entries not a list": json.dumps({"version": 1, "entries": {}}),
            "a row that is not an object": json.dumps({"version": 1, "entries": ["x"]}),
            "an extra field": json.dumps({"version": 1, "entries": [{**row, "name": "Test Boat A"}]}),
            "a missing field": json.dumps({"version": 1, "entries": [{k: v for k, v in row.items() if k != "method"}]}),
            "a duplicate pair": json.dumps({"version": 1, "entries": [row, {**row, "method": METHODS[1]}]}),
            "an unknown method": json.dumps({"version": 1, "entries": [{**row, "method": "ais-type"}]}),
            "an invalid date": json.dumps({"version": 1, "entries": [{**row, "confirmed_on": "2026-02-30"}]}),
            "a withdrawal before the confirmation": json.dumps({"version": 1, "entries": [{**row, "withdrawn_on": "2026-10-31"}]}),
            "a url reference": json.dumps({"version": 1, "entries": [{**row, "evidence_ref": "https://example.com"}]}),
            "a numeric MMSI": json.dumps({"version": 1, "entries": [{**row, "mmsi": 999000001}]}),
            "invalid UTF-8": None,
        }
        self.ledger().parent.mkdir(parents=True)
        for label, text in corrupt.items():
            with self.subTest(label):
                if text is None:
                    self.ledger().write_bytes(b"\xff\xfe{")
                else:
                    self.ledger().write_text(text)
                before = tree(self.var)
                for result in (self.add(2), self.withdraw(1), self.run_cli("confirm", "list", "--region", "CA")):
                    self.assertEqual(result[:2], (1, ""))
                    self.assertEqual(result[2].splitlines()[0].split(": ", 1)[1], confirm.LEDGER_BAD)
                self.assertEqual(tree(self.var), before)
                with self.assertRaises(confirm.ConfirmError):
                    confirm.load_confirmations("CA", "staging", self.var)

    def test_symlinked_ledger_paths_are_refused(self):
        outside = self.var / "outside"
        outside.mkdir()
        target = outside / "other.json"
        target.write_text(json.dumps({"version": 1, "entries": []}))
        self.ledger().parent.mkdir(parents=True)
        self.ledger().symlink_to(target)
        for result in (self.add(1), self.withdraw(1), self.run_cli("confirm", "list", "--region", "CA")):
            self.assertEqual(result[:2], (1, ""))
        self.assertEqual(json.loads(target.read_text()), {"version": 1, "entries": []})
        self.ledger().unlink()
        shutil.rmtree(self.ledger().parent)
        self.ledger().parent.symlink_to(outside)
        self.assertEqual(self.add(1)[:2], (1, ""))
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["other.json"], "nothing was written through the link")

    def test_the_ledger_is_per_region_and_sink(self):
        self.add(1)
        self.assertTrue(self.ledger("staging").exists())
        self.assertFalse(self.ledger("worker").exists())
        self.assertEqual(confirm.load_confirmations("CA", "worker", self.var), [])
        self.assertEqual(confirm.load_confirmations("WA", "staging", self.var), [])
        for region, sink in (("../CA", "staging"), ("ca", "staging"), ("CA", "prod"), ("CAL", "staging"), ("", "staging")):
            with self.subTest(region=region, sink=sink), self.assertRaises(confirm.ConfirmError):
                confirm.load_confirmations(region, sink, self.var)


class CliTests(ConfirmBase):
    def test_confirm_cli_dispatch_and_flags(self):
        code, out, err = self.run_cli("confirm", "--help")
        self.assertEqual(code, 0)
        for word in ("add", "withdraw", "list"):
            self.assertIn(word, out)
        self.assertIn("confirm", self.run_cli("--help")[1])
        before = tree(self.var)
        marker = "zzmarker"
        bad = {
            "no action": ("confirm",),
            "unknown action": ("confirm", "remove", "--region", "CA"),
            "unknown flag": ("confirm", "list", "--region", "CA", f"--{marker}", "1"),
            "abbreviated flag": ("confirm", "list", "--reg", "CA"),
            "add with a withdrawal date": ("confirm", "add", "--region", "CA", "--vessel-id", VESSELS[1], "--mmsi", MMSI[1],
                                           "--method", METHODS[0], "--confirmed-on", "2026-11-01", "--evidence-ref", "r",
                                           "--withdrawn-on", "2026-11-03"),
            "withdraw with a method": ("confirm", "withdraw", "--region", "CA", "--vessel-id", VESSELS[1], "--mmsi", MMSI[1],
                                       "--withdrawn-on", "2026-11-03", "--method", METHODS[0]),
            "list with a vessel": ("confirm", "list", "--region", "CA", "--vessel-id", VESSELS[1]),
            "add without evidence": ("confirm", "add", "--region", "CA", "--vessel-id", VESSELS[1], "--mmsi", MMSI[1],
                                     "--method", METHODS[0], "--confirmed-on", "2026-11-01"),
            "withdraw without a date": ("confirm", "withdraw", "--region", "CA", "--vessel-id", VESSELS[1], "--mmsi", MMSI[1]),
            "no region": ("confirm", "list"),
            "a flag without its value": ("confirm", "list", "--region"),
        }
        with mock.patch.object(confirm, "read_registry", side_effect=AssertionError("a store was opened")), \
                mock.patch.object(confirm.sqlite3, "connect", side_effect=AssertionError("a store was opened")):
            for label, argv in bad.items():
                with self.subTest(label):
                    code, out, err = self.run_cli(*argv)
                    self.assertEqual((code, out), (2, ""))
                    self.assertIn("confirm: invalid or missing arguments", err)
                    for echoed in (marker, "remove", EVIDENCE):
                        self.assertNotIn(echoed, err)
            for sink in ("bogus-sink", "WORKER"):
                with self.subTest(sink=sink):
                    code, out, err = self.run_cli("confirm", "list", "--region", "CA", "--sink", sink)
                    self.assertEqual((code, out, err), (1, "", "confirm list: invalid region or sink\n"))
            self.assertEqual(self.run_cli("confirm", "list", "--region", "ca")[:2], (1, ""))
        self.assertEqual(tree(self.var), before)

    def test_list_is_deterministic_and_carries_only_opaque_fields(self):
        for n in (3, 1, 2):
            self.add(n, method=METHODS[n - 1], ref=f"{EVIDENCE}-{n}")
        self.withdraw(2)
        first = self.run_cli("confirm", "list", "--region", "CA")
        self.assertEqual(first, self.run_cli("confirm", "list", "--region", "CA"))
        rows = json.loads(first[1])["confirmations"]
        self.assertEqual([r["vessel_id"] for r in rows], [VESSELS[1], VESSELS[2], VESSELS[3]])
        self.assertEqual([r["state"] for r in rows], ["active", "withdrawn", "active"])
        for row in rows:
            self.assertEqual(sorted(row), ["confirmed_on", "method", "mmsi", "state", "vessel_id", "withdrawn_on"])
        self.assertNotIn(EVIDENCE, first[1] + first[2])

    def test_staging_registry_is_read_only_and_never_created(self):
        self.add(1)
        self.withdraw(1)
        self.add(2)
        digest_before = digest(self.db)
        for result in (self.add(3), self.withdraw(2), self.add(1, mmsi=MMSI[2]), self.run_cli("confirm", "list", "--region", "CA")):
            self.assertIn(result[0], (0, 1))
        self.assertEqual(digest(self.db), digest_before, "the staging registry is byte-identical")
        self.assertEqual(sorted(p.name for p in (self.var / "staging").iterdir()), ["CA.sqlite"])
        # no staging registry at all: refused, and none is created
        self.db.unlink()
        before = tree(self.var)
        self.assert_refused(self.add(4))
        self.assertEqual(self.run_cli("confirm", "list", "--region", "CA")[:2], (1, ""))
        self.assertEqual(tree(self.var), before)
        self.assertFalse(self.db.exists())

    def test_worker_registry_is_read_through_the_snapshot_only(self):
        worker = FakeWorker([{"id": VESSELS[1], "mmsi": MMSI[1]}, {"id": VESSELS[2], "mmsi": None}])
        with mock.patch.object(confirm, "WorkerSink", lambda *a, **k: worker), \
                mock.patch.object(confirm, "worker_base", lambda: "https://worker.invalid"):
            self.assertEqual(self.add(1, sink="worker")[0], 0)
            self.assert_refused(self.add(2, mmsi=MMSI[2], sink="worker"))
            self.assert_refused(self.add(3, sink="worker"))
            self.assertEqual(self.withdraw(1, sink="worker")[0], 0)
            self.assertEqual([r["state"] for r in self.listing("worker")], ["withdrawn"])
        self.assertTrue(worker.requests)
        self.assertEqual({method for method, _ in worker.requests}, {"GET"}, "no registry operation is ever sent")
        self.assertTrue(all("/api/fleet/jobs/snapshot?" in url and "/registry" not in url for _, url in worker.requests))
        self.assertTrue(self.ledger("worker").exists())
        self.assertFalse(self.ledger("staging").exists(), "a worker confirmation never lands in the staging ledger")
        self.assertEqual(self.listing("staging"), [])

    def test_a_failing_worker_read_is_refused_without_its_cause(self):
        worker = FakeWorker([], fail=True)
        before = tree(self.var)
        with mock.patch.object(confirm, "WorkerSink", lambda *a, **k: worker), \
                mock.patch.object(confirm, "worker_base", lambda: "https://worker.invalid"):
            code, out, err = self.add(1, sink="worker")
        self.assertEqual((code, out, err), (1, "", "confirm add: the registry could not be read\n"))
        self.assertEqual(tree(self.var), before)


if __name__ == "__main__":
    unittest.main()
