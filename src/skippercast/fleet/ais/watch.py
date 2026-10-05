"""The listener's watch list: ``<FLEET_VAR>/<region>/ais/watch.json`` (design.md section 10).

The processor job (CF-46) refreshes this file from the Worker each run with
``write_watch``; the listener re-reads it every ``RELOAD_SECONDS`` with
``WatchFile.poll`` and never talks to the Worker itself (it holds no GitHub
identity). Format, version 1::

    {"schema_version": 1,
     "region": "XX",
     "generated_at": "2026-08-01T12:03:11Z",
     "watched": [367000001, 367000002]}

``watched`` lists the MMSIs whose positions go to the ``positions`` table:
integers 1..999,999,999, sorted, no duplicates. Candidates are not listed; their
positions inside a harbor geofence reach ``discovery`` like any unwatched
vessel's. The file is written atomically (temporary file, then rename), so a
reader sees the old list or the new one, never half of one.

A missing file is an empty list. A file that cannot be read or does not match
the format (wrong region, a bad MMSI) is rejected and the listener keeps the
list it had, counting the failure in its heartbeat.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Iterable

from .sources.base import valid_mmsi

__all__ = ["SCHEMA_VERSION", "RELOAD_SECONDS", "WatchList", "WatchFileError", "WatchFile", "parse_watch",
           "read_watch", "write_watch", "atomic_write_json"]

SCHEMA_VERSION = 1
RELOAD_SECONDS = 600
_KEYS = {"schema_version", "region", "generated_at", "watched"}


class WatchFileError(ValueError):
    """``watch.json`` exists but is not a valid version-1 watch list for this region."""


@dataclass(frozen=True)
class WatchList:
    region: str
    watched: frozenset[int]
    generated_at: str | None = None

    def __contains__(self, mmsi: object) -> bool:
        return mmsi in self.watched

    def __len__(self) -> int:
        return len(self.watched)


def parse_watch(document, region: str) -> WatchList:
    """Validate a parsed ``watch.json`` document for ``region``."""
    if not isinstance(document, dict):
        raise WatchFileError("watch.json is not a JSON object")
    unknown = set(document) - _KEYS
    if unknown:
        raise WatchFileError(f"watch.json has unknown keys: {', '.join(sorted(unknown))}")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise WatchFileError(f"watch.json schema_version must be {SCHEMA_VERSION}")
    if document.get("region") != region:
        raise WatchFileError(f"watch.json is for region {document.get('region')!r}, not {region!r}")
    generated = document.get("generated_at")
    if generated is not None and not isinstance(generated, str):
        raise WatchFileError("watch.json generated_at must be an ISO 8601 string")
    watched = document.get("watched")
    if not isinstance(watched, list) or not all(valid_mmsi(m) for m in watched):
        raise WatchFileError("watch.json watched must be a list of MMSIs (integers 1..999999999)")
    if len(set(watched)) != len(watched):
        raise WatchFileError("watch.json watched lists an MMSI twice")
    return WatchList(region, frozenset(watched), generated)


def read_watch(path: Path, region: str) -> WatchList:
    """The watch list at ``path``; an empty list when the file does not exist."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return WatchList(region, frozenset())
    except OSError as error:
        raise WatchFileError(f"watch.json cannot be read: {error.strerror or error}") from None
    try:
        document = json.loads(text)
    except json.JSONDecodeError:
        raise WatchFileError("watch.json is not JSON") from None
    return parse_watch(document, region)


def write_watch(path: Path, region: str, watched: Iterable[int], generated_at: datetime | None = None) -> WatchList:
    """Atomically write a version-1 watch list (used by the processor, CF-46)."""
    mmsis = sorted(set(watched))
    moment = (generated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    document = {"schema_version": SCHEMA_VERSION, "region": region,
                "generated_at": moment.strftime("%Y-%m-%dT%H:%M:%SZ"), "watched": mmsis}
    result = parse_watch(document, region)
    atomic_write_json(Path(path), document)
    return result


def atomic_write_json(path: Path, document) -> None:
    """Write JSON to a temporary file in the same directory, fsync it, then rename it over ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream, separators=(",", ":"), sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


class WatchFile:
    """Re-reads ``watch.json`` when its modification time or size changes; keeps the last good list on error."""

    def __init__(self, path: Path, region: str):
        self.path = Path(path)
        self.region = region
        self.current = WatchList(region, frozenset())
        self.errors = 0
        self.last_error: str | None = None
        self._stamp: tuple | None = None

    def _signature(self):
        try:
            info = self.path.stat()
        except FileNotFoundError:
            return None
        return (info.st_mtime_ns, info.st_size, info.st_ino)

    def poll(self) -> bool:
        """Reload if the file changed; True when the watched set changed."""
        stamp = self._signature()
        if stamp == self._stamp and self._stamp is not None:
            return False
        try:
            fresh = read_watch(self.path, self.region)
        except WatchFileError as error:
            self.errors += 1
            self.last_error = str(error)
            self._stamp = stamp   # do not retry the same bad file every poll
            return False
        self._stamp = stamp
        self.last_error = None
        changed = fresh.watched != self.current.watched
        self.current = fresh
        return changed
