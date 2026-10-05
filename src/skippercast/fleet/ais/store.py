"""The raw AIS store on Hermes: one SQLite file per UTC day (design.md sections 4, 5 and 10).

Layout under ``$SKIPPERCAST_FLEET_VAR`` (default ``<repo>/var/fleet``, gitignored)::

    <FLEET_VAR>/<region>/ais/raw/YYYY-MM-DD.sqlite   positions, discovery, statics (WAL)
    <FLEET_VAR>/<region>/ais/validation/             labelled trips' raw positions (CF-48)

Each day file holds three tables:

- ``positions`` for watched MMSIs and ``discovery`` for unwatched vessels the
  listener keeps (inside a geofence, or a static name matching an alias), both
  keyed ``(mmsi, ts, source)`` ``WITHOUT ROWID``. A repeated key is stored
  once: the row with the earliest ``received_at`` wins, whichever arrives first,
  so the same report heard twice, or a batch written twice, gives one row. A
  position with ``received_at - ts`` over ``aisstream.LATE_MS`` may sit in the
  wrong minute; the processor (CF-43) treats its time as suspect.
- ``statics`` for every vessel in the box, keyed the same way; a repeated key is
  ignored.

A record goes to the file of the UTC day of its ``ts``. Which vessels are
written is the listener's decision; the store only stores.

Retention (``thresholds.retention``: ``raw_days``, ``discovery_days``,
``static_days``) works by age in whole days: a day's ``positions`` are kept until
more than ``raw_days`` days have passed since it (day ``D`` goes on day
``D + raw_days + 1``), and likewise ``discovery`` and ``statics``. A file is
deleted once all three are past their limit; before that, a table past its
limit is emptied in place. Retention only ever touches ``raw/YYYY-MM-DD.sqlite``
files (and their ``-wal``/``-shm`` siblings) that really live in ``raw/``:
``validation/`` and anything else is never read, moved or deleted. A day file
with more than one hard link (for example one also linked into ``validation/``)
is never emptied in place, only unlinked from ``raw/`` when it expires. The
listener and processor must not hold expired day files open across retention.

Standard library only (``sqlite3``).
"""
from __future__ import annotations

from collections import defaultdict
from contextlib import closing
from dataclasses import astuple, dataclass, field
from datetime import date, datetime, timedelta, timezone
import os
from pathlib import Path
import re
import sqlite3
from typing import Callable, Iterable, Iterator, Mapping

from ...paths import repo_root
from .sources.base import AisPosition, AisStatic, valid_mmsi

__all__ = ["SCHEMA_VERSION", "POSITION_TABLES", "TABLES", "AisStore", "RetentionLimits", "RetentionResult",
           "WriteCounts", "fleet_var", "ais_root", "day_of", "retention_limits"]

SCHEMA_VERSION = 1
POSITION_TABLES = ("positions", "discovery")
TABLES = POSITION_TABLES + ("statics",)
DAY_FILE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})\.sqlite$")
_SIDECARS = ("-wal", "-shm", "-journal")
_POSITION_COLUMNS = ("mmsi", "ts", "lat", "lon", "sog", "cog", "heading", "nav_status", "msg_type", "source",
                     "received_at")
_STATIC_COLUMNS = ("mmsi", "ts", "name", "call_sign", "imo", "ship_type", "dim_bow", "dim_stern", "dim_port",
                   "dim_starboard", "ais_class", "source")
_POSITION_DDL = """CREATE TABLE IF NOT EXISTS {table} (
  mmsi INTEGER NOT NULL, ts INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL,
  sog REAL, cog REAL, heading INTEGER, nav_status INTEGER, msg_type TEXT NOT NULL, source TEXT NOT NULL,
  received_at INTEGER NOT NULL,
  PRIMARY KEY (mmsi, ts, source)) WITHOUT ROWID"""
_STATIC_DDL = """CREATE TABLE IF NOT EXISTS statics (
  mmsi INTEGER NOT NULL, ts INTEGER NOT NULL, name TEXT, call_sign TEXT, imo INTEGER, ship_type INTEGER,
  dim_bow INTEGER, dim_stern INTEGER, dim_port INTEGER, dim_starboard INTEGER, ais_class TEXT NOT NULL,
  source TEXT NOT NULL,
  PRIMARY KEY (mmsi, ts, source)) WITHOUT ROWID"""


def _insert_sql(table: str) -> str:
    """Statics ignore a repeated key; positions keep the earliest receipt, whatever order rows arrive in."""
    columns = _STATIC_COLUMNS if table == "statics" else _POSITION_COLUMNS
    sql = f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({', '.join('?' * len(columns))}) "
    if table == "statics":
        return sql + "ON CONFLICT (mmsi, ts, source) DO NOTHING"
    updates = ", ".join(f"{c} = excluded.{c}" for c in _POSITION_COLUMNS[2:])
    return sql + (f"ON CONFLICT (mmsi, ts, source) DO UPDATE SET {updates} "
                  f"WHERE excluded.received_at < {table}.received_at")


def fleet_var(environ: Mapping[str, str] | None = None) -> Path:
    """``$SKIPPERCAST_FLEET_VAR``, else ``<repo>/var/fleet`` (design.md section 4)."""
    configured = (os.environ if environ is None else environ).get("SKIPPERCAST_FLEET_VAR", "").strip()
    return Path(configured).expanduser() if configured else repo_root() / "var" / "fleet"


def ais_root(region: str, var: Path | None = None) -> Path:
    """``<FLEET_VAR>/<region>/ais``."""
    if not re.fullmatch(r"[A-Z]{2}", region or ""):
        raise ValueError("fleet region ids are two upper-case letters")
    return (var if var is not None else fleet_var()) / region / "ais"


def day_of(ts_ms: int) -> date:
    """The UTC day of an epoch-millisecond time."""
    return datetime.fromtimestamp(ts_ms / 1000, timezone.utc).date()


def _day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp()) * 1000


@dataclass(frozen=True)
class RetentionLimits:
    raw_days: int
    discovery_days: int
    static_days: int

    def __post_init__(self):
        for name, value in (("raw_days", self.raw_days), ("discovery_days", self.discovery_days),
                            ("static_days", self.static_days)):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"retention {name} must be a whole number of days >= 1")

    def table_days(self) -> dict[str, int]:
        return {"positions": self.raw_days, "discovery": self.discovery_days, "statics": self.static_days}


def retention_limits(region) -> RetentionLimits:
    """The ``thresholds.retention`` of a loaded ``FleetRegion``."""
    node = region.thresholds["retention"]
    return RetentionLimits(int(node["raw_days"]), int(node["discovery_days"]), int(node["static_days"]))


@dataclass
class WriteCounts:
    """Rows inserted per table, plus position rows replaced by an earlier receipt; plain duplicates are not counted."""
    positions: int = 0
    discovery: int = 0
    statics: int = 0

    @property
    def total(self) -> int:
        return self.positions + self.discovery + self.statics


@dataclass
class RetentionResult:
    deleted_files: list[str] = field(default_factory=list)              # day file names, e.g. 2026-08-01.sqlite
    emptied: dict[str, list[str]] = field(default_factory=dict)         # day file name -> tables emptied
    skipped: list[str] = field(default_factory=list)                    # hard-linked files left as they are


class AisStore:
    """Day-file store rooted at ``<FLEET_VAR>/<region>/ais``."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.raw_dir = self.root / "raw"
        self.validation_dir = self.root / "validation"

    @classmethod
    def for_region(cls, region: str, var: Path | None = None) -> "AisStore":
        return cls(ais_root(region, var))

    def day_path(self, day: date) -> Path:
        return self.raw_dir / f"{day.isoformat()}.sqlite"

    def connect(self, day: date) -> sqlite3.Connection:
        """Open (creating if needed) the day file with its schema, in WAL mode."""
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.day_path(day))
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"{self.day_path(day).name}: schema version {version} is newer than this code")
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            if version < SCHEMA_VERSION:
                with conn:
                    for table in POSITION_TABLES:
                        conn.execute(_POSITION_DDL.format(table=table))
                    conn.execute(_STATIC_DDL)
                    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        except BaseException:
            conn.close()
            raise
        return conn

    def days(self) -> list[date]:
        """UTC days with a day file, oldest first."""
        found = []
        if self.raw_dir.is_dir():
            for entry in self.raw_dir.iterdir():
                day = _parse_day(entry.name)
                if day is not None and entry.is_file():
                    found.append(day)
        return sorted(found)

    def write(self, positions: Iterable[AisPosition] = (), discovery: Iterable[AisPosition] = (),
              statics: Iterable[AisStatic] = ()) -> WriteCounts:
        """Insert records into their days' files, one transaction per day; duplicate keys are ignored."""
        by_day: dict[date, dict[str, list[tuple]]] = defaultdict(lambda: defaultdict(list))
        for table, records, kind in (("positions", positions, AisPosition), ("discovery", discovery, AisPosition),
                                     ("statics", statics, AisStatic)):
            for record in records:
                if not isinstance(record, kind):
                    raise TypeError(f"{table} takes {kind.__name__} records")
                if not valid_mmsi(record.mmsi):
                    raise ValueError(f"{table}: invalid MMSI")
                by_day[day_of(record.ts)][table].append(astuple(record))
        counts = WriteCounts()
        for day in sorted(by_day):
            with closing(self.connect(day)) as conn, conn:
                for table, rows in by_day[day].items():
                    before = conn.total_changes
                    conn.executemany(_insert_sql(table), rows)
                    setattr(counts, table, getattr(counts, table) + conn.total_changes - before)
        return counts

    def read_positions(self, start_ms: int, end_ms: int, mmsis: Iterable[int] | None = None,
                       table: str = "positions") -> Iterator[AisPosition]:
        """Positions with ``start_ms <= ts < end_ms``, by MMSI then time, from ``positions`` or ``discovery``."""
        if table not in POSITION_TABLES:
            raise ValueError(f"table must be one of {POSITION_TABLES}")
        for row in self._read(table, _POSITION_COLUMNS, start_ms, end_ms, mmsis):
            yield AisPosition(*row)

    def read_statics(self, start_ms: int, end_ms: int, mmsis: Iterable[int] | None = None) -> Iterator[AisStatic]:
        for row in self._read("statics", _STATIC_COLUMNS, start_ms, end_ms, mmsis):
            yield AisStatic(*row)

    def _read(self, table, columns, start_ms, end_ms, mmsis):
        wanted = None if mmsis is None else sorted(set(mmsis))
        if wanted is not None and not wanted:
            return
        days = [d for d in self.days() if _day_start_ms(d) < end_ms and _day_start_ms(d + timedelta(days=1)) > start_ms]
        rows = []
        for day in days:
            sql = f"SELECT {', '.join(columns)} FROM {table} WHERE ts >= ? AND ts < ?"
            params: list = [start_ms, end_ms]
            if wanted is not None:
                sql += f" AND mmsi IN ({', '.join('?' * len(wanted))})"
                params += wanted
            with closing(sqlite3.connect(self.day_path(day))) as conn:
                try:
                    rows.extend(conn.execute(sql, params).fetchall())
                except sqlite3.OperationalError as error:   # a file this store did not create
                    if "no such table" not in str(error):
                        raise
        rows.sort(key=lambda r: (r[0], r[1], r[columns.index("source")]))
        yield from rows

    def apply_retention(self, limits: RetentionLimits, today: date | None = None,
                        clock: Callable[[], datetime] | None = None) -> RetentionResult:
        """Delete or empty day files past their limits (module docstring); never touches ``validation/``."""
        if today is None:
            today = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc).date()
        result = RetentionResult()
        if not self.raw_dir.is_dir() or self.raw_dir.is_symlink():
            return result
        raw = self.raw_dir.resolve()
        validation = self.validation_dir.resolve()
        if raw == validation or validation in raw.parents:
            raise RuntimeError("the raw store must not live inside validation/")
        table_days = limits.table_days()
        for entry in sorted(self.raw_dir.iterdir()):
            day = _parse_day(entry.name)
            if day is None or entry.is_symlink() or not entry.is_file() or entry.resolve().parent != raw:
                continue
            age = (today - day).days
            expired = [t for t in TABLES if age > table_days[t]]
            if not expired:
                continue
            if len(expired) == len(TABLES):
                for sidecar in _SIDECARS:
                    extra = entry.with_name(entry.name + sidecar)
                    if extra.is_file() and not extra.is_symlink():
                        extra.unlink()
                entry.unlink()
                result.deleted_files.append(entry.name)
                continue
            if entry.stat().st_nlink > 1:   # shared with another path: emptying would change that copy too
                result.skipped.append(entry.name)
                continue
            with closing(self.connect(day)) as conn:
                emptied = []
                with conn:
                    for table in expired:
                        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                            conn.execute(f"DELETE FROM {table}")
                            emptied.append(table)
                if emptied:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    conn.execute("VACUUM")
                    result.emptied[entry.name] = emptied
        return result


def _parse_day(name: str) -> date | None:
    match = DAY_FILE.match(name)
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None
