"""Offline guard for coordinator-owned mapping checkpoint jobs.

This is a private checkpoint helper, not a scheduler or a scientific approval
system. Evidence receipts establish that checks were recorded; they do not
establish scientific clearance.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any


ACTIVE_STATES = {"queued", "running", "ready_for_review", "reviewed", "publishing"}
TERMINAL_STATES = {"published", "blocked", "no_delta"}
STATES = ACTIVE_STATES | TERMINAL_STATES
DISPATCH_STATES = {"queued", "dispatching", "acknowledged"}
TRANSITIONS = {
    "queued": {"running", "blocked"},
    "running": {"ready_for_review", "blocked", "no_delta"},
    "ready_for_review": {"reviewed", "blocked"},
    "reviewed": {"publishing", "blocked"},
    "publishing": {"published", "blocked"},
    "published": set(), "blocked": {"queued"}, "no_delta": {"queued"},
}
IDENTITY_FIELDS = ("region", "reach", "method", "native_window")


class GuardError(ValueError):
    """Checkpoint violates the mapping handoff contract."""


def _required(job: dict[str, Any], field: str) -> Any:
    value = job.get(field)
    if value is None or value == "":
        raise GuardError(f"job {job.get('id', '<unknown>')} lacks {field}")
    return value


def _source_ids(job: dict[str, Any]) -> set[str]:
    sources = _required(job, "source_ids")
    if not isinstance(sources, list) or not sources or any(not isinstance(x, str) or not x for x in sources):
        raise GuardError(f"job {job.get('id', '<unknown>')} source_ids must be a non-empty string list")
    return set(sources)


def _writable_path(job: dict[str, Any]) -> str:
    return os.path.normcase(os.path.realpath(str(_required(job, "output_path"))))


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (all(left.get(k) == right.get(k) for k in IDENTITY_FIELDS)
            and bool(_source_ids(left) & _source_ids(right)))


def validate_checkpoint(checkpoint: dict[str, Any], *, base_dir: Path | None = None) -> None:
    """Validate coordinator and exclusive active claims in one handoff object."""
    coordinator = _required(checkpoint, "coordinator")
    jobs = checkpoint.get("jobs")
    if not isinstance(jobs, list):
        raise GuardError("checkpoint jobs must be an array")
    seen: set[str] = set()
    active: list[dict[str, Any]] = []
    for job in jobs:
        if not isinstance(job, dict):
            raise GuardError("each job must be an object")
        job_id = _required(job, "id")
        if job_id in seen:
            raise GuardError(f"duplicate job id: {job_id}")
        seen.add(job_id)
        state = _required(job, "state")
        if state not in STATES:
            raise GuardError(f"job {job_id} has invalid state {state!r}")
        _required(job, "owner")
        dispatch_state = _required(job, "dispatch_state")
        if dispatch_state not in DISPATCH_STATES:
            raise GuardError(f"job {job_id} has invalid dispatch_state {dispatch_state!r}")
        _required(job, "output_path")
        if state in ACTIVE_STATES:
            for field in IDENTITY_FIELDS:
                _required(job, field)
            _source_ids(job)
            active.append(job)
        if state == "published":
            _require_publication_receipts(job, base_dir)
    for i, job in enumerate(active):
        for other in active[i + 1:]:
            if _overlaps(job, other):
                raise GuardError(f"overlapping source/reach/method/window claim: {job['id']} and {other['id']}")
            if _writable_path(job) == _writable_path(other):
                raise GuardError(f"overlapping writable output path: {job['id']} and {other['id']}")
    # A dispatching job is deliberately retained as a claim. This validation
    # never changes or reassigns it; a coordinator must reconcile process state.
    _ = coordinator


def _require_publication_receipts(job: dict[str, Any], base_dir: Path | None) -> None:
    receipts = job.get("receipt_paths")
    if not isinstance(receipts, list):
        raise GuardError(f"published job {job['id']} needs rights, restriction, and live-readback receipts")
    resolved = []
    for item in receipts:
        if not isinstance(item, str) or not item:
            continue
        path = Path(item)
        resolved.append((path if path.is_absolute() else (base_dir or Path.cwd()) / path).resolve())
    required = {"rights", "restriction", "live_readback"}
    found: set[str] = set()
    for path in resolved:
        name = path.name.lower()
        if path.is_file():
            if "rights" in name: found.add("rights")
            if "restriction" in name or "mpa" in name: found.add("restriction")
            if "live" in name and ("readback" in name or "read-back" in name): found.add("live_readback")
    missing = sorted(required - found)
    if missing:
        raise GuardError(f"published job {job['id']} missing existing receipt(s): {', '.join(missing)}")


@contextmanager
def _exclusive_lock(path: Path):
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def update_job(path: str | Path, job_id: str, patch: dict[str, Any], *, actor: str) -> dict[str, Any]:
    """Coordinator-only atomic update, preserving every unrelated handoff field."""
    checkpoint_path = Path(path)
    with _exclusive_lock(checkpoint_path):
        try:
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GuardError(f"cannot read checkpoint: {exc}") from exc
        if actor != checkpoint.get("coordinator"):
            raise GuardError("only the named coordinator may update the checkpoint")
        jobs = checkpoint.get("jobs")
        if not isinstance(jobs, list):
            raise GuardError("checkpoint jobs must be an array")
        matches = [j for j in jobs if isinstance(j, dict) and j.get("id") == job_id]
        if len(matches) != 1:
            raise GuardError(f"expected one job {job_id!r}, found {len(matches)}")
        job = matches[0]
        if "id" in patch and patch["id"] != job_id:
            raise GuardError("job id cannot be changed")
        old, new = job.get("state"), patch.get("state", job.get("state"))
        if new != old and (old not in TRANSITIONS or new not in TRANSITIONS[old]):
            raise GuardError(f"invalid state transition {old!r} -> {new!r}")
        if job.get("dispatch_state") == "dispatching" and patch.get("owner", job.get("owner")) != job.get("owner"):
            raise GuardError("dispatching claim cannot be reassigned until process state is reconciled")
        job.update(patch)
        validate_checkpoint(checkpoint, base_dir=checkpoint_path.parent)
        _atomic_write(checkpoint_path, checkpoint)
        return checkpoint


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(dir_fd)
        finally: os.close(dir_fd)
    finally:
        if os.path.exists(temp_name): os.unlink(temp_name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint", type=Path)
    args = parser.parse_args()
    try:
        data = json.loads(args.checkpoint.read_text(encoding="utf-8"))
        validate_checkpoint(data, base_dir=args.checkpoint.parent)
    except (OSError, json.JSONDecodeError, GuardError) as exc:
        parser.error(str(exc))
    print(f"valid checkpoint: {len(data['jobs'])} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
