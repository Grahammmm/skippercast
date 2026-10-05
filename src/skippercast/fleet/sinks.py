"""Where registry operations go (design section 9, "Operation contract").

An operation is flat: ``{"op": <kind>, <column>: value, ...}`` as the Worker's
``POST /api/fleet/jobs/registry`` takes it (``server/fleet/registry.ts`` is the
reference). Both sinks take the same list and return
``{"ops", "changed", "counts": {kind: {"ops", "changed"}}}``:

- ``SqliteSink`` applies the committed migrations (``drizzle/meta/_journal.json``
  order) to ``<FLEET_VAR>/staging/<region>.sqlite`` and validates and upserts the
  operations with the Worker's rules (dry runs, new regions and tests);
- ``WorkerSink`` checks every operation's fields first, then POSTs
  ``{"region", "run_id", "batch", "ops"}`` with a GitHub OIDC token, at most 500
  operations and 1 MB per request, ``batch`` numbered across the whole run, and
  retries 429/5xx and transport errors with backoff.

A ``dry-run`` region refuses the WorkerSink (``open_sink``).
"""
from __future__ import annotations

from datetime import datetime, timezone
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
from .ops import MAX_ERRORS, MAX_OPS, OP_KINDS, PURGE_KEY, REGION, RUN_ID, Row, iso_ms, validate_ops, wire

MAX_BYTES = 1024 * 1024


class SinkError(RuntimeError):
    """Rejected operations; ``errors`` lists ``{index, op, error}`` by overall op index."""

    def __init__(self, message: str, errors: list[dict] | None = None):
        self.errors = list(errors or [])
        shown = "; ".join(f"op {e['index']} ({e['op']}): {e['error']}" for e in self.errors[:5])
        super().__init__(message + (f": {shown}" if shown else ""))


class SinkRefused(SinkError):
    pass


class BatchTooLarge(SinkError):
    """The Worker answered 413: the batching here is wrong. Never retried."""


def _checked(ops: list, region: str) -> list[Row]:
    rows, errors = validate_ops(ops, region)
    if errors:
        raise SinkError("invalid operations", errors)
    return rows


# ---- SqliteSink: registry.ts validateRegistry + applyRegistry over sqlite3 ---------------

def _newer(t: str, at: str, col: str) -> str:
    return f"CASE WHEN excluded.{at}>={t}.{at} THEN excluded.{col} ELSE {t}.{col} END"


def _pinned(col: str) -> str:
    return ("(CASE WHEN NOT json_valid(fleet_vessels.pinned_json) THEN 1 WHEN json_type(fleet_vessels.pinned_json)<>'object' "
            f"THEN 1 ELSE json_type(fleet_vessels.pinned_json,'$.\"{col}\"') IS NOT NULL END)")


def _vessel(col: str) -> str:
    t = "fleet_vessels"
    if col in ("first_seen_at", "last_seen_at"):
        return f"{'MIN' if col == 'first_seen_at' else 'MAX'}({t}.{col},excluded.{col})"
    keep = f"{_pinned(col)} OR excluded.last_seen_at<{t}.last_seen_at"
    if col == "profile_status":
        return (f"CASE WHEN {keep} THEN {t}.{col} WHEN {t}.removal_requested_at IS NOT NULL AND excluded.{col}='listed' "
                f"THEN {t}.{col} ELSE excluded.{col} END")
    return f"CASE WHEN {keep} THEN {t}.{col} ELSE excluded.{col} END"


def _fact(col: str) -> str:
    t = "fleet_vessel_facts"
    if col in ("retrieved_at", "last_seen_at"):
        return f"MAX({t}.{col},excluded.{col})"
    if col == "first_seen_at":
        return f"MIN({t}.{col},excluded.{col})"
    if col in ("superseded_at", "superseded_by"):
        return f"CASE WHEN {t}.superseded_at IS NOT NULL AND excluded.retrieved_at>{t}.superseded_at THEN NULL ELSE {t}.{col} END"
    return _newer(t, "retrieved_at", col)


def _seen(t: str, at: str) -> Callable[[str], str]:
    def update(col: str) -> str:
        if col == at:
            return f"MAX({t}.{col},excluded.{col})"
        if col == "first_seen_at":
            return f"MIN({t}.{col},excluded.{col})"
        return _newer(t, at, col)
    return update


# kind -> (table, conflict, insert-only columns, update expression, extra condition, created_at, updated_at stamp)
TABLES: dict[str, tuple] = {
    "operator.upsert": ("fleet_operators", "id", ("id", "region"), _seen("fleet_operators", "updated_at"), None, True, "seen"),
    "vessel.upsert": ("fleet_vessels", "id", ("id", "region"), _vessel, None, True, "clock"),
    "fact.upsert": ("fleet_vessel_facts", "id", ("id", "vessel_id", "field", "value_json", "value_key", "source_id",
                                                  "source_url"), _fact, None, False, None),
    "alias.upsert": ("fleet_aliases", "vessel_id,alias_norm", ("vessel_id", "alias_norm"),
                     _seen("fleet_aliases", "last_seen_at"), None, False, None),
    "offering.upsert": ("fleet_offerings", "id", ("id", "vessel_id"), _seen("fleet_offerings", "updated_at"), None, False, "seen"),
    "departure.upsert": ("fleet_departures", "id", ("id", "offering_id", "vessel_id", "date"),
                         _seen("fleet_departures", "retrieved_at"), None, False, None),
    "review.open": ("fleet_reviews", "id", ("id", "region", "kind", "opened_at", "run_id", "status"), None,
                    "fleet_reviews.status='open' AND fleet_reviews.region=excluded.region", False, None),
    "change.record": ("fleet_changes", "id", (), None, None, False, None),
    "run.record": ("fleet_runs", "id", ("id", "region"),
                   lambda col: "MIN(fleet_runs.started_at,excluded.started_at)" if col == "started_at" else f"excluded.{col}",
                   None, False, None),
}


class SqliteSink:
    name = "staging"

    def __init__(self, path: Path | str, region: str, run_id: str, *, root: Path | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        if not REGION.match(region) or not RUN_ID.match(run_id):
            raise SinkRefused(f"invalid region or run id: {region!r} {run_id!r}")
        self.region, self.run_id, self.clock = region, run_id, clock
        self.db = sqlite3.connect(str(path), isolation_level=None)
        self.migrate(root or repo_root())

    def migrate(self, root: Path) -> None:
        """Apply drizzle/<tag>.sql in _journal.json order, each once (tracked in _skippercast_migrations)."""
        journal = json.loads((root / "drizzle" / "meta" / "_journal.json").read_text(encoding="utf-8"))
        self.db.execute("CREATE TABLE IF NOT EXISTS _skippercast_migrations (tag TEXT PRIMARY KEY)")
        done = {tag for (tag,) in self.db.execute("SELECT tag FROM _skippercast_migrations")}
        for entry in sorted(journal["entries"], key=lambda e: e["idx"]):
            if entry["tag"] in done:
                continue
            sql = (root / "drizzle" / f"{entry['tag']}.sql").read_text(encoding="utf-8")
            self.db.execute("BEGIN")
            try:
                for statement in sql.split("--> statement-breakpoint"):
                    if statement.strip():
                        self.db.execute(statement)
                self.db.execute("INSERT INTO _skippercast_migrations VALUES (?)", (entry["tag"],))
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    def _select(self, sql: str, values) -> list[tuple]:
        values = sorted(set(values))
        return self.db.execute(sql.format(",".join("?" * len(values))), values).fetchall() if values else []

    def _references(self, rows: list[Row]) -> tuple[list[Row], list[dict]]:
        """registry.ts validateRegistry after the field checks: last op per row wins; references and slugs."""
        last = {(r.kind, r.id): r for r in rows}
        kept = [r for r in rows if last[(r.kind, r.id)] is r]
        of = lambda kind: [r for r in kept if r.kind == kind]  # noqa: E731
        vessel_ops, operator_ops, offering_ops = of("vessel.upsert"), of("operator.upsert"), of("offering.upsert")
        referenced = [r.id if r.kind == "vessel.upsert" else r.cols["vessel_id"] for r in kept
                      if r.kind not in ("operator.upsert", "review.open", "run.record", "fact.purge")]
        vessels = dict(self._select("SELECT id, region FROM fleet_vessels WHERE id IN ({})", referenced))
        operator_ids = [r.id for r in operator_ops] + [r.cols["operator_id"] for r in vessel_ops
                                                       if isinstance(r.cols.get("operator_id"), str)]
        operators = dict(self._select("SELECT id, region FROM fleet_operators WHERE id IN ({})", operator_ids))
        offerings = dict(self._select("SELECT id, vessel_id FROM fleet_offerings WHERE id IN ({})",
                                      [r.cols["offering_id"] for r in of("departure.upsert")] + [r.id for r in offering_ops]))
        batch_offerings = {r.id: r.cols["vessel_id"] for r in offering_ops}
        batch_vessels, batch_operators = {r.id for r in vessel_ops}, {r.id for r in operator_ops}
        v_slugs, o_slugs = [r.cols["slug"] for r in vessel_ops], [r.cols["slug"] for r in operator_ops]
        v_owner = {s: i for i, s in self._select("SELECT id, slug FROM fleet_vessels WHERE slug IN ({})", v_slugs)}
        advisor = {s for (s,) in self._select("SELECT slug FROM advisor_boats WHERE slug IN ({})", v_slugs)}
        o_owner = {s: i for i, s in self._select("SELECT id, slug FROM fleet_operators WHERE slug IN ({})", o_slugs)}
        known = lambda v: v in batch_vessels or vessels.get(v) == self.region  # noqa: E731
        claimed, ok, errors = {}, [], []
        for row in kept:
            problems = []
            if row.kind in ("operator.upsert", "vessel.upsert"):
                prefix, stored, owner = (("o:", operators, o_owner) if row.kind == "operator.upsert" else ("v:", vessels, v_owner))
                slug = row.cols["slug"]
                if row.id in stored and stored[row.id] != self.region:
                    problems.append(f"id: {row.kind.split('.')[0]} belongs to another region")
                mine = claimed.get(prefix + slug)
                if (owner.get(slug, row.id) != row.id or (mine and mine != row.id)
                        or (prefix == "v:" and slug in advisor)):
                    problems.append("slug: already taken")
                claimed[prefix + slug] = row.id
                operator = row.cols.get("operator_id")
                if (row.kind == "vessel.upsert" and isinstance(operator, str) and operator not in batch_operators
                        and operators.get(operator) != self.region):
                    problems.append("operator_id: unknown operator in this region")
            elif row.kind == "departure.upsert":
                if not known(row.cols["vessel_id"]):
                    problems.append("vessel_id: unknown vessel in this region")
                owner = batch_offerings.get(row.cols["offering_id"], offerings.get(row.cols["offering_id"]))
                if owner is None:
                    problems.append("offering_id: unknown offering")
                elif owner != row.cols["vessel_id"]:
                    problems.append("offering_id: belongs to another vessel")
            elif row.kind == "offering.upsert":
                if not known(row.cols["vessel_id"]):
                    problems.append("vessel_id: unknown vessel in this region")
                if offerings.get(row.id, row.cols["vessel_id"]) != row.cols["vessel_id"]:
                    problems.append("id: offering belongs to another vessel")
            elif row.kind in ("fact.upsert", "alias.upsert", "change.record") and not known(row.cols["vessel_id"]):
                problems.append("vessel_id: unknown vessel in this region")
            errors += [{"index": row.index, "op": row.kind, "error": p} for p in problems]
            if not problems:
                ok.append(row)
        return ok, errors

    def _stored(self, row: Row) -> dict:
        cols = dict(row.cols)
        if row.kind in ("operator.upsert", "vessel.upsert"):
            cols["region"] = self.region
        elif row.kind == "fact.upsert":
            cols.update(run_id=self.run_id, superseded_at=None, superseded_by=None)
        elif row.kind == "review.open":
            cols.update(region=self.region, run_id=self.run_id, status="open")
        elif row.kind == "change.record":
            cols["run_id"] = self.run_id
        elif row.kind == "run.record":
            cols.update(id=f"{self.run_id}:{row.cols['step']}", region=self.region)
        return cols

    def _upsert(self, kind: str, cols: dict, now: str) -> int:
        table, conflict, insert_only, update, where, created, stamp = TABLES[kind]
        full = {**cols, **({"created_at": now} if created else {}), **({"updated_at": now} if stamp == "clock" else {})}
        columns = sorted(full)
        updatable = [c for c in columns if c not in insert_only and c != "created_at"
                     and not (c == "updated_at" and stamp == "clock")]
        sets = [(c, update(c) if update else f"excluded.{c}") for c in updatable]
        sql = f"INSERT INTO {table}({','.join(columns)}) VALUES ({','.join('?' * len(columns))})"
        if kind == "change.record" or not sets:
            sql += " ON CONFLICT DO NOTHING"
        else:
            assignments = [f"{c}={expr}" for c, expr in sets] + (["updated_at=excluded.updated_at"] if stamp == "clock" else [])
            changed = " OR ".join(f"({expr}) IS NOT {table}.{c}" for c, expr in sets)
            condition = " AND ".join(filter(None, [where, f"({changed})"]))
            sql += f" ON CONFLICT({conflict}) DO UPDATE SET {','.join(assignments)} WHERE {condition}"
        before = self.db.total_changes
        self.db.execute(sql, [full[c] for c in columns])
        return self.db.total_changes - before

    def apply(self, operations: Iterable[Mapping[str, Any]]) -> dict:
        """Validate every operation (fields, then references), then write them all in one transaction."""
        ops = [dict(op) for op in operations]
        rows, errors = validate_ops(ops, self.region)
        rows, more = self._references(rows)  # the Worker checks references on the valid rows either way
        errors = sorted((errors + more)[:MAX_ERRORS], key=lambda e: e["index"])
        if errors:
            raise SinkError("invalid operations", errors)
        now, counts, changed = iso_ms(self.clock()), {}, 0
        self.db.execute("BEGIN")
        try:
            for kind in OP_KINDS:
                mine = [r for r in rows if r.kind == kind]
                if not mine:
                    continue
                count = counts[kind] = {"ops": len(mine), "changed": 0}
                if kind == "fact.purge":
                    for row in mine:
                        before = self.db.total_changes
                        self.db.execute(
                            "DELETE FROM fleet_vessel_facts WHERE source_id=? AND last_seen_at<? AND field<>? AND NOT EXISTS "
                            "(SELECT 1 FROM json_each(?) WHERE json_each.value=fleet_vessel_facts.field) "
                            "AND vessel_id IN (SELECT id FROM fleet_vessels WHERE region=?)",
                            [row.cols["source_id"], row.cols["seen_before"], PURGE_KEY, row.cols["keep_fields"],
                             self.region])
                        count["changed"] += self.db.total_changes - before
                    changed += count["changed"]
                    continue
                for row in mine:
                    count["changed"] += self._upsert(kind, self._stored(row), now)
                for row in mine:
                    if row.supersedes:
                        at, before = row.cols["retrieved_at"], self.db.total_changes
                        self.db.execute(
                            "UPDATE fleet_vessel_facts SET superseded_at=?, superseded_by=? WHERE vessel_id=? AND field=? "
                            f"AND superseded_at IS NULL AND retrieved_at<=? AND id IN ({','.join('?' * len(row.supersedes))})",
                            [at, row.id, row.cols["vessel_id"], row.cols["field"], at, *row.supersedes])
                        count["changed"] += self.db.total_changes - before
                changed += count["changed"]
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise
        return {"ops": len(ops), "changed": changed, "counts": counts}

    def close(self) -> None:
        self.db.close()


# ---- WorkerSink ------------------------------------------------------------------------

class WorkerSink:
    name = "worker"
    path = "/api/fleet/jobs/registry"
    RETRY = (429, 500, 502, 503, 504)

    def __init__(self, base: str, region: str, run_id: str, next_batch: Callable[[], int], *, opener=urlopen,
                 token_source: Callable[[], str] | None = None, sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic, attempts: int = 5):
        parts = urlsplit(base)
        if parts.scheme != "https" and parts.hostname not in ("127.0.0.1", "localhost"):
            raise SinkRefused(f"the Worker base must be https: {base}")
        if not REGION.match(region) or not RUN_ID.match(run_id):
            raise SinkRefused(f"invalid region or run id: {region!r} {run_id!r}")
        self.base, self.region, self.run_id, self.next_batch = base.rstrip("/"), region, run_id, next_batch
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

    @staticmethod
    def batches(ops: list) -> Iterable[tuple[int, list]]:
        """(start index, ops) chunks of at most MAX_OPS operations and well under MAX_BYTES of JSON."""
        start, batch, size = 0, [], 0
        for index, op in enumerate(ops):
            length = len(json.dumps(op, separators=(",", ":"), ensure_ascii=False).encode()) + 1
            if batch and (len(batch) == MAX_OPS or size + length > MAX_BYTES - 4096):
                yield start, batch
                start, batch, size = index, [], 0
            batch.append(op)
            size += length
        if batch:
            yield start, batch

    def _post(self, start: int, batch: list) -> dict:
        number = self.next_batch()
        body = json.dumps({"region": self.region, "run_id": self.run_id, "batch": number, "ops": batch},
                          separators=(",", ":"), ensure_ascii=False).encode()
        for attempt in range(1, self.attempts + 1):
            request = Request(self.base + self.path, data=body, method="POST", headers={
                "Authorization": "Bearer " + self.token(), "Content-Type": "application/json",
                "Accept": "application/json", "User-Agent": self.user_agent})
            try:
                with self.opener(request, timeout=60) as response:
                    return json.load(response)
            except HTTPError as error:
                try:
                    detail = json.loads(error.read() or b"{}")
                except ValueError:
                    detail = {}
                if error.code == 413:
                    raise BatchTooLarge(f"batch {number} (ops {start}-{start + len(batch) - 1}): HTTP 413 "
                                        f"{detail.get('error', '')}; the WorkerSink batching is wrong") from None
                if error.code not in self.RETRY or attempt == self.attempts:
                    errors = [{**e, "index": start + e["index"]} for e in detail.get("errors", [])
                              if isinstance(e, dict) and isinstance(e.get("index"), int)]
                    raise SinkError(f"batch {number}: HTTP {error.code} {detail.get('error', '')}".strip(), errors) from None
            except OSError as error:
                if attempt == self.attempts:
                    raise SinkError(f"batch {number}: {type(error).__name__}: {error}") from None
            self.sleep(min(60.0, 2.0 ** attempt))
        raise AssertionError("unreachable")  # pragma: no cover

    def apply(self, operations: Iterable[Mapping[str, Any]]) -> dict:
        ops = [dict(op) for op in operations]
        _checked(ops, self.region)  # the Worker's field checks first: nothing is sent if any op is invalid
        ops = [wire(op) for op in ops]
        result = {"ops": len(ops), "changed": 0, "counts": {}}
        for start, batch in self.batches(ops):
            reply = self._post(start, batch)
            result["changed"] += int(reply.get("changed", 0))
            for kind, count in (reply.get("counts") or {}).items():
                total = result["counts"].setdefault(kind, {"ops": 0, "changed": 0})
                total["ops"] += int(count.get("ops", 0))
                total["changed"] += int(count.get("changed", 0))
        return result

    def close(self) -> None:
        pass


def worker_base(environ: Mapping[str, str] | None = None) -> str:
    environ = os.environ if environ is None else environ
    base = environ.get("SKIPPERCAST_PUBLIC_BASE", "").strip()
    if base:
        return base
    return json.loads((repo_root() / "deployments" / "production.json").read_text(encoding="utf-8"))["public_origin"]


def open_sink(kind: str, region, run, **options: Any):
    """The sink named on the command line; a dry-run region never gets the WorkerSink."""
    if kind == "staging":
        return SqliteSink(run.staging_db(), region.id, run.id)
    if kind == "worker":
        if region.status == "dry-run":
            raise SinkRefused(f"region {region.id} is dry-run: only the staging sink is allowed")
        return WorkerSink(options.pop("base", None) or worker_base(), region.id, run.id, run.next_batch, **options)
    raise SinkRefused(f"unknown sink {kind!r}")
