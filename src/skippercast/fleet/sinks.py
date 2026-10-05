"""Where registry operations go (design section 9).

An operation is ``{"kind": <kind>, "row": {<snake_case column>: value}}`` with
``row`` keyed by the target ``fleet_*`` table's columns and carrying its
deterministic id. Both sinks take the same list:

- ``SqliteSink`` applies the committed ``drizzle/*.sql`` migrations to
  ``<FLEET_VAR>/staging/<region>.sqlite`` and upserts each operation (dry runs,
  new regions and tests);
- ``WorkerSink`` POSTs ``{"region", "run_id", "step", "operations"}`` to
  ``/api/fleet/jobs/registry`` with a GitHub OIDC token, at most 500 operations
  and 1 MB per request, retrying 429/5xx and transport errors with backoff.

A ``dry-run`` region refuses the WorkerSink (``open_sink``).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable, Iterable, Mapping
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from .. import __version__
from ..paths import repo_root

# kind -> (table, key columns). review.open only updates a review still open;
# change.record never rewrites a recorded change.
KINDS: Mapping[str, tuple[str, tuple[str, ...]]] = {
    "vessel.upsert": ("fleet_vessels", ("id",)),
    "operator.upsert": ("fleet_operators", ("id",)),
    "fact.upsert": ("fleet_vessel_facts", ("id",)),
    "alias.upsert": ("fleet_aliases", ("vessel_id", "alias_norm")),
    "offering.upsert": ("fleet_offerings", ("id",)),
    "departure.upsert": ("fleet_departures", ("id",)),
    "review.open": ("fleet_reviews", ("id",)),
    "change.record": ("fleet_changes", ("id",)),
    "run.record": ("fleet_runs", ("id",)),
}
MAX_OPS = 500
MAX_BYTES = 1_000_000


class SinkError(RuntimeError):
    def __init__(self, message: str, index: int | None = None):
        super().__init__(message if index is None else f"operation {index}: {message}")
        self.index = index


class SinkRefused(SinkError):
    pass


def _check(index: int, op: Any) -> tuple[str, tuple[str, ...], dict]:
    if not isinstance(op, Mapping) or op.get("kind") not in KINDS or not isinstance(op.get("row"), Mapping):
        raise SinkError("expected {kind, row} with a known kind", index)
    table, keys = KINDS[op["kind"]]
    row = dict(op["row"])
    if any(row.get(k) in (None, "") for k in keys):
        raise SinkError(f"missing key {', '.join(keys)}", index)
    if op["kind"] == "fact.upsert" and not str(row.get("source_url") or "").startswith(("https://", "admin:")):
        raise SinkError("a fact needs an https source_url or admin: provenance", index)
    return table, keys, row


class SqliteSink:
    name = "staging"

    def __init__(self, path: Path | str, migrations: Path | None = None):
        self.db = sqlite3.connect(str(path))
        self.db.execute("PRAGMA foreign_keys = ON")
        self.migrate(migrations or repo_root() / "drizzle")
        self._columns: dict[str, set[str]] = {}

    def migrate(self, directory: Path) -> None:
        self.db.execute("CREATE TABLE IF NOT EXISTS _skippercast_migrations (name TEXT PRIMARY KEY)")
        done = {name for (name,) in self.db.execute("SELECT name FROM _skippercast_migrations")}
        for path in sorted(Path(directory).glob("*.sql")):
            if path.name in done:
                continue
            with self.db:
                for statement in path.read_text(encoding="utf-8").split("--> statement-breakpoint"):
                    if statement.strip():
                        self.db.execute(statement)
                self.db.execute("INSERT INTO _skippercast_migrations VALUES (?)", (path.name,))

    def columns(self, table: str) -> set[str]:
        if table not in self._columns:
            self._columns[table] = {row[1] for row in self.db.execute(f"PRAGMA table_info({table})")}
        return self._columns[table]

    def apply(self, operations: Iterable[Mapping[str, Any]]) -> dict:
        """Upsert every operation in one transaction; returns {"operations", "changes"}."""
        before, count = self.db.total_changes, 0
        with self.db:
            for index, op in enumerate(operations):
                table, keys, row = _check(index, op)
                unknown = set(row) - self.columns(table)
                if unknown:
                    raise SinkError(f"unknown column(s) for {table}: {', '.join(sorted(unknown))}", index)
                cols = list(row)
                sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                updates = [c for c in cols if c not in keys]
                if updates and op["kind"] != "change.record":
                    differs = " OR ".join(f"{table}.{c} IS NOT excluded.{c}" for c in updates)
                    guard = f"({differs})" + (f" AND {table}.status = 'open'" if op["kind"] == "review.open" else "")
                    sql += (f" ON CONFLICT ({', '.join(keys)}) DO UPDATE SET "
                            + ", ".join(f"{c} = excluded.{c}" for c in updates) + f" WHERE {guard}")
                else:
                    sql += f" ON CONFLICT ({', '.join(keys)}) DO NOTHING"
                self.db.execute(sql, [row[c] for c in cols])
                count += 1
        return {"operations": count, "changes": self.db.total_changes - before}

    def close(self) -> None:
        self.db.close()


class WorkerSink:
    name = "worker"
    path = "/api/fleet/jobs/registry"

    def __init__(self, base: str, region: str, run_id: str, step: str, *, opener=urlopen,
                 token_source: Callable[[], str] | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, attempts: int = 5):
        parts = urlsplit(base)
        if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
            raise SinkRefused(f"the Worker base must be https: {base}")
        self.base, self.region, self.run_id, self.step = base.rstrip("/"), region, run_id, step
        self.audience = self.base + "/api/fleet/jobs"
        self.opener, self.sleep, self.clock, self.attempts = opener, sleep, clock, attempts
        self.token_source = token_source or self._github_token
        self.user_agent = f"SkipperCast-fleet/{__version__} (+{self.base})"
        self._token, self._at = None, -1e9

    def _github_token(self) -> str:
        url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&" + urlencode({"audience": self.audience})
        request = Request(url, headers={"Authorization": "Bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"],
                                        "User-Agent": self.user_agent})
        with self.opener(request, timeout=20) as response:
            return json.load(response)["value"]

    def token(self) -> str:
        # GitHub's tokens live about five minutes; the Worker refuses any lifetime over ten.
        if self._token is None or self.clock() - self._at > 240:
            self._token, self._at = self.token_source(), self.clock()
        return self._token

    def batches(self, operations: list) -> Iterable[tuple[int, list]]:
        start, batch, size = 0, [], 0
        for index, op in enumerate(operations):
            length = len(json.dumps(op, separators=(",", ":"))) + 1
            if batch and (len(batch) == MAX_OPS or size + length > MAX_BYTES - 1024):
                yield start, batch
                start, batch, size = index, [], 0
            batch.append(op)
            size += length
        if batch:
            yield start, batch

    def _post(self, start: int, batch: list) -> dict:
        body = json.dumps({"region": self.region, "run_id": self.run_id, "step": self.step, "operations": batch},
                          separators=(",", ":")).encode()
        for attempt in range(1, self.attempts + 1):
            request = Request(self.base + self.path, data=body, method="POST", headers={
                "Authorization": "Bearer " + self.token(), "Content-Type": "application/json",
                "Accept": "application/json", "User-Agent": self.user_agent})
            try:
                with self.opener(request, timeout=60) as response:
                    return json.load(response)
            except HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == self.attempts:
                    try:
                        detail = json.loads(error.read() or b"{}")
                    except ValueError:
                        detail = {}
                    index = detail.get("index")
                    raise SinkError(f"HTTP {error.code} {detail.get('error', '')}".strip(),
                                    start + index if isinstance(index, int) else None) from None
            except OSError as error:
                if attempt == self.attempts:
                    raise SinkError(f"{type(error).__name__}: {error}") from None
            self.sleep(min(60.0, 2.0 ** attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    def apply(self, operations: Iterable[Mapping[str, Any]]) -> dict:
        operations = list(operations)
        for index, op in enumerate(operations):
            _check(index, op)
        changes = 0
        for start, batch in self.batches(operations):
            changes += int(self._post(start, batch).get("changes", 0))
        return {"operations": len(operations), "changes": changes}

    def close(self) -> None:
        pass


def worker_base(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    base = environ.get("SKIPPERCAST_PUBLIC_BASE", "").strip()
    if base:
        return base
    return json.loads((repo_root() / "deployments" / "production.json").read_text(encoding="utf-8"))["public_origin"]


def open_sink(kind: str, region, run, step: str, **options: Any):
    """The sink named on the command line; a dry-run region never gets the WorkerSink."""
    if kind == "staging":
        return SqliteSink(run.staging_db())
    if kind == "worker":
        if region.status == "dry-run":
            raise SinkRefused(f"region {region.id} is dry-run: only the staging sink is allowed")
        return WorkerSink(options.pop("base", None) or worker_base(), region.id, run.id, step, **options)
    raise SinkRefused(f"unknown sink {kind!r}")
