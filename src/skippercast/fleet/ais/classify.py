"""Classify a trip's positions into segments (design.md section 11, D10).

Pure and deterministic: the same trip, ports and thresholds always give the
same segments. Standard library only.

For each position, over a centred ``window_min`` window that never crosses a
gap (a silence over ``gap_unknown_min``):

- **mean SOG** of the positions' speeds: the reported SOG, else the speed
  derived from the previous usable position;
- **straightness** = net displacement / path length;
- **heading variance** = 1 - mean resultant length of COG (reported, else the
  bearing from the previous usable position).

Positions whose time is suspect (``segment.is_suspect``: received more than
``LATE_MS`` after the fix) keep their reported SOG but are left out of derived
speeds, headings and straightness, because those depend on when the fix was
taken.

Labels, in precedence order: ``in-port`` (inside a geofence); ``fishing-drift``
(mean SOG at or below ``drift.max_sog_kn``); ``fishing-troll`` (mean SOG within
``troll.min_sog_kn``-``troll.max_sog_kn`` and straightness at or below
``troll.max_straightness`` or heading variance at or above
``troll.min_heading_variance``); ``transit`` otherwise. Consecutive equal labels
form runs. Runs shorter than ``min_segment_minutes`` merge into the longer
neighbour (the earlier one on a tie); then a fishing run shorter than its
``min_minutes`` becomes transit, and short runs merge again. Silences over
``gap_unknown_min`` become ``gap`` segments, which never merge, including a
silence between the last fix at sea and the return fix. So a run between two
gaps (or between a gap and the trip's start or end) has no neighbour to merge
into and may be shorter than ``min_segment_minutes``.

Segments tile the trip: each ends where the next begins, the last at the trip's
``returned_at``. Every segment and the result carry ``basis =
inferred-from-movement`` (D10: never "confirmed fishing") and the
``classifier_version``, a hash of the activity thresholds and
``ALGORITHM_VERSION``.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Sequence

from .segment import (BASIS, MINUTE_MS, ActivityThresholds, Geofence, Trip, distance_nm, is_suspect, port_at)
from .sources.base import AisPosition

__all__ = ["ALGORITHM_VERSION", "BASIS", "KINDS", "FISHING_KINDS", "Classification", "Segment", "Stats",
           "classifier_version", "classify_trip", "label_positions", "window_stats"]

# Bump when the classification code changes behaviour, so classifier_version changes with it.
ALGORITHM_VERSION = 1
KINDS = ("in-port", "transit", "fishing-drift", "fishing-troll", "gap")
FISHING_KINDS = ("fishing-drift", "fishing-troll")
_SUSTAINED = {"fishing-drift": "drift_min_minutes", "fishing-troll": "troll_min_minutes"}


def classifier_version(thresholds: ActivityThresholds) -> str:
    """``c<ALGORITHM_VERSION>-<16 hex>``: changes whenever any activity threshold or the algorithm version does."""
    body = json.dumps({"algorithm": ALGORITHM_VERSION, "activity": thresholds.raw}, sort_keys=True,
                      separators=(",", ":"))
    return f"c{ALGORITHM_VERSION}-{hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]}"


@dataclass(frozen=True)
class Stats:
    mean_sog: float | None
    straightness: float | None
    heading_var: float | None


@dataclass(frozen=True)
class Segment:
    """A classified stretch of a trip. Times are epoch milliseconds; ``positions`` are the fixes inside it."""
    seq: int
    kind: str
    started_at: int
    ended_at: int
    positions: tuple[AisPosition, ...]
    mean_sog: float | None
    straightness: float | None
    heading_var: float | None
    basis: str = BASIS

    @property
    def points_n(self) -> int:
        return len(self.positions)

    @property
    def minutes(self) -> float:
        return (self.ended_at - self.started_at) / MINUTE_MS


@dataclass(frozen=True)
class Classification:
    trip: Trip
    segments: tuple[Segment, ...]
    classifier_version: str
    basis: str = BASIS

    @property
    def fishing_min(self) -> float:
        return sum(s.minutes for s in self.segments if s.kind in FISHING_KINDS)

    @property
    def gap_min(self) -> float:
        return sum(s.minutes for s in self.segments if s.kind == "gap")


# ---------------------------------------------------------------- per-position measures

def _bearing(a: AisPosition, b: AisPosition) -> float:
    p1, p2 = math.radians(a.lat), math.radians(b.lat)
    dl = math.radians(b.lon - a.lon)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return math.degrees(math.atan2(x, y)) % 360.0


def _measures(rows: Sequence[AisPosition], gap_ms: float):
    """Per position: (speed kn or None, course deg or None). Derived values skip suspect fixes and gaps."""
    speeds, courses = [], []
    prev: AisPosition | None = None
    for p in rows:
        if prev is not None and p.ts - prev.ts > gap_ms:
            prev = None
        suspect = is_suspect(p)
        derived_ok = prev is not None and not suspect and p.ts > prev.ts
        speed = p.sog
        if speed is None and derived_ok:
            speed = distance_nm(prev.lat, prev.lon, p.lat, p.lon) / ((p.ts - prev.ts) / 3_600_000)
        course = None
        if not suspect:
            course = p.cog
            if course is None and derived_ok and (prev.lat, prev.lon) != (p.lat, p.lon):
                course = _bearing(prev, p)
        speeds.append(speed)
        courses.append(course)
        if not suspect:
            prev = p
    return speeds, courses


def _stats(rows: Sequence[AisPosition], speeds, courses) -> Stats:
    known = [s for s in speeds if s is not None]
    mean_sog = sum(known) / len(known) if known else None
    angles = [math.radians(c) for c in courses if c is not None]
    heading_var = None
    if angles:
        sx = sum(math.sin(a) for a in angles) / len(angles)
        cx = sum(math.cos(a) for a in angles) / len(angles)
        heading_var = max(0.0, 1.0 - math.hypot(sx, cx))
    usable = [p for p in rows if not is_suspect(p)]
    straightness = None
    if len(usable) >= 2:
        path = sum(distance_nm(a.lat, a.lon, b.lat, b.lon) for a, b in zip(usable, usable[1:]))
        if path > 0:
            net = distance_nm(usable[0].lat, usable[0].lon, usable[-1].lat, usable[-1].lon)
            straightness = min(1.0, net / path)
    return Stats(_round(mean_sog), _round(straightness), _round(heading_var))


def _round(value):
    return None if value is None else round(value, 6)


def _blocks(rows: Sequence[AisPosition], gap_ms: float) -> list[tuple[int, int]]:
    """Index ranges [start, end) of runs of positions with no silence over the gap threshold."""
    blocks, start = [], 0
    for k in range(1, len(rows)):
        if rows[k].ts - rows[k - 1].ts > gap_ms:
            blocks.append((start, k))
            start = k
    if rows:
        blocks.append((start, len(rows)))
    return blocks


def window_stats(rows: Sequence[AisPosition], thresholds: ActivityThresholds) -> list[Stats]:
    """Centred-window mean SOG, straightness and heading variance for every position."""
    gap_ms = thresholds.gap_unknown_min * MINUTE_MS
    half = thresholds.window_min * MINUTE_MS / 2
    speeds, courses = _measures(rows, gap_ms)
    out: list[Stats] = []
    for start, end in _blocks(rows, gap_ms):
        lo = hi = start
        for k in range(start, end):
            t = rows[k].ts
            while rows[lo].ts < t - half:
                lo += 1
            while hi < end and rows[hi].ts <= t + half:
                hi += 1
            out.append(_stats(rows[lo:hi], speeds[lo:hi], courses[lo:hi]))
    return out


def label_positions(rows: Sequence[AisPosition], ports: Sequence[Geofence],
                    thresholds: ActivityThresholds) -> list[str]:
    """The raw per-position label (before sustain and merge rules)."""
    th = thresholds
    labels = []
    for p, stats in zip(rows, window_stats(rows, th)):
        sog = stats.mean_sog
        if port_at(ports, p.lat, p.lon) is not None:
            labels.append("in-port")
        elif sog is not None and sog <= th.drift_max_sog_kn:
            labels.append("fishing-drift")
        elif (sog is not None and th.troll_min_sog_kn <= sog <= th.troll_max_sog_kn
              and ((stats.straightness is not None and stats.straightness <= th.troll_max_straightness)
                   or (stats.heading_var is not None and stats.heading_var >= th.troll_min_heading_variance))):
            labels.append("fishing-troll")
        else:
            labels.append("transit")
    return labels


# ---------------------------------------------------------------- runs

@dataclass
class _Run:
    kind: str
    first: int   # index of the first position
    last: int    # index of the last position
    start: int   # ms
    end: int     # ms (start of the next run, or trip end)

    @property
    def minutes(self) -> float:
        return (self.end - self.start) / MINUTE_MS


def _coalesce(runs: list[_Run]) -> list[_Run]:
    out: list[_Run] = []
    for run in runs:
        if out and out[-1].kind == run.kind and run.kind != "gap":
            out[-1].last, out[-1].end = run.last, run.end
        else:
            out.append(run)
    return out


def _merge_short(runs: list[_Run], minimum: float) -> list[_Run]:
    """Merge runs shorter than ``minimum`` minutes into their longer non-gap neighbour, shortest first."""
    while True:
        candidates = [k for k, r in enumerate(runs) if r.kind != "gap" and r.minutes < minimum]
        best = None
        for k in sorted(candidates, key=lambda k: (runs[k].minutes, k)):
            left = runs[k - 1] if k > 0 and runs[k - 1].kind != "gap" else None
            right = runs[k + 1] if k + 1 < len(runs) and runs[k + 1].kind != "gap" else None
            if left or right:
                best = (k, left, right)
                break
        if best is None:
            return runs
        k, left, right = best
        run = runs[k]
        target = left if right is None or (left is not None and left.minutes >= right.minutes) else right
        if target is left:
            left.last, left.end = run.last, run.end
        else:
            right.first, right.start = run.first, run.start
        del runs[k]
        runs[:] = _coalesce(runs)


def classify_trip(trip: Trip, ports: Sequence[Geofence], thresholds: ActivityThresholds) -> Classification:
    """Cut a trip into labelled segments (module docstring)."""
    th = thresholds
    rows = trip.positions
    version = classifier_version(th)
    if not rows:
        return Classification(trip, (), version)
    gap_ms = th.gap_unknown_min * MINUTE_MS
    labels = label_positions(rows, ports, th)

    runs: list[_Run] = []
    for k, (p, label) in enumerate(zip(rows, labels)):
        if k and p.ts - rows[k - 1].ts > gap_ms:
            runs.append(_Run("gap", k - 1, k - 1, rows[k - 1].ts, p.ts))
        if runs and runs[-1].kind == label:
            runs[-1].last = k
        else:
            runs.append(_Run(label, k, k, p.ts, p.ts))
    # A silence between the last fix at sea and the return fix is a gap too, not part of the last run.
    if trip.returned_at - rows[-1].ts > gap_ms:
        runs.append(_Run("gap", len(rows) - 1, len(rows) - 1, rows[-1].ts, trip.returned_at))
    # Tile: every run ends where the next begins, the last at the trip's end.
    for here, after in zip(runs, runs[1:]):
        here.end = after.start
    runs[-1].end = max(runs[-1].start, trip.returned_at)

    # Short blips first (so one noisy fix does not break a drift), then the sustain rule, then again.
    runs = _merge_short(_coalesce(runs), th.min_segment_minutes)
    for run in runs:
        attr = _SUSTAINED.get(run.kind)
        if attr and run.minutes < getattr(th, attr):
            run.kind = "transit"
    runs = _merge_short(_coalesce(runs), th.min_segment_minutes)

    speeds, courses = _measures(rows, gap_ms)
    segments = []
    for seq, run in enumerate(runs):
        if run.kind == "gap":
            segments.append(Segment(seq, "gap", run.start, run.end, (), None, None, None))
            continue
        part = slice(run.first, run.last + 1)
        stats = _stats(rows[part], speeds[part], courses[part])
        segments.append(Segment(seq, run.kind, run.start, run.end, tuple(rows[part]), stats.mean_sog,
                                stats.straightness, stats.heading_var))
    return Classification(trip, tuple(segments), version)
