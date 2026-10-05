"""The always-on AIS listener (design.md section 10).

``python -m skippercast.fleet.ais listen --region CA`` runs it under the user
systemd unit (CF-42). Four asyncio tasks share one ``Listener``:

- **reader**: ``source.stream(bbox, mmsis)`` (one bbox subscription; with
  ``ais.mmsi_filter`` the watched MMSIs only), routes each record (below) and
  puts it on a bounded queue (``QUEUE_MAX``) without ever waiting on the
  database. Shedding: at ``SHED_DISCOVERY`` (80%) full, discovery positions are
  dropped; at ``SHED_STATICS`` (90%) statics too; watched positions only when
  the queue is full. Every drop is counted by table. A dropped connection, an
  error frame or ``IDLE_SECONDS`` (120 s) without a record reconnects after a
  delay drawn with full jitter from ``[0, min(BACKOFF_MAX, BACKOFF_INITIAL *
  2**attempt)]`` (1 s growing to 5 min); a connection that delivered a record
  resets ``attempt``.
- **writer**: commits the queue every ``BATCH_SECONDS`` (1 s) or
  ``BATCH_ROWS`` (1,000) rows through ``AisStore.write`` in a worker thread.
  ``AisStore.write`` opens each day file for one batch and closes it, so no day
  file is held open between batches. Hourly retention (``thresholds.retention``)
  runs in the same task between batches, so a write never overlaps retention.
  A record whose day its table's retention has already expired (or more than
  ``FUTURE_SLACK_MS`` in the future) is never queued, so the writer cannot
  recreate a day file retention removed.
- **watch**: re-reads ``ais/watch.json`` (``watch.py``) every
  ``RELOAD_SECONDS`` (10 min); with ``mmsi_filter`` a changed list makes the
  reader resubscribe.
- **heartbeat**: every ``HEARTBEAT_SECONDS`` (60 s) atomically writes
  ``ais/heartbeat.json`` (format below).

Routing (design.md section 5): a position from a watched MMSI goes to
``positions``. A position from any other vessel goes to ``discovery`` only when
it lies inside the region's AIS bbox and inside a harbor geofence of one of the
region's ports; everything else is never written. Statics go to ``statics``
for every vessel the subscription delivers, de-duplicated in memory: a static
is queued only when its content differs from the last one queued for that MMSI
and source, or the last one was queued on an earlier UTC day (so each day file
holds each vessel's statics).

``heartbeat.json`` (version 1)::

    {"schema_version": 1, "region": "XX", "source": "aisstream",
     "written_at": "...Z", "started_at": "...Z", "git_sha": "abc123" | null,
     "interval_s": 60.0, "connected": true, "last_message_at": "...Z" | null,
     "messages_per_min": 412.0, "watched_messages_per_min": 9.0, "vessels": 218,
     "reconnects": 2, "idle_reconnects": 0, "last_error": "..." | null,
     "drops": {"positions": 0, "discovery": 0, "statics": 0, "write_error": 0},
     "written": {"positions": 0, "discovery": 0, "statics": 0},
     "ignored": 0, "stale": 0, "malformed": 0,
     "queue_depth": 3, "queue_max": 50000,
     "watch_size": 41, "watch_generated_at": "...Z" | null, "watch_errors": 0,
     "retention_at": "...Z" | null}

Rates and ``vessels`` (distinct MMSIs heard) cover the interval since the
previous heartbeat; the other counters run since ``started_at``. ``git_sha`` is
``$SKIPPERCAST_GIT_SHA`` (the deploy sets it), else ``null``. The processor
pushes this file to the Worker (CF-45); CF-42's install checks it.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import deque
from dataclasses import astuple, dataclass, field
from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import random
import signal
import time
from typing import Awaitable, Callable, Iterable, Sequence

from ..config import point_in_polygon
from .sources.aisstream import FUTURE_SLACK_MS, MAX_MMSI_FILTER
from .sources.base import AisMessage, AisPosition, AisSource, AisStatic, Bbox, NotConfigured, bbox_contains
from .store import AisStore, RetentionLimits, day_of
from .watch import RELOAD_SECONDS, WatchFile, atomic_write_json

__all__ = ["QUEUE_MAX", "SHED_DISCOVERY", "SHED_STATICS", "BATCH_ROWS", "BATCH_SECONDS", "BACKOFF_INITIAL",
           "BACKOFF_MAX", "IDLE_SECONDS", "HEARTBEAT_SECONDS", "RETENTION_SECONDS", "HEARTBEAT_VERSION",
           "Geofence", "Router", "Settings", "Listener", "backoff_ceiling", "main"]

QUEUE_MAX = 50_000
SHED_DISCOVERY = 0.8
SHED_STATICS = 0.9
BATCH_ROWS = 1_000
BATCH_SECONDS = 1.0
BACKOFF_INITIAL = 1.0
BACKOFF_MAX = 300.0
IDLE_SECONDS = 120.0
HEARTBEAT_SECONDS = 60.0
RETENTION_SECONDS = 3_600.0
HEARTBEAT_VERSION = 1
TABLES = ("positions", "discovery", "statics")

log = logging.getLogger("skippercast.fleet.ais.listener")


def backoff_ceiling(attempt: int, initial: float = BACKOFF_INITIAL, cap: float = BACKOFF_MAX) -> float:
    """The upper bound of the jittered delay before reconnect ``attempt`` (0-based)."""
    return min(cap, initial * 2 ** min(attempt, 32))


def _iso(epoch_s: float | None) -> str | None:
    if epoch_s is None:
        return None
    return datetime.fromtimestamp(epoch_s, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Geofence:
    """A harbor polygon (closed ring of (lon, lat)) with its bounding box for a cheap first test."""
    ring: tuple[tuple[float, float], ...]
    south: float = field(init=False)
    west: float = field(init=False)
    north: float = field(init=False)
    east: float = field(init=False)

    def __post_init__(self):
        lons = [p[0] for p in self.ring]
        lats = [p[1] for p in self.ring]
        object.__setattr__(self, "south", min(lats))
        object.__setattr__(self, "north", max(lats))
        object.__setattr__(self, "west", min(lons))
        object.__setattr__(self, "east", max(lons))

    def contains(self, lat: float, lon: float) -> bool:
        if not (self.south <= lat <= self.north and self.west <= lon <= self.east):
            return False
        return point_in_polygon(lon, lat, self.ring)


class Router:
    """Decides which table, if any, a record goes to (module docstring)."""

    def __init__(self, bbox: Bbox, geofences: Sequence[Geofence], retention: RetentionLimits):
        self.bbox = bbox
        self.geofences = tuple(geofences)
        self.table_days = retention.table_days()
        self._statics: dict[tuple[int, str], tuple[int, tuple]] = {}

    def in_harbor(self, lat: float, lon: float) -> bool:
        return bbox_contains(self.bbox, lat, lon) and any(g.contains(lat, lon) for g in self.geofences)

    def expired(self, table: str, ts: int, now_ms: int) -> bool:
        """True when ``ts`` is too old for ``table``'s retention, or implausibly far ahead of ``now_ms``."""
        if ts > now_ms + FUTURE_SLACK_MS:
            return True
        return (day_of(now_ms) - day_of(ts)).days > self.table_days[table]

    def route(self, record: AisMessage, watched) -> str | None:
        if isinstance(record, AisPosition):
            if record.mmsi in watched:
                return "positions"
            return "discovery" if self.in_harbor(record.lat, record.lon) else None
        if isinstance(record, AisStatic):
            return "statics"
        return None

    def static_is_new(self, record: AisStatic) -> bool:
        key = (record.mmsi, record.source)
        content = astuple(record)[2:]          # everything but mmsi and ts
        seen = self._statics.get(key)
        return seen is None or seen[1] != content or seen[0] != day_of(record.ts).toordinal()

    def remember_static(self, record: AisStatic) -> None:
        self._statics[(record.mmsi, record.source)] = (day_of(record.ts).toordinal(), astuple(record)[2:])


@dataclass
class Settings:
    queue_max: int = QUEUE_MAX
    shed_discovery: float = SHED_DISCOVERY
    shed_statics: float = SHED_STATICS
    batch_rows: int = BATCH_ROWS
    batch_seconds: float = BATCH_SECONDS
    backoff_initial: float = BACKOFF_INITIAL
    backoff_max: float = BACKOFF_MAX
    idle_seconds: float = IDLE_SECONDS
    reload_seconds: float = RELOAD_SECONDS
    heartbeat_seconds: float = HEARTBEAT_SECONDS
    retention_seconds: float = RETENTION_SECONDS

    def __post_init__(self):
        if not 0 < self.shed_discovery <= self.shed_statics <= 1:
            raise ValueError("shedding thresholds must satisfy 0 < discovery <= statics <= 1")
        if self.queue_max < 1 or self.batch_rows < 1:
            raise ValueError("queue_max and batch_rows must be positive")


@dataclass
class Counters:
    reconnects: int = 0
    idle_reconnects: int = 0
    ignored: int = 0
    stale: int = 0
    malformed: int = 0
    drops: dict = field(default_factory=lambda: {"positions": 0, "discovery": 0, "statics": 0, "write_error": 0})
    written: dict = field(default_factory=lambda: {t: 0 for t in TABLES})
    # since the last heartbeat
    interval_messages: int = 0
    interval_watched: int = 0
    interval_vessels: set = field(default_factory=set)


class _Resubscribe(Exception):
    pass


class Listener:
    """One region's listener. Everything time- or chance-dependent is injectable for tests."""

    def __init__(self, *, region: str, source: AisSource, store: AisStore, bbox: Bbox,
                 geofences: Iterable[Geofence], retention: RetentionLimits, watch: WatchFile,
                 heartbeat_path: Path, mmsi_filter: bool = False, settings: Settings | None = None,
                 clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
                 jitter: Callable[[float, float], float] = random.uniform,
                 git_sha: str | None = None):
        self.region = region
        self.source = source
        self.store = store
        self.bbox = bbox
        self.retention = retention
        self.router = Router(bbox, list(geofences), retention)
        self.watch = watch
        self.heartbeat_path = Path(heartbeat_path)
        self.mmsi_filter = mmsi_filter
        self.settings = settings or Settings()
        self.clock = clock
        self.sleep = sleep
        self.jitter = jitter
        self.git_sha = git_sha
        self.queue: deque[tuple[str, AisMessage]] = deque()
        self.counters = Counters()
        self.started_at = clock()
        self.connected = False
        self.last_message_at: float | None = None
        self.last_error: str | None = None
        self.last_retention_at: float | None = None
        self.delays: list[float] = []          # reconnect delays drawn, newest last (kept short)
        self._heartbeat_at = self.started_at
        self._batch_ready = asyncio.Event()
        self._resubscribe = asyncio.Event()

    # ----- reader -----

    def subscription_mmsis(self) -> set[int] | None:
        """``None`` (every vessel in the bbox) unless ``mmsi_filter`` is on and the list fits aisstream's filter."""
        if not self.mmsi_filter:
            return None
        watched = set(self.watch.current.watched)
        if len(watched) > MAX_MMSI_FILTER:
            log.warning("watch list of %d is over the %d-MMSI filter; subscribing to the whole bbox",
                        len(watched), MAX_MMSI_FILTER)
            return None
        return watched

    def accept(self, record: AisMessage) -> str | None:
        """Route and queue one record; returns the table it was queued for, or ``None``."""
        now = self.clock()
        self.last_message_at = now
        self.counters.interval_messages += 1
        self.counters.interval_vessels.add(record.mmsi)
        table = self.router.route(record, self.watch.current.watched)
        if table is None:
            self.counters.ignored += 1
            return None
        if table == "positions":
            self.counters.interval_watched += 1
        if self.router.expired(table, record.ts, int(now * 1000)):
            self.counters.stale += 1
            return None
        if table == "statics" and not self.router.static_is_new(record):
            return None
        depth, cap = len(self.queue), self.settings.queue_max
        if depth >= cap or (table == "discovery" and depth >= cap * self.settings.shed_discovery) or (
                table == "statics" and depth >= cap * self.settings.shed_statics):
            self.counters.drops[table] += 1
            return None
        if table == "statics":
            self.router.remember_static(record)
        self.queue.append((table, record))
        if len(self.queue) >= self.settings.batch_rows:
            self._batch_ready.set()
        return table

    async def _next(self, stream):
        """The next record, or ``asyncio.TimeoutError`` after ``idle_seconds``; ``_Resubscribe`` on a watch change."""
        step = asyncio.ensure_future(anext(stream))
        change = asyncio.ensure_future(self._resubscribe.wait())
        try:
            done, _ = await asyncio.wait({step, change}, timeout=self.settings.idle_seconds,
                                         return_when=asyncio.FIRST_COMPLETED)
        except BaseException:   # cancelled: settle the read before the stream is closed
            await self._settle(step, change)
            raise
        if step in done:
            change.cancel()
            return step.result()
        await self._settle(step, change)
        if change in done:
            raise _Resubscribe()
        raise asyncio.TimeoutError()

    @staticmethod
    async def _settle(*futures) -> None:
        for future in futures:
            future.cancel()
        await asyncio.gather(*futures, return_exceptions=True)

    async def read_forever(self) -> None:
        """Connect, read and reconnect until cancelled. ``NotConfigured`` (no API key) is fatal."""
        attempt = 0
        while True:
            mmsis = self.subscription_mmsis()
            if mmsis is not None and not mmsis:
                # watched-only mode with nothing to watch: wait for the list to fill
                self._resubscribe.clear()
                await self.sleep(self.settings.reload_seconds)
                continue
            self._resubscribe.clear()
            stream = self.source.stream(self.bbox, mmsis)
            reason = None
            try:
                while True:
                    record = await self._next(stream)
                    if not self.connected:
                        self.connected = True
                        log.info("receiving AIS", extra={"region": self.region, "source_id": self.source.id})
                    attempt = 0
                    self.accept(record)
            except _Resubscribe:
                reason = None
            except NotConfigured:
                raise
            except StopAsyncIteration:
                reason = "stream ended"
            except asyncio.TimeoutError:
                self.counters.idle_reconnects += 1
                reason = f"no message for {self.settings.idle_seconds:g} s"
            except asyncio.CancelledError:
                raise
            except Exception as error:   # connection errors, error frames, protocol errors
                reason = f"{type(error).__name__}: {str(error)[:200]}"
            finally:
                self.connected = False
                try:
                    await stream.aclose()
                except Exception:
                    pass
            if reason is None:
                log.info("watch list changed; resubscribing", extra={"region": self.region})
                continue
            self.counters.reconnects += 1
            self.last_error = reason
            delay = self.jitter(0.0, backoff_ceiling(attempt, self.settings.backoff_initial, self.settings.backoff_max))
            attempt += 1
            self.delays = (self.delays + [delay])[-20:]
            log.warning("AIS connection lost (%s); reconnecting in %.1f s", reason, delay,
                        extra={"region": self.region, "source_id": self.source.id})
            await self.sleep(delay)

    # ----- writer -----

    def take_batch(self) -> dict[str, list[AisMessage]]:
        batch = {t: [] for t in TABLES}
        for _ in range(min(len(self.queue), self.settings.batch_rows)):
            table, record = self.queue.popleft()
            batch[table].append(record)
        if len(self.queue) < self.settings.batch_rows:
            self._batch_ready.clear()
        return batch

    async def flush(self) -> int:
        """Write everything queued now, one batch at a time; returns rows handed to the store."""
        handed = 0
        while self.queue:
            batch = self.take_batch()
            rows = sum(len(v) for v in batch.values())
            handed += rows
            try:
                counts = await asyncio.to_thread(self.store.write, batch["positions"], batch["discovery"],
                                                 batch["statics"])
            except Exception as error:   # disk full, a locked or corrupt day file
                self.counters.drops["write_error"] += rows
                self.last_error = f"write failed: {type(error).__name__}: {str(error)[:200]}"
                log.error("AIS batch of %d rows not written: %s", rows, error, extra={"region": self.region})
                continue
            for table in TABLES:
                self.counters.written[table] += getattr(counts, table)
        return handed

    async def retain(self) -> None:
        now = self.clock()
        today = datetime.fromtimestamp(now, timezone.utc).date()
        try:
            result = await asyncio.to_thread(self.store.apply_retention, self.retention, today)
        except Exception as error:
            self.last_error = f"retention failed: {type(error).__name__}: {str(error)[:200]}"
            log.error("AIS retention failed: %s", error, extra={"region": self.region})
        else:
            if result.deleted_files or result.emptied:
                log.info("AIS retention deleted %d day files, emptied %d", len(result.deleted_files),
                         len(result.emptied), extra={"region": self.region})
        self.last_retention_at = now

    async def write_forever(self) -> None:
        while True:
            if self.last_retention_at is None or self.clock() - self.last_retention_at >= self.settings.retention_seconds:
                await self.retain()
            try:
                await asyncio.wait_for(self._batch_ready.wait(), self.settings.batch_seconds)
            except asyncio.TimeoutError:
                pass
            await self.flush()

    # ----- watch and heartbeat -----

    async def watch_forever(self) -> None:
        while True:
            await self.sleep(self.settings.reload_seconds)
            self.reload_watch()

    def reload_watch(self) -> bool:
        changed = self.watch.poll()
        if changed:
            log.info("watch list now %d MMSIs", len(self.watch.current), extra={"region": self.region})
            if self.mmsi_filter:
                self._resubscribe.set()
        if self.watch.last_error:
            log.warning("watch.json rejected, keeping %d MMSIs: %s", len(self.watch.current), self.watch.last_error,
                        extra={"region": self.region})
        return changed

    def heartbeat(self) -> dict:
        now = self.clock()
        minutes = max(now - self._heartbeat_at, 1e-9) / 60
        c = self.counters
        document = {
            "schema_version": HEARTBEAT_VERSION, "region": self.region, "source": self.source.id,
            "written_at": _iso(now), "started_at": _iso(self.started_at), "git_sha": self.git_sha,
            "interval_s": round(now - self._heartbeat_at, 3), "connected": self.connected,
            "last_message_at": _iso(self.last_message_at),
            "messages_per_min": round(c.interval_messages / minutes, 2),
            "watched_messages_per_min": round(c.interval_watched / minutes, 2),
            "vessels": len(c.interval_vessels), "reconnects": c.reconnects, "idle_reconnects": c.idle_reconnects,
            "last_error": self.last_error, "drops": dict(c.drops), "written": dict(c.written),
            "ignored": c.ignored, "stale": c.stale, "malformed": c.malformed,
            "queue_depth": len(self.queue), "queue_max": self.settings.queue_max,
            "watch_size": len(self.watch.current), "watch_generated_at": self.watch.current.generated_at,
            "watch_errors": self.watch.errors, "retention_at": _iso(self.last_retention_at),
        }
        return document

    def write_heartbeat(self) -> dict:
        document = self.heartbeat()
        atomic_write_json(self.heartbeat_path, document)
        self._heartbeat_at = self.clock()
        self.counters.interval_messages = 0
        self.counters.interval_watched = 0
        self.counters.interval_vessels = set()
        return document

    async def heartbeat_forever(self) -> None:
        while True:
            try:
                self.write_heartbeat()
            except OSError as error:
                log.error("heartbeat not written: %s", error, extra={"region": self.region})
            await self.sleep(self.settings.heartbeat_seconds)

    # ----- the service -----

    def on_malformed(self, error: Exception) -> None:
        self.counters.malformed += 1

    async def run(self, stop: asyncio.Event | None = None) -> None:
        """Run until ``stop`` is set (or a task fails), then flush the queue and write a last heartbeat."""
        stop = stop or asyncio.Event()
        if hasattr(self.source, "on_malformed") and getattr(self.source, "on_malformed") is None:
            self.source.on_malformed = self.on_malformed
        self.reload_watch()
        tasks = [asyncio.create_task(coro, name=name) for name, coro in (
            ("ais-reader", self.read_forever()), ("ais-writer", self.write_forever()),
            ("ais-watch", self.watch_forever()), ("ais-heartbeat", self.heartbeat_forever()))]
        stopper = asyncio.create_task(stop.wait(), name="ais-stop")
        failure = None
        try:
            done, _ = await asyncio.wait([*tasks, stopper], return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not stopper and not task.cancelled() and task.exception() is not None:
                    failure = task.exception()
        finally:
            for task in (*tasks, stopper):
                task.cancel()
            await asyncio.gather(*tasks, stopper, return_exceptions=True)
            await self.flush()
            try:
                self.write_heartbeat()
            except OSError:
                pass
        if failure is not None:
            raise failure


def geofences_of(region) -> list[Geofence]:
    return [Geofence(tuple(tuple(p) for p in port.geofence)) for port in region.ports]


def build_listener(region_id: str, var: Path | None = None, environ=None, **overrides) -> Listener:
    """A listener for ``regions/<region_id>/fleet.json`` with the aisstream key from ``AISSTREAM_API_KEY``."""
    from ..config import load_region
    from .sources import get_source
    from .sources.base import bbox_of
    from .store import retention_limits

    environ = os.environ if environ is None else environ
    region = load_region(region_id)
    source_options = {"message_types": region.ais.message_types}
    if region.ais.source == "aisstream":
        source_options["api_key"] = environ.get("AISSTREAM_API_KEY", "").strip() or None
    source = get_source(region.ais.source, **source_options)
    store = AisStore.for_region(region.id, var)
    return Listener(region=region.id, source=source, store=store, bbox=bbox_of(region.ais),
                    geofences=geofences_of(region), retention=retention_limits(region),
                    watch=WatchFile(store.root / "watch.json", region.id),
                    heartbeat_path=store.root / "heartbeat.json", mmsi_filter=region.ais.mmsi_filter,
                    git_sha=(environ.get("SKIPPERCAST_GIT_SHA") or "").strip() or None, **overrides)


async def _serve(listener: Listener) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signum, stop.set)
        except (NotImplementedError, RuntimeError):   # not on this platform
            pass
    await listener.run(stop)


def main(argv: Sequence[str] | None = None) -> int:
    from ... import log as joblog

    parser = argparse.ArgumentParser(prog="python -m skippercast.fleet.ais listen",
                                     description="Run the always-on AIS listener for one fleet region.")
    parser.add_argument("--region", required=True, help="fleet region id, e.g. CA")
    args = parser.parse_args(argv)
    joblog.configure(job="fleet-ais-listener", region=args.region)
    try:
        listener = build_listener(args.region)
        if hasattr(listener.source, "subscription"):
            listener.source.subscription(listener.bbox)   # fail now, not after start, without a key
    except NotConfigured as error:
        log.error("%s", error)
        return 2
    log.info("AIS listener starting", extra={"region": listener.region, "source_id": listener.source.id})
    try:
        asyncio.run(_serve(listener))
    except NotConfigured as error:
        log.error("%s", error)
        return 2
    return 0
