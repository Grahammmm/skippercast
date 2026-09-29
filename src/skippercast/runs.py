"""Run manifests: what a scheduled job read, wrote and concluded, as one JSON file.

    run = RunManifest.start("forecast-build")
    run.add_input("var/forecasts-published/gfs_global/manifest.json")
    run.source("gfs_global", "ok", duration_ms=31800, detail="built 2026-09-28T18:00:00Z")
    run.add_output("var/forecasts/index.json")
    run.region("morro-bay", "degraded", sources_ok=58, sources_total=62)  # multi-region jobs
    run.finish(exit_code=0)
    run.write("var/runs/forecast-build.json")

Or as a context manager, which records an escaping exception's class as the
run error and exit code 1 before re-raising it:

    with RunManifest.start("forecast-build") as run:
        ...

Paths are stored relative to the repository or working directory so a manifest
never publishes a machine path. `python -m skippercast.report` renders one as a
GitHub step summary. Standard library only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import subprocess
import time

from .log import run_id as current_run_id
from .platform.contracts import REPO, atomic_json

SCHEMA_VERSION = 1
OK_SOURCE_STATES = frozenset({"ok"})
ERROR_CHARS = 300


def stamp(moment):
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def git_sha(environ=None, root=REPO):
    """The commit being run: GITHUB_SHA in Actions, else `git rev-parse HEAD`, else None."""
    environ = os.environ if environ is None else environ
    sha = (environ.get("GITHUB_SHA") or "").strip()
    if sha:
        return sha
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and len(sha) == 40 else None


def file_digest(path):
    """sha256 and size of a file, streamed."""
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def public_path(path, roots=None):
    """A path relative to the repository or working directory; never an absolute machine path."""
    path = Path(path)
    if not path.is_absolute():
        return path.as_posix()
    resolved = path.resolve()
    for root in roots or (Path.cwd(), REPO):
        try:
            return resolved.relative_to(Path(root).resolve()).as_posix()
        except ValueError:
            continue
    return path.name


class RunManifest:
    """Mutable record of one job run; to_dict() is the published JSON."""

    def __init__(self, job, run_id, *, run_attempt=None, git_sha=None, started_at=None, clock=time.monotonic):
        if not job or not isinstance(job, str):
            raise ValueError("A run manifest needs a job name")
        self.job = job
        self.run_id = run_id
        self.run_attempt = run_attempt
        self.git_sha = git_sha
        self.started_at = started_at or datetime.now(timezone.utc)
        self.finished_at = None
        self.duration_ms = None
        self.exit_code = None
        self.status = None
        self.error = None
        self.inputs = []
        self.outputs = []
        self.sources = {}
        self.regions = {}
        self._clock = clock
        self._started = clock()

    @classmethod
    def start(cls, job, *, environ=None, root=REPO, **kwargs):
        """A manifest stamped with the GitHub run (or a local id), attempt and commit."""
        environ = os.environ if environ is None else environ
        attempt = (environ.get("GITHUB_RUN_ATTEMPT") or "").strip()
        kwargs.setdefault("run_attempt", int(attempt) if attempt.isdigit() else None)
        kwargs.setdefault("git_sha", git_sha(environ, root))
        return cls(job, current_run_id(environ), **kwargs)

    # -- recording ------------------------------------------------------------------

    def _file(self, path, role):
        if not Path(path).is_file():
            raise FileNotFoundError(f"Run {role} is not a file: {public_path(path)}")
        sha256, size = file_digest(path)
        return {"path": public_path(path), "sha256": sha256, "bytes": size}

    def add_input(self, path, *, optional=False):
        """Record a file the job read. An optional input that does not exist is skipped."""
        if optional and not Path(path).is_file():
            return None
        entry = self._file(path, "input")
        self.inputs.append(entry)
        return entry

    def add_output(self, path):
        """Record a file the job wrote (hash it after the final write)."""
        entry = self._file(path, "output")
        self.outputs.append(entry)
        return entry

    def source(self, ident, status, **fields):
        """Per-source outcome: status plus optional detail, error_class, duration_ms, http_status, ..."""
        if not ident or not isinstance(status, str) or not status:
            raise ValueError("A source outcome needs an id and a status")
        row = {"status": status, **{k: v for k, v in fields.items() if v is not None}}
        if isinstance(row.get("detail"), str):
            row["detail"] = row["detail"][:ERROR_CHARS]
        self.sources[str(ident)] = row
        return row

    def region(self, ident, status, **fields):
        """Per-region outcome for jobs that loop over regions: status plus counts, issues, error_class, ..."""
        if not ident or not isinstance(status, str) or not status:
            raise ValueError("A region outcome needs an id and a status")
        row = {"status": status, **{k: v for k, v in fields.items() if v is not None}}
        if isinstance(row.get("error"), str):
            row["error"] = row["error"][:ERROR_CHARS]
        self.regions[str(ident)] = row
        return row

    def finish(self, exit_code=0, *, error=None, status=None):
        """Close the run. Status: failed on a non-zero exit, degraded if any source or region is not ok, else ok."""
        self.finished_at = datetime.now(timezone.utc)
        self.duration_ms = max(0, round((self._clock() - self._started) * 1000))
        self.exit_code = int(exit_code)
        if error is not None:
            self.error = {"class": type(error).__name__, "message": str(error)[:ERROR_CHARS]}
        if status is None:
            if self.exit_code != 0 or self.error:
                status = "failed"
            elif any(row["status"] not in OK_SOURCE_STATES
                     for row in (*self.sources.values(), *self.regions.values())):
                status = "degraded"
            else:
                status = "ok"
        if status not in ("ok", "degraded", "failed"):
            raise ValueError(f"Unknown run status: {status}")
        self.status = status
        return self

    def __enter__(self):
        return self

    def __exit__(self, kind, error, traceback):
        if self.finished_at is None:
            if error is not None and not isinstance(error, SystemExit):
                self.finish(1, error=error)
            elif isinstance(error, SystemExit):
                code = error.code
                self.finish(code if isinstance(code, int) else (0 if code is None else 1))
            else:
                self.finish(0)
        return False

    # -- output ---------------------------------------------------------------------

    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "job": self.job,
            "run_id": self.run_id,
            "run_attempt": self.run_attempt,
            "git_sha": self.git_sha,
            "started_at": stamp(self.started_at),
            "finished_at": stamp(self.finished_at) if self.finished_at else None,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "exit_code": self.exit_code,
            "error": self.error,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "sources": dict(self.sources),
            "regions": dict(self.regions),
        }

    def write(self, path):
        """Atomically write the manifest; finishes an unfinished run as exit 0 first."""
        if self.finished_at is None:
            self.finish(0)
        return atomic_json(path, self.to_dict(), indent=1)

    def r2_key(self):
        """Where the manifest belongs in R2 (runs/<job>/<run_id>.json); uploading is the workflow's job."""
        suffix = f"-{self.run_attempt}" if self.run_attempt and self.run_attempt > 1 else ""
        return f"runs/{self.job}/{self.run_id}{suffix}.json"


def validate(document):
    """Minimal structural check used by the report CLI; raises ValueError."""
    if not isinstance(document, dict) or document.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Not a SkipperCast run manifest (schema_version 1)")
    for key in ("job", "run_id", "started_at", "status", "inputs", "outputs", "sources"):
        if key not in document:
            raise ValueError(f"Run manifest is missing {key}")
    if document["status"] not in ("ok", "degraded", "failed"):
        raise ValueError("Invalid run status")
    if not isinstance(document["sources"], dict) or not all(isinstance(r, dict) and "status" in r
                                                             for r in document["sources"].values()):
        raise ValueError("Run manifest sources must map ids to status rows")
    regions = document.get("regions", {})  # optional: added for the regional refresh jobs
    if not isinstance(regions, dict) or not all(isinstance(r, dict) and "status" in r for r in regions.values()):
        raise ValueError("Run manifest regions must map ids to status rows")
    return document
