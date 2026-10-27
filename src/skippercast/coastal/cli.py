"""Inspect a coastal queue and the imported package without launching workers.

Mission preparation and execution use their existing dedicated launchers. This
interface does not enqueue, recover, rearm or run a native/rendering mission.
"""
import argparse
import hashlib
import importlib.metadata
from importlib.resources import files
import json
from pathlib import Path
import sqlite3
import sys

from .handoff.common import confined


def runtime_identity():
    """Report observed code/resources; metadata presence is not acceptance."""
    from .coordinator.loop import implementation_hashes

    code_sha, deps_sha = implementation_hashes(None)
    try:
        distribution = importlib.metadata.distribution("skippercast")
        package = {
            "metadata_found": True,
            "version": distribution.version,
            "distribution_root": str(distribution.locate_file("")),
        }
    except importlib.metadata.PackageNotFoundError:
        package = {"metadata_found": False, "version": None}
    dependencies = {}
    for name in ("rasterio", "pyproj", "shapely", "h5py", "numpy", "jsonschema"):
        try:
            dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            dependencies[name] = "unavailable"
    resources = []
    for resource in sorted(files("skippercast.coastal.resources").iterdir(), key=lambda p: p.name):
        if resource.name.endswith(".schema.json") and resource.is_file():
            data = resource.read_bytes()
            resources.append({"name": resource.name, "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest()})
    module = Path(__file__).resolve(strict=True)
    return {
        "schema": "coastal-runtime-identity-v1",
        "entrypoint": "skippercast.coastal.cli",
        "python": {"executable": sys.executable, "version": sys.version},
        "distribution": package,
        "imported_module": str(module),
        "imported_module_sha256": hashlib.sha256(module.read_bytes()).hexdigest(),
        "code_sha256": code_sha,
        "dependency_versions_sha256": deps_sha,
        "dependency_versions": dependencies,
        "schema_resources": resources,
        "acceptance": "identity-only; installed equivalence and native/render acceptance unverified",
    }


def queue_status(database):
    """Read the existing queue without creating or migrating its database."""
    if not database.exists():
        return {"schema": "coastal-coordinator-status-v1", "state": "uninitialized",
                "jobs": [], "events": 0, "charges": [], "progress": [],
                "last_tick_epoch": None}
    connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    try:
        # One read transaction keeps the counts, states and charges consistent.
        connection.execute("BEGIN")
        return {
            "schema": "coastal-coordinator-status-v1",
            "jobs": [dict(row) for row in connection.execute(
                "SELECT job_id,segment_id,stage,state,attempts,max_attempts,holds_json "
                "FROM jobs ORDER BY created,job_id")],
            "events": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "charges": [dict(row) for row in connection.execute("SELECT * FROM charges")],
            "progress": [dict(row) for row in connection.execute("SELECT * FROM region_progress")],
            "last_tick_epoch": connection.execute(
                "SELECT MAX(utc) FROM events WHERE kind='tick'").fetchone()[0],
        }
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--db", default="var/coastal/coordinator.sqlite")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="inspect an existing queue; never create it")
    commands.add_parser("identity", help="report imported code and packaged schema identities")
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("root must be an existing directory")
        result = (runtime_identity() if args.command == "identity" else
                  queue_status(confined(root, args.db, existing=False)))
    except (OSError, ValueError, sqlite3.Error) as error:
        print(json.dumps({"schema": "coastal-inspection-error-v1",
                          "error": type(error).__name__, "detail": str(error)}), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
