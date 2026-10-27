"""Finite source-once engineering adapter; not an ordered-worker release route.

One durable source reservation precedes original access. Consumers inherit a sealed
FD, never a filename fallback. Owner loss forbids reopening under the same grant.
The existing ordered supervisor cannot transfer this capability yet.
"""
import copy
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import time
import uuid
from ..budget import Budget
from ..receipts import atomic_json, digest
from ..runner import boot_id

CONTRACT = "coastal-batch-source-reuse-v1"
SEALS = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL
MAX_BYTES = 64 * 1024 * 1024

def source_admissions(grant):
    if grant.get("saved_area_continuation_contract") is not None:
        from ..coordinator.saved_area import continuation_grant
        continuation_grant(grant)
        return 6
    contract = grant.get("source_reuse_contract")
    if contract not in (None, CONTRACT):
        raise ValueError("unknown source reuse contract")
    count = grant.get("window_count", len(grant.get("window_set", [])) or 4)
    if type(count) is not int or not 1 <= count <= 4:
        raise ValueError("bounded window count required")
    return 1 if contract else 2 * count

def source_volume_cap(grant):
    size = grant.get("source", {}).get("bytes")
    if type(size) is not int or not 0 < size <= MAX_BYTES:
        raise ValueError("bounded source size required")
    return source_admissions(grant) * size

def _process(pid):
    text = Path(f"/proc/{pid}/stat").read_text()
    fields = text[text.rindex(")") + 2:].split()
    if fields[0] in ("Z", "X"):
        raise ValueError("batch owner stopped")
    return [pid, fields[19], boot_id()]

def _hash_fd(fd, size):
    result = hashlib.sha256()
    for offset in range(0, size, 1024 * 1024):
        data = os.pread(fd, min(1024 * 1024, size - offset), offset)
        if not data:
            raise ValueError("sealed source truncated")
        result.update(data)
    return result.hexdigest()

def _open_source(root, leaf):
    # All ancestor directories and the leaf are opened without symlink following.
    root = Path(os.path.abspath(root))
    if Path(leaf).parts != (leaf,) or leaf in (".", ".."):
        raise ValueError("exact source leaf required")
    directory = os.open("/", os.O_DIRECTORY | os.O_RDONLY)
    try:
        for part in root.parts[1:]:
            next_fd = os.open(part, os.O_DIRECTORY | os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_fd
        return os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)

def _fingerprint(st):
    return (st.st_dev,st.st_ino,st.st_mode,st.st_size,st.st_mtime_ns,st.st_ctime_ns)

def _load(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or not 0 < before.st_size <= 131072:
            raise ValueError("bounded single-link batch control required")
        data = bytearray()
        while len(data) < before.st_size:
            chunk = os.read(fd, before.st_size-len(data))
            if not chunk: raise ValueError("batch control truncated")
            data.extend(chunk)
        if _fingerprint(os.fstat(fd)) != _fingerprint(before): raise ValueError("batch control changed while reading")
        return json.loads(data)
    finally:
        os.close(fd)

class BatchOwner:
    """A live owner and immutable ledger, explicitly created by an admission caller.

    This adapter does not attest scientific approval or authenticate a production
    Store lease. It is usable only after a caller independently validates release;
    the ordered native adapter deliberately refuses this contract today.
    """
    @classmethod
    def create(cls, path, grant, budget, *, runtime_budget, deadline_monotonic):
        if (type(budget) is not Budget or type(runtime_budget) is not Budget
            or runtime_budget.path.resolve() == budget.path.resolve() or runtime_budget.limits.bytes != 0
            or runtime_budget.limits.requests != 0 or grant.get("source_reuse_contract") != CONTRACT):
            raise ValueError("real Budget and explicit batch contract required")
        size = source_volume_cap(grant)
        if budget.limits.bytes != size or budget.limits.requests != 0 or budget.limits.attempts_per_candidate != 1:
            raise ValueError("exact one-copy no-retry source Budget required")
        source = grant["source"]
        if not re.fullmatch("[a-f0-9]{64}", str(source.get("sha256", ""))):
            raise ValueError("exact source SHA required")
        windows = grant.get("window_set")
        if (not isinstance(windows, list) or not 1 <= len(windows) <= 4
            or any(not isinstance(w, list) or len(w) != 4 or any(type(x) is not int for x in w)
                   or min(w[:2]) < 0 or not 1 <= w[2] == w[3] <= 128 for w in windows)
            or len({tuple(w) for w in windows}) != len(windows)):
            raise ValueError("finite exact square windows required")
        for i, a in enumerate(windows):
            for b in windows[i+1:]:
                if a[0] < b[0]+b[2] and b[0] < a[0]+a[2] and a[1] < b[1]+b[3] and b[1] < a[1]+a[3]:
                    raise ValueError("overlapping windows")
        now = time.monotonic()
        if (not isinstance(deadline_monotonic, (int, float)) or isinstance(deadline_monotonic, bool)
            or not math.isfinite(deadline_monotonic) or not now < deadline_monotonic <= now + 3600):
            raise ValueError("finite immutable batch deadline required")
        obj = cls()
        obj.path = Path(path).absolute()
        obj.path.parent.mkdir(parents=True, exist_ok=True)
        obj.fd = -1
        obj.origin_fd = -1
        obj.budget = budget
        obj.runtime_budget = runtime_budget
        obj.grant = copy.deepcopy(grant)
        obj.state = dict(schema=CONTRACT, grant_sha=digest(grant), source=copy.deepcopy(source),
                         windows=windows, owner=_process(os.getpid()), deadline=deadline_monotonic,
                         generation=uuid.uuid4().hex, state="admitted", leases={},
                         source_ledger=str(budget.path.resolve()), runtime_ledger=str(runtime_budget.path.resolve()))
        # Exclusive durable intent BEFORE reserve/open; existing/uncertain batch cannot be retried.
        fd = os.open(obj.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as out:
            json.dump(obj.state, out, sort_keys=True); out.flush(); os.fsync(out.fileno())
        reservation = "source-once-" + obj.state["generation"]
        obj.state["source_reservation"] = reservation
        try:
            budget.reserve(reservation, bytes=size, candidate=obj.state["grant_sha"])
        except BaseException:
            obj.state["state"] = "refused"
            atomic_json(obj.path, obj.state)
            raise
        obj.state["state"] = "copying"
        atomic_json(obj.path, obj.state)
        original = -1
        try:
            original = _open_source(grant["source_root"], grant["source_relative_path"])
            before = os.fstat(original)
            if not stat.S_ISREG(before.st_mode) or before.st_size != size:
                raise ValueError("source size/type differs")
            obj.fd = os.memfd_create("coastal-source-once", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
            h = hashlib.sha256(); copied = 0
            while copied < size:
                if time.monotonic() >= deadline_monotonic:
                    raise ValueError("batch expired during original copy")
                part = os.read(original, min(1024*1024, size-copied))
                if not part: raise ValueError("source truncated")
                h.update(part); copied += len(part)
                offset = 0
                while offset < len(part):
                    written = os.write(obj.fd, part[offset:])
                    if written <= 0: raise ValueError("copy stalled")
                    offset += written
            if os.read(original, 1) or _fingerprint(os.fstat(original)) != _fingerprint(before) or h.hexdigest() != source["sha256"]:
                raise ValueError("source changed or hash differs")
            fcntl.fcntl(obj.fd, fcntl.F_ADD_SEALS, SEALS)
            if _hash_fd(obj.fd, size) != source["sha256"]:
                raise ValueError("sealed copy hash differs")
            if time.monotonic() >= deadline_monotonic:
                raise ValueError("batch expired during authentication")
            st = os.fstat(obj.fd)
            obj.state.update(state="active", fd_identity=[st.st_dev, st.st_ino, st.st_size],
                             source_bytes_read=copied, source_full_hash_passes=1,
                             origin_path=str(Path(grant["source_root"])/grant["source_relative_path"]),
                             origin_fingerprint=list((before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)),
                             origin_fd=original,
                             sealed_full_hash_passes=1, original_eof_probe_requested_bytes=1)
            atomic_json(obj.path, obj.state)
            obj.origin_fd = original
            original = -1
            return obj
        except BaseException:
            obj.state["state"] = "uncertain"
            atomic_json(obj.path, obj.state)
            if obj.fd >= 0: os.close(obj.fd); obj.fd = -1
            raise
        finally:
            if original >= 0: os.close(original)

    def _check(self):
        persisted = _load(self.path)
        if persisted != self.state or self.state["owner"] != _process(os.getpid()):
            raise ValueError("batch ledger/owner changed")
        if self.fd < 0 or self.state["state"] != "active" or time.monotonic() >= self.state["deadline"]:
            raise ValueError("batch inactive or expired")
        _check_origin(self.state)

    def lease(self, index, stage, token):
        self._check()
        if type(index) is not int or not 0 <= index < len(self.state["windows"]) or stage not in ("acquire", "qualify"):
            raise ValueError("window/stage outside batch")
        if not isinstance(token, str) or not re.fullmatch("[a-f0-9]{32}", token):
            raise ValueError("exact lease token required")
        key = f"{index}:{stage}"
        if key in self.state["leases"]:
            raise ValueError("duplicate/uncertain phase cannot reacquire source capability")
        if stage == "qualify" and self.state["leases"].get(f"{index}:acquire", {}).get("state") != "completed":
            raise ValueError("qualification requires committed acquisition")
        self.runtime_budget.reserve(token, bytes=0, candidate=key)
        self.state["leases"][key] = dict(token=token, state="leased")
        atomic_json(self.path, self.state)
        return dict(batch_path=str(self.path), grant_sha=self.state["grant_sha"], generation=self.state["generation"],
                    key=key, token=token, source=copy.deepcopy(self.state["source"]),
                    owner=self.state["owner"], fd_identity=self.state["fd_identity"], deadline=self.state["deadline"])

    def complete(self, certificate, result_sha):
        self._check()
        if not re.fullmatch("[a-f0-9]{64}", str(result_sha)):
            raise ValueError("result SHA required")
        if any(certificate.get(k) != self.state[k] for k in ("grant_sha","generation","source","owner","fd_identity","deadline")):
            raise ValueError("completion batch identity changed")
        key = certificate["key"]
        expected = self.state["leases"].get(key)
        if not expected or expected["token"] != certificate["token"]:
            raise ValueError("lease fenced")
        if expected["state"] == "completed":
            if expected["result_sha"] != result_sha: raise ValueError("duplicate result changed")
            return False
        expected.update(state="completed", result_sha=result_sha)
        atomic_json(self.path, self.state)
        return True

    def close(self):
        if self.origin_fd >= 0:
            os.close(self.origin_fd); self.origin_fd = -1
        if self.fd >= 0:
            os.close(self.fd); self.fd = -1
            self.state["state"] = "closed"
            atomic_json(self.path, self.state)

def _check_origin(state):
    expected = state["origin_fingerprint"]
    for path in (state["origin_path"], f"/proc/{state['owner'][0]}/fd/{state['origin_fd']}"):
        st = os.stat(path, follow_symlinks=path.startswith("/proc/"))
        if [st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns,st.st_ctime_ns] != expected:
            raise ValueError("source origin metadata mutated")

def validate_consumer(fd, certificate, *, expected_grant_sha, window, stage, token):
    """Validate inherited FD + durable owner/lease fences; no path-based fallback.

    Caller must separately validate its real Store lease. Hash input is sealed-copy
    I/O, never an additional original-source admission.
    """
    state = _load(certificate["batch_path"])
    key = certificate["key"]
    if (state["state"] != "active" or time.monotonic() >= state["deadline"]
        or state["owner"] != _process(state["owner"][0])
        or state["owner"] != certificate["owner"]
        or state["grant_sha"] != expected_grant_sha or certificate["grant_sha"] != expected_grant_sha
        or state["generation"] != certificate["generation"] or state["deadline"] != certificate["deadline"]
        or state["source"] != certificate["source"]):
        raise ValueError("batch owner/identity/clock fenced")
    _check_origin(state)
    index, actual_stage = key.split(":")
    if (actual_stage != stage or state["windows"][int(index)] != window or certificate["token"] != token
        or state["leases"].get(key) != dict(token=token, state="leased")):
        raise ValueError("consumer window/stage/lease fenced")
    st = os.fstat(fd)
    if ([st.st_dev, st.st_ino, st.st_size] != state["fd_identity"]
        or certificate["fd_identity"] != state["fd_identity"]
        or fcntl.fcntl(fd, fcntl.F_GET_SEALS) & SEALS != SEALS):
        raise ValueError("inherited FD identity or seals differ")
    if _hash_fd(fd, st.st_size) != state["source"]["sha256"]:
        raise ValueError("sealed consumer verification differs")
    if (_load(certificate["batch_path"]) != state or time.monotonic() >= state["deadline"]
        or state["owner"] != _process(state["owner"][0])):
        raise ValueError("batch fenced during sealed verification")
    _check_origin(state)
    return dict(source=copy.deepcopy(state["source"]), original_source_bytes_read=0,
                sealed_snapshot_bytes_hashed=st.st_size, scientific_acceptance=False)
