"""Crash-durable receipts and bounded hashing for private coastal work."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
from typing import Protocol


class Clock(Protocol):
    def time(self) -> float: ...
    def monotonic(self) -> float: ...


class SystemClock:
    def time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()


SYSTEM_CLOCK = SystemClock()


def epoch(clock=None) -> float:
    """Accept the repository's datetime callable and epoch-clock conventions."""
    clock = SYSTEM_CLOCK if clock is None else clock
    if hasattr(clock, "time"):
        value = clock.time()
    elif hasattr(clock, "timestamp"):
        value = clock.timestamp()
    else:
        value = clock()
        if isinstance(value, datetime):
            if value.tzinfo is None:
                raise ValueError("clock returned a naive datetime")
            value = value.timestamp()
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("clock must return a finite instant")
    return value


def monotonic(clock=None) -> float:
    clock = SYSTEM_CLOCK if clock is None else clock
    # Legacy datetime-only test clocks have no monotonic source. Their epoch is
    # useful for deterministic tests; ledger high-water marks still prevent refunds.
    value = clock.monotonic() if hasattr(clock, "monotonic") else epoch(clock)
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("monotonic clock must be finite")
    return value


def utc(clock=None) -> str:
    return datetime.fromtimestamp(epoch(clock), timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(obj) -> str:
    return hashlib.sha256(canonical_json(obj)).hexdigest()


_MANAGED_WRITES = ContextVar("coastal_managed_writes", default=None)

def managed_configuration():
    current = _MANAGED_WRITES.get()
    return json.loads(canonical_json(current[1])) if current is not None else None

def managed_writer():
    current = _MANAGED_WRITES.get()
    return current[0] if current is not None else None

@contextmanager
def managed_writes(configuration):
    """Explicit grant-bound checkpoint scope; this grants no native authority."""
    if configuration is None:
        yield
        return
    configuration = json.loads(canonical_json(configuration))
    if (not isinstance(configuration, dict)
            or set(configuration) != {"grant", "grant_digest", "role", "max_bytes"}
            or not isinstance(configuration["grant"], dict)
            or configuration["grant_digest"] != digest(configuration["grant"])
            or configuration["role"] not in {"native", "mapping", "render", "control"}
            or type(configuration["max_bytes"]) is not int
            or not 0 < configuration["max_bytes"] <= 131072):
        raise ValueError("exact immutable managed checkpoint configuration required")
    from .output_writer import ManagedOutputs
    writer = ManagedOutputs(configuration["grant"]["output_root"],
                            configuration["grant"], configuration["grant_digest"])
    writer.audit()
    token = _MANAGED_WRITES.set((writer, configuration))
    try:
        yield writer
    finally:
        _MANAGED_WRITES.reset(token)


def atomic_json(path, obj, *, fsync=True) -> None:
    """Replace one receipt only after its complete bytes have reached disk.

    The parent directory must exist. Unique sibling temporaries avoid collisions;
    syncing the directory makes the rename durable as well as the file contents.
    """
    path = Path(path)
    current = _MANAGED_WRITES.get()
    if current is not None:
        writer, configuration = current
        name = writer.relative_path(path)
        writer.write_checkpoint(name, obj, role=configuration["role"],
                                max_bytes=configuration["max_bytes"],
                                intent="checkpoint:" + name, max_updates=1024)
        return
    data = canonical_json(obj) + b"\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            if fsync:
                os.fsync(stream.fileno())
        os.replace(temporary, path)
        if fsync:
            directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def file_sha256(path, cap=None, deadline=None, *, clock=None, chunk_bytes=1024 * 1024) -> str:
    """Hash bytes within a byte cap and optional epoch deadline; never sample."""
    if cap is not None and (isinstance(cap, bool) or not isinstance(cap, int) or cap < 0):
        raise ValueError("hash cap must be a non-negative integer")
    if isinstance(chunk_bytes, bool) or not isinstance(chunk_bytes, int) or chunk_bytes <= 0:
        raise ValueError("hash chunk_bytes must be a positive integer")
    if deadline is not None and not math.isfinite(float(deadline)):
        raise ValueError("hash deadline must be finite")
    sha = hashlib.sha256()
    count = 0
    with open(path, "rb") as stream:
        if cap is not None and os.fstat(stream.fileno()).st_size > cap:
            raise ValueError("hash byte cap exceeded")
        while True:
            if deadline is not None and epoch(clock) >= float(deadline):
                raise TimeoutError("hash deadline exceeded")
            part = stream.read(chunk_bytes)
            if not part:
                return sha.hexdigest()
            count += len(part)
            if cap is not None and count > cap:
                raise ValueError("hash byte cap exceeded")
            sha.update(part)


def verified_artifact(root, path, sha256, bytes):
    """Return a verified root-confined regular artifact, rejecting symlink escapes."""
    root = Path(root).resolve(strict=True)
    candidate = Path(path)
    candidate = (root / candidate if not candidate.is_absolute() else candidate).resolve(strict=True)
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ValueError("artifact is not a regular file inside the artifact root")
    if isinstance(bytes, bool) or not isinstance(bytes, int) or bytes < 0:
        raise ValueError("artifact bytes must be a non-negative integer")
    if not isinstance(sha256, str) or len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError("artifact sha256 must be lowercase hexadecimal")
    if candidate.stat().st_size != bytes or file_sha256(candidate, cap=bytes) != sha256:
        raise ValueError("artifact hash or size mismatch")
    return candidate


def provenance(source_url, acquired_utc, catalog_sha, sample_sha, code_sha, deps_sha, libs):
    """Bind provenance to supplied observations; never infer missing library facts."""
    if not isinstance(libs, dict) or not libs:
        raise ValueError("provenance requires observed library versions")
    values = dict(source_url=source_url, acquired_utc=acquired_utc, catalog_sha=catalog_sha,
                  sample_sha=sample_sha, code_sha=code_sha, deps_sha=deps_sha, libs=dict(libs))
    for key in ("catalog_sha", "sample_sha", "code_sha", "deps_sha"):
        value = values[key]
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError(f"provenance {key} is not a SHA-256")
    return values
