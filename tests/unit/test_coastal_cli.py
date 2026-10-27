"""Offline inspection must preserve held attempts and never launch a worker."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from skippercast.coastal import cli
from skippercast.coastal.coordinator.store import Store
from skippercast.coastal.coordinator.segments import segment
from skippercast.coastal.coordinator.stages import digest


class CoastalInspectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()

    def invoke(self, *arguments):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(["--root", str(self.root), *arguments])
        return code, output.getvalue(), error.getvalue()

    def test_uninitialized_status_does_not_create_a_queue(self):
        with patch.object(Store, "__init__", side_effect=AssertionError("must not initialize Store")):
            code, output, error = self.invoke("status")
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(json.loads(output)["state"], "uninitialized")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_status_matches_store_and_preserves_held_attempts_and_charges(self):
        database = self.root / "queue.sqlite"
        store = Store(database, root=self.root, clock=lambda: 100.)
        try:
            record = segment(0, 0, region="synthetic-inspection-only")
            store.add_segment(record)
            job = store.enqueue(record["segment_id"], "discover", code_sha="a" * 64,
                                deps_sha="b" * 64, max_attempts=2)
            store.db.execute("UPDATE jobs SET state='held',attempts=2,holds_json=? WHERE job_id=?",
                             (json.dumps(["synthetic_exhausted_hold"]), job))
            store.charge(job, {"wall_s": 17, "bytes": 123, "requests": 2})
            store.event(job, "tick", {"synthetic": True})
            expected = store.status()
        finally:
            store.close()
        original = database.read_bytes()
        with patch.object(Store, "__init__", side_effect=AssertionError("must not initialize Store")):
            code, output, error = self.invoke("--db", "queue.sqlite", "status")
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertEqual(result, expected)
        self.assertEqual((result["jobs"][0]["state"], result["jobs"][0]["attempts"]), ("held", 2))
        self.assertEqual(result["charges"][0]["bytes"], 123)
        self.assertEqual(database.read_bytes(), original)

    def test_status_refuses_traversal_and_absolute_database_paths(self):
        for database in ("../outside.sqlite", str(self.root / "absolute.sqlite")):
            with self.subTest(database=database):
                code, output, error = self.invoke("--db", database, "status")
                self.assertEqual((code, output), (2, ""))
                self.assertEqual(json.loads(error)["error"], "ValueError")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_status_refuses_database_and_parent_symlinks(self):
        target = self.root / "target"
        target.mkdir()
        (self.root / "alias").symlink_to(target, target_is_directory=True)
        (self.root / "queue.sqlite").symlink_to(target / "absent.sqlite")
        for database in ("alias/queue.sqlite", "queue.sqlite"):
            with self.subTest(database=database):
                code, output, error = self.invoke("--db", database, "status")
                self.assertEqual((code, output), (2, ""))
                self.assertIn("symlink", json.loads(error)["detail"])
        self.assertEqual(list(target.iterdir()), [])

    def test_declared_root_alias_is_accepted_without_accepting_child_symlinks(self):
        alias = self.root / "root-alias"
        alias.symlink_to(self.root, target_is_directory=True)
        output = io.StringIO()
        with redirect_stdout(output):
            code = cli.main(["--root", str(alias), "status"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["state"], "uninitialized")
        self.assertFalse((self.root / "var").exists())

    def test_corrupt_or_incompatible_database_returns_error_without_replacing_bytes(self):
        database = self.root / "bad.sqlite"
        database.write_bytes(b"synthetic corrupt database")
        original = database.read_bytes()
        code, output, error = self.invoke("--db", "bad.sqlite", "status")
        self.assertEqual((code, output), (2, ""))
        self.assertIn("error", json.loads(error))
        self.assertEqual(database.read_bytes(), original)

    def test_missing_root_is_an_error_without_creation(self):
        output, error = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = cli.main(["--root", str(self.root / "missing"), "status"])
        self.assertEqual(code, 2)
        self.assertEqual(output.getvalue(), "")
        self.assertFalse((self.root / "missing").exists())

    def test_dispatch_and_recovery_commands_are_not_exposed(self):
        for command in ("enqueue", "run", "recover"):
            with self.subTest(command=command), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as result:
                    cli.main(["--root", str(self.root), command])
                self.assertEqual(result.exception.code, 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_identity_binds_imported_module_and_packaged_schema_bytes(self):
        code, output, error = self.invoke("identity")
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertEqual(result["imported_module_sha256"], hashlib.sha256(Path(cli.__file__).read_bytes()).hexdigest())
        resources = {row["name"]: row for row in result["schema_resources"]}
        self.assertIn("coastal-terrain-only-input-v1.schema.json", resources)
        for identity in resources.values():
            self.assertEqual(len(identity["sha256"]), 64)
            self.assertGreater(identity["bytes"], 0)
        self.assertIn("unverified", result["acceptance"])
        self.assertEqual(list(self.root.iterdir()), [])

    def test_absent_distribution_is_unknown_not_an_installed_pass(self):
        with patch.object(cli.importlib.metadata, "distribution",
                          side_effect=importlib.metadata.PackageNotFoundError("skippercast")):
            code, output, error = self.invoke("identity")
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertEqual(result["distribution"], {"metadata_found": False, "version": None})
        self.assertIn("installed equivalence", result["acceptance"])
        self.assertIn("unverified", result["acceptance"])

    def test_dependency_identity_is_recomputable_from_reported_versions(self):
        code, output, error = self.invoke("identity")
        self.assertEqual((code, error), (0, ""))
        result = json.loads(output)
        self.assertEqual(result["dependency_versions_sha256"],
                         digest({"libs": result["dependency_versions"]}))

    def test_module_entrypoint_from_an_artifact_directory(self):
        result = subprocess.run([sys.executable, "-m", "skippercast.coastal.cli",
                                 "--root", str(self.root), "status"],
                                cwd=self.root, env=dict(os.environ), capture_output=True,
                                text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["state"], "uninitialized")
        self.assertEqual(list(self.root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
