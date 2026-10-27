"""The native worker the coordinator launches is shipped with the package.

coordinator/authenticated.py argv_for starts every acquire/qualify job as
``python -I src/skippercast/coastal/authenticated_v1/bootstrap.py --request ... --output ...``.
Attempt 2 of the 2026-10-19 four128 trial failed at A-acquire because that file
(and the worker and observer it loads) existed only in an uncommitted snapshot.
These tests pin the launch path to real, parseable package source.
"""
import ast
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from skippercast.coastal.coordinator import authenticated
from tests._coastal_operations import export_package

LANE = Path(authenticated.__file__).resolve().parent.parent / "authenticated_v1"
TRIO = ("bootstrap.py", "worker.py", "observer.py")


def _job(root):
    return dict(execution_contract=authenticated.EXECUTION_CONTRACT, stage="acquire",
                job_id="job:" + "a" * 24, lease_token="b" * 32, root=str(root))


def test_coordinator_launches_the_packaged_bootstrap(tmp_path):
    argv = authenticated.argv_for(_job(tmp_path), tmp_path / "job.json", tmp_path / "output")
    assert argv[0] == sys.executable and argv[1] == "-I"
    assert argv[3:] == ["--request", str(tmp_path / "job.json"), "--output", str(tmp_path / "output")]
    bootstrap = Path(argv[2])
    assert bootstrap.resolve() == LANE / "bootstrap.py"
    info = os.lstat(bootstrap)
    assert stat.S_ISREG(info.st_mode) and info.st_nlink == 1
    ast.parse(bootstrap.read_bytes(), filename=str(bootstrap))


def test_native_worker_trio_is_source_that_binds_together():
    trees = {}
    for name in TRIO:
        path = LANE / name
        assert stat.S_ISREG(os.lstat(path).st_mode), name
        trees[name] = ast.parse(path.read_bytes(), filename=str(path))
    # bootstrap.py loads the shared pre-import guard, then the worker's main.
    imports = [(node.module, [a.name for a in node.names]) for node in ast.walk(trees["bootstrap.py"])
               if isinstance(node, ast.ImportFrom)]
    assert ("skippercast.coastal.authenticated_v1.worker", ["main"]) in imports
    assert (LANE.parent / "_source_bootstrap.py").is_file()
    worker_defs = {node.name for node in trees["worker.py"].body if isinstance(node, ast.FunctionDef)}
    assert {"main", "run", "read_job", "validate_clock", "runtime_limits"} <= worker_defs
    # observer.implementation() hashes these lane files into every result; each must exist.
    hashed = None
    for node in ast.walk(trees["observer.py"]):
        if isinstance(node, ast.Tuple) and all(isinstance(e, ast.Constant) for e in node.elts):
            names = [e.value for e in node.elts]
            if "bootstrap.py" in names:
                hashed = names
    assert hashed and "worker.py" in hashed
    for name in hashed:
        assert (LANE / name).is_file(), name


@pytest.mark.gis
def test_isolated_bootstrap_validates_arguments_offline(tmp_path):
    """Real ``python -I`` launch from a source-only export; no request is ever served."""
    export = export_package(tmp_path / "export")
    bootstrap = export / "skippercast/coastal/authenticated_v1/bootstrap.py"
    assert bootstrap.read_bytes() == (LANE / "bootstrap.py").read_bytes()

    def launch(*args):
        return subprocess.run([sys.executable, "-I", str(bootstrap), *args], cwd=tmp_path,
                              capture_output=True, text=True, timeout=60)

    shown = launch("--help")
    assert shown.returncode == 0, shown.stderr
    assert "--request" in shown.stdout and "--output" in shown.stdout

    missing = launch()
    assert missing.returncode == 2 and "required" in missing.stderr

    outside = launch("--request", str(tmp_path / "job.json"), "--output", str(tmp_path / "out"))
    assert outside.returncode == 4 and not outside.stdout
    assert "authenticated worker refused" in outside.stderr
    assert "fixed owned job request namespace required" in outside.stderr
    assert not (tmp_path / "out").exists()

    # The same pre-import guard as the supervisor: compiled bytecode is refused
    # before any project module runs.
    (export / "skippercast/__pycache__").mkdir()
    poisoned = launch("--help")
    assert poisoned.returncode != 0 and "compiled bytecode" in poisoned.stderr
    assert not poisoned.stdout
