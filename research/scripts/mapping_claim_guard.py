"""Offline guard for coordinator-owned mapping checkpoint jobs.

This is a private checkpoint helper, not a scheduler or a scientific approval
system. Evidence receipts establish that checks were recorded; they do not
establish scientific clearance.
"""
from __future__ import annotations

import argparse
import hashlib
import fcntl
import json
import os
import math
import re
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


def _window(job: dict[str, Any]) -> tuple[float, float, float, float]:
    """Return a validated native pixel rectangle (x, y, width, height)."""
    value = _required(job, "native_window")
    if isinstance(value, dict):
        value = [value.get("x"), value.get("y"), value.get("width"), value.get("height")]
    if (not isinstance(value, (list, tuple)) or len(value) != 4
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in value)
            or value[2] <= 0 or value[3] <= 0):
        raise GuardError(f"job {job.get('id', '<unknown>')} native_window must be [x, y, width, height]")
    return tuple(float(v) for v in value)


def _writable_path(job: dict[str, Any], base_dir: Path | None) -> str:
    path = Path(str(_required(job, "output_path")))
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    return os.path.normcase(str(path.resolve(strict=False)))


def _path_scopes_overlap(a: str, b: str) -> bool:
    try:
        common = os.path.commonpath((a, b))
    except ValueError:  # different drives on Windows
        return False
    return common == a or common == b


def _rectangles_overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def _overlaps(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (all(left.get(k) == right.get(k) for k in ("region", "reach", "method"))
            and bool(_source_ids(left) & _source_ids(right))
            and _rectangles_overlap(_window(left), _window(right)))


EXECUTION_FIELDS = ("id", "owner", "attempt", "dispatch_id", "process_id")
CLAIM_FIELDS = ("region", "reach", "method", "source_ids", "native_window", "output_path")
PUBLICATION_KINDS = {"rights", "restriction", "live_readback"}
PUBLICATION_RECEIPT_SCHEMA = "sc-mapping-publication-receipt/1"


def _execution_identity(job: dict[str, Any]) -> dict[str, Any]:
    # Missing identity is preserved as unknown, never inferred from age or state.
    return {field: job.get(field) for field in EXECUTION_FIELDS}


def _execution_claim(job: dict[str, Any]) -> dict[str, Any] | None:
    claim = job.get("execution_claim")
    if claim is not None:
        if not isinstance(claim, dict) or set(claim) != set(EXECUTION_FIELDS):
            raise GuardError("execution_claim must contain the recorded execution identity")
        if claim["id"] != job.get("id"):
            raise GuardError("execution_claim job id does not match")
        return claim
    # Legacy checkpoints fail closed when execution may have started.
    if job.get("state") == "running" or job.get("dispatch_state") in {"dispatching", "acknowledged"}:
        return _execution_identity(job)
    return None


def _stop_proof(identity: dict[str, Any] | None, proof: Any,
                checkpoint: dict[str, Any], base_dir: Path | None) -> bool:
    """Check a coordinator attestation against the *prior* execution identity.

    Receipt JSON repeats the identity, coordinator, stopped=true and stopped_utc.
    The attestation pins its bytes with sha256. This is bookkeeping evidence;
    the coordinator remains responsible for actually checking the process.
    """
    if identity is None or any(identity.get(k) is None or identity[k] == "" for k in EXECUTION_FIELDS):
        return False
    if not isinstance(proof, dict) or proof.get("verified") is not True:
        return False
    if proof.get("verified_by") != checkpoint.get("coordinator"):
        return False
    if not isinstance(proof.get("stopped_utc"), str) or not proof["stopped_utc"].strip():
        return False
    receipt = proof.get("path")
    if not isinstance(receipt, str) or not receipt:
        return False
    path = Path(receipt)
    if not path.is_absolute():
        path = (base_dir or Path.cwd()) / path
    try:
        raw = path.read_bytes()
        content = json.loads(raw)
    except (OSError, ValueError, UnicodeError):
        return False
    return (isinstance(content, dict)
            and proof.get("sha256") == hashlib.sha256(raw).hexdigest()
            and content.get("stopped") is True
            and content.get("verified_by") == checkpoint.get("coordinator")
            and content.get("stopped_utc") == proof["stopped_utc"]
            and all(type(content.get(k)) is type(identity[k]) and content.get(k) == identity[k]
                    for k in EXECUTION_FIELDS))


def validate_checkpoint(checkpoint: dict[str, Any], *, base_dir: Path | None = None,
                        checkpoint_path: Path | None = None) -> None:
    """Validate coordinator and exclusive active claims in one handoff object.

    Pass checkpoint_path (the file this object is persisted to) so publication
    evidence that aliases the checkpoint itself is refused.
    """
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
        identity = _execution_claim(job)
        unresolved_execution = identity is not None and not _stop_proof(
            identity, job.get("stopped_process_receipt"), checkpoint, base_dir)
        if state in ACTIVE_STATES or unresolved_execution:
            for field in ("region", "reach", "method"):
                _required(job, field)
            _window(job)
            _source_ids(job)
            active.append(job)
        if state == "published":
            _require_publication_receipts(job, base_dir, checkpoint_path)
    for i, job in enumerate(active):
        for other in active[i + 1:]:
            if _overlaps(job, other):
                raise GuardError(f"overlapping source/reach/method/window claim: {job['id']} and {other['id']}")
            if _path_scopes_overlap(_writable_path(job, base_dir), _writable_path(other, base_dir)):
                raise GuardError(f"overlapping writable output path: {job['id']} and {other['id']}")
    # Execution claims survive status edits until matching process reconciliation.
    _ = coordinator


def _same_file(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:  # the checkpoint is absent, so nothing can alias it
        return False


def _pinned_publication_file(ref: Any, root: Path, label: str, *, receipt: bool = False,
                             checkpoint_path: Path | None = None) -> bytes | None:
    """Verify an exact {path, sha256} reference; parse only bytes we verified.

    A reference must not be the checkpoint itself (by path, symlink or hard
    link): recording the transition rewrites those bytes, so the pin could not
    survive the update it authorises.
    """
    if (not isinstance(ref, dict) or ref.keys() != {"path", "sha256"}
            or not isinstance(ref["path"], str) or not ref["path"].strip()
            or not isinstance(ref["sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", ref["sha256"])):
        raise GuardError(f"{label} needs a path and SHA-256")
    path = root / ref["path"]
    try:
        if not path.is_file():
            raise GuardError(f"{label} is not a regular file")
        if checkpoint_path is not None and _same_file(path, checkpoint_path):
            raise GuardError(f"{label} must not be the checkpoint itself")
        with path.open("rb") as stream:
            if not stream.read(1):
                raise GuardError(f"{label} is empty")
            stream.seek(0)
            raw = stream.read() if receipt else None
            digest = hashlib.sha256(raw) if raw is not None else hashlib.file_digest(stream, "sha256")
    except OSError as exc:
        raise GuardError(f"cannot read {label}") from exc
    if digest.hexdigest() != ref["sha256"]:
        raise GuardError(f"{label} SHA-256 does not match")
    return raw


def _require_publication_receipts(job: dict[str, Any], base_dir: Path | None,
                                  checkpoint_path: Path | None = None) -> None:
    """Check coordinator attestations of existing producer evidence, not approval.

    Pin the exact artifact (or complete release manifest) in publication_artifact
    before the transition. publication_receipts maps each kind to {path, sha256}.
    Each v1 JSON receipt records a PASS for that job, attempt and artifact, and
    pins the underlying producer output with evidence={path, sha256}. Paths are
    checkpoint-relative or absolute. Generic receipt_paths are not proof.
    The coordinator still interprets producer output and checks currency through
    the existing review/release route; this guard does not contact live services.
    """
    refs = job.get("publication_receipts")
    if not isinstance(refs, dict) or refs.keys() != PUBLICATION_KINDS:
        raise GuardError("publication evidence needs rights, restriction, and live-readback receipts")
    attempt = job.get("attempt")
    if type(attempt) is not int or attempt < 1:
        raise GuardError("publication evidence requires a positive job attempt")
    root = base_dir or Path.cwd()
    artifact = _required(job, "publication_artifact")
    _pinned_publication_file(artifact, root, "publication artifact", checkpoint_path=checkpoint_path)
    for kind in sorted(PUBLICATION_KINDS):
        label = f"{kind} receipt"
        raw = _pinned_publication_file(refs[kind], root, label, receipt=True,
                                       checkpoint_path=checkpoint_path)
        try:
            content = json.loads(raw or b"")
        except (ValueError, RecursionError) as exc:
            raise GuardError(f"{label} must be valid JSON") from exc
        expected = {"schema": PUBLICATION_RECEIPT_SCHEMA, "kind": kind, "status": "PASS",
                    "job_id": job["id"], "attempt": attempt, "artifact_sha256": artifact["sha256"]}
        if (not isinstance(content, dict) or type(content.get("attempt")) is not int
                or not isinstance(content.get("job_id"), str) or not content["job_id"].strip()
                or any(content.get(k) != v for k, v in expected.items())):
            raise GuardError(f"{label} does not attest PASS for this job, attempt and artifact")
        _pinned_publication_file(content.get("evidence"), root, f"{kind} producer evidence",
                                 checkpoint_path=checkpoint_path)


@contextmanager
def _exclusive_lock(path: Path):
    if path.is_symlink() or path != path.resolve(strict=False):
        raise GuardError("checkpoint path must be canonical and must not be a symlink")
    lock_path = path.with_name(path.name + ".lock")
    if lock_path.is_symlink():
        raise GuardError("checkpoint lock path must not be a symlink")
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
    if checkpoint_path.is_symlink():
        raise GuardError("checkpoint path must not be a symlink")
    # Resolve parent aliases (for example macOS /var -> /private/var) once so
    # lock and replacement always address the same canonical checkpoint.
    checkpoint_path = checkpoint_path.resolve(strict=False)
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
        if "execution_claim" in patch:
            raise GuardError("execution_claim is guard-owned and cannot be patched")
        identity = _execution_claim(job)
        proof = patch.get("stopped_process_receipt", job.get("stopped_process_receipt"))
        stopped = _stop_proof(identity, proof, checkpoint, checkpoint_path.parent)
        owner_changed = patch.get("owner", job.get("owner")) != job.get("owner")
        identity_changed = any(patch.get(k, job.get(k)) != job.get(k) for k in EXECUTION_FIELDS)
        if owner_changed and not stopped:
            raise GuardError("owner reassignment requires an existing verified stopped-process receipt")
        if identity is not None and not stopped:
            changed_fields = {k for k in EXECUTION_FIELDS if patch.get(k, job.get(k)) != job.get(k)}
            # A coordinator may record an identity learned after dispatch (for
            # example process_id at acknowledgement), but cannot replace it.
            if any(k not in {"dispatch_id", "process_id"} or identity.get(k) not in (None, "")
                   or not isinstance(patch.get(k), str) or not patch[k].strip() for k in changed_fields):
                raise GuardError("execution identity cannot change before stopped-process reconciliation")
            identity = dict(identity, **{k: patch[k] for k in changed_fields})
            if any(patch.get(k, job.get(k)) != job.get(k) for k in CLAIM_FIELDS):
                raise GuardError("occupied claim scope cannot change before stopped-process reconciliation")
        candidate = dict(job, **patch)
        if new == "published" and any(
                type(candidate.get(k)) is not type(job.get(k)) or candidate.get(k) != job.get(k)
                for k in ("attempt", "publication_artifact")):
            raise GuardError("cannot change the recorded attempt or artifact when recording publication")
        if owner_changed:
            if candidate.get("dispatch_state") == "dispatching":
                raise GuardError("stopped claim must leave dispatching before reassignment")
            if new == "running":
                raise GuardError("reassigned job cannot remain running")
        if old == "queued" and new == "running" and candidate.get("dispatch_state") != "acknowledged":
            raise GuardError("queued job cannot enter running until dispatch is acknowledged")
        # Persist observed execution before a status edit can hide it. New
        # executions require a fresh identity; prior receipts cannot stop them.
        starts_execution = (new == "running" or candidate.get("dispatch_state") == "dispatching"
                            or candidate.get("dispatch_state") == "acknowledged")
        if identity is None:
            if starts_execution:
                job["execution_claim"] = _execution_identity(candidate)
        elif stopped and starts_execution and (
                identity_changed or (old != "running" and new == "running")
                or (candidate.get("dispatch_state") != job.get("dispatch_state")
                    and candidate.get("dispatch_state") in {"dispatching", "acknowledged"})):
            if _execution_identity(candidate) == identity:
                raise GuardError("new execution requires a fresh execution identity")
            if owner_changed:
                # Reassignment must first return to queued dispatch, above.
                raise GuardError("reassigned job must queue before a new execution")
            job["execution_claim"] = _execution_identity(candidate)
        else:
            job["execution_claim"] = dict(identity)
        job.update(patch)
        validate_checkpoint(checkpoint, base_dir=checkpoint_path.parent, checkpoint_path=checkpoint_path)
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
        validate_checkpoint(data, base_dir=args.checkpoint.parent, checkpoint_path=args.checkpoint)
    except (OSError, json.JSONDecodeError, GuardError) as exc:
        parser.error(str(exc))
    print(f"valid checkpoint: {len(data['jobs'])} jobs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
