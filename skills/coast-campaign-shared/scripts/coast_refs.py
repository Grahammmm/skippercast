"""Offline, fail-closed typed references for campaign workflow tools (not product code)."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import stat

ROOT_ID = re.compile(r"(?:queue:[A-Za-z0-9_-]+|repo:[0-9a-f]{40}|archive:[A-Za-z0-9_-]+:[A-Za-z0-9_-]+|raw:campaign)\Z")
SHA = re.compile(r"[0-9a-f]{64}\Z")
REF_KEYS = {"root_id", "path", "sha256", "bytes"}


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def object_digest(value):
    """Producer object digest deliberately excludes the canonical file newline."""
    return hashlib.sha256(canonical(value)[:-1]).hexdigest()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def loads(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"nonfinite JSON number: {value}")
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
    canonical(value)  # also rejects overflow to inf (e.g. 1e999)
    return value


def relative_parts(path):
    if not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or "\0" in path:
        raise ValueError("reference needs a relative POSIX path")
    parts = path.split("/")
    if any(p in ("", ".", "..") or any(ord(c) < 32 for c in p) for p in parts):
        raise ValueError("invalid reference path component")
    return parts


@contextmanager
def directory_fd(path):
    """Walk the configured root itself without following even an ancestor symlink."""
    path = Path(path)
    if not path.is_absolute() or any(p in (".", "..") for p in path.parts):
        raise ValueError("operator root must be absolute and normalized")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


class Resolver:
    """Bindings are supplied by the operator; receipts can never add bindings.

    allowed_root_ids must come from the admitted card, independently of the binding file.
    Every root is disjoint. Reads return original bytes, never rewritten native receipts.
    """
    def __init__(self, bindings, *, allowed_root_ids):
        if not bindings or set(bindings) != set(allowed_root_ids):
            raise ValueError("unexpected or missing operator root binding")
        self.bindings = {}
        for root_id, path in bindings.items():
            if not ROOT_ID.fullmatch(root_id):
                raise ValueError("unknown root namespace")
            if not isinstance(path, str) or ".." in path.split("/") or "." in path.split("/"):
                raise ValueError("invalid root path")
            with directory_fd(path):
                pass
            self.bindings[root_id] = Path(path)
        paths = list(self.bindings.values())
        for i, path in enumerate(paths):
            for other in paths[i + 1:]:
                if path.is_relative_to(other) or other.is_relative_to(path):
                    raise ValueError("overlapping operator roots")

    def read(self, ref, *, retain=True):
        if not isinstance(ref, dict) or set(ref) != REF_KEYS:
            raise ValueError("typed Ref requires exactly root_id/path/sha256/bytes")
        if ref["root_id"] not in self.bindings:
            raise ValueError("unbound root_id")
        if not isinstance(ref["sha256"], str) or not SHA.fullmatch(ref["sha256"]):
            raise ValueError("invalid reference SHA256")
        if type(ref["bytes"]) is not int or ref["bytes"] < 0:
            raise ValueError("invalid reference byte count")
        parts = relative_parts(ref["path"])
        with directory_fd(self.bindings[ref["root_id"]]) as root:
            fd = os.dup(root)
            try:
                for part in parts[:-1]:
                    new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                    os.close(fd)
                    fd = new
                leaf = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    before = os.fstat(leaf)
                    if not stat.S_ISREG(before.st_mode):
                        raise ValueError("reference leaf is not a regular file")
                    if before.st_size != ref["bytes"]:
                        raise ValueError("reference byte count mismatch")
                    chunks = []
                    digest = hashlib.sha256()
                    size = 0
                    remaining = ref["bytes"] + 1
                    while remaining:
                        chunk = os.read(leaf, min(remaining, 1024 * 1024))
                        if not chunk:
                            break
                        digest.update(chunk)
                        size += len(chunk)
                        if retain:
                            chunks.append(chunk)
                        remaining -= len(chunk)
                    raw = b"".join(chunks)
                    after = os.fstat(leaf)
                    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
                    ):
                        raise ValueError("reference changed during read")
                finally:
                    os.close(leaf)
            finally:
                os.close(fd)
        if size != ref["bytes"] or digest.hexdigest() != ref["sha256"]:
            raise ValueError("reference SHA256/bytes mismatch")
        return raw


def native_ref(value, queue_id):
    """Explicit adapter ONLY for caller-identified native reference fields."""
    if not isinstance(value, dict) or not {"path", "sha256", "bytes"} <= value.keys():
        raise ValueError("native file reference required")
    if not queue_id.startswith("queue:"):
        raise ValueError("native refs require original queue namespace")
    return dict(root_id=queue_id, **{key: value[key] for key in ("path", "sha256", "bytes")})


def write_once(path, value):
    raw = canonical(value)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    return raw
