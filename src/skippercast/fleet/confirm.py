"""``confirm``: a private ledger of operator-confirmed charter identities.

``python -m skippercast.fleet confirm add --region CA [--sink staging|worker] --vessel-id ID --mmsi 9DIGITS
--method METHOD --confirmed-on YYYY-MM-DD --evidence-ref TOKEN``

``python -m skippercast.fleet confirm withdraw --region CA [--sink ...] --vessel-id ID --mmsi 9DIGITS --withdrawn-on DATE``

``python -m skippercast.fleet confirm list --region CA [--sink ...]``

A registry MMSI is not an operator-confirmed identity (``catalog/data-needs.json`` ``charter-identity``). This
module records that a person confirmed one, privately: ``<FLEET_VAR>/<region>/confirmations/<sink>.json``
(version 1, ``{"version": 1, "entries": [...]}``), one ledger per sink so a staging confirmation never counts
against the Worker registry. It is not the Worker registry (no D1 migration), is never published and is never
committed; ``var/`` is gitignored.

One entry per exact (``vessel_id``, ``mmsi``): ``method`` (``METHODS``), ``confirmed_on``, ``evidence_ref`` and
``withdrawn_on`` (null while the confirmation stands). The evidence reference is an opaque token that points at
evidence kept elsewhere; it is never a name, contact, path or URL. Recording a confirmation neither investigates
nor authenticates that evidence.

``add`` and ``withdraw`` read the selected registry first (staging: the SQLite file, read-only; worker: the
snapshot pages) and refuse an MMSI the registry does not hold for that vessel. A stale binding (the registry no
longer holds the pair) never counts and cannot be withdrawn either, so its evidence is never silently reassigned.
This is a current-state ledger, not an audit archive: re-confirming a withdrawn pair replaces its entry.
Nothing printed contains an evidence reference, a name, a path or a rejected input.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import sys
from typing import Any, Callable, Iterable, Mapping

from .ingest import load_snapshot
from .resolve import Snapshot
from .runs import fleet_var, new_run_id
from .sinks import WorkerSink, worker_base

VERSION = 1
SINKS = ("staging", "worker")
METHODS = ("operator-statement", "uscg-documentation-matched-to-operator", "cdfw-cpfv-licence-matched-to-operator")
ROW_KEYS = frozenset({"vessel_id", "mmsi", "method", "confirmed_on", "evidence_ref", "withdrawn_on"})
REGION, VESSEL, MMSI = re.compile(r"^[A-Z]{2}$"), re.compile(r"^[A-Za-z0-9_-]{1,64}$"), re.compile(r"^[0-9]{9}$")
EVIDENCE, DATE = re.compile(r"^[A-Za-z0-9_-]{1,128}$"), re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

LEDGER_BAD = "the confirmation ledger is unreadable or invalid"
REGISTRY_BAD = "the registry could not be read"
NOT_HELD = "the registry does not hold this MMSI for this vessel"


class ConfirmError(Exception):
    """A refusal. The message is fixed text; it never holds a supplied value."""


def today() -> date:
    return datetime.now(timezone.utc).date()


# ---- validation ------------------------------------------------------------------------------

def _date(text: Any, *, latest: date | None = None) -> date:
    if not isinstance(text, str) or not DATE.fullmatch(text):
        raise ConfirmError("invalid date")
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        raise ConfirmError("invalid date") from None
    if latest is not None and parsed > latest:
        raise ConfirmError("date is in the future")
    return parsed


def _text(pattern: re.Pattern, value: Any, message: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ConfirmError(message)
    return value


def _identity(region: str, sink: str, vessel_id: Any, mmsi: Any) -> tuple[str, str]:
    if not isinstance(region, str) or not REGION.fullmatch(region) or sink not in SINKS:
        raise ConfirmError("invalid region or sink")
    return _text(VESSEL, vessel_id, "invalid vessel id"), _text(MMSI, mmsi, "invalid MMSI")


def _checked_entry(row: Any) -> dict:
    if not isinstance(row, dict) or set(row) != ROW_KEYS:
        raise ConfirmError(LEDGER_BAD)
    try:
        _text(VESSEL, row["vessel_id"], LEDGER_BAD), _text(MMSI, row["mmsi"], LEDGER_BAD)
        _text(EVIDENCE, row["evidence_ref"], LEDGER_BAD)
        if row["method"] not in METHODS:
            raise ConfirmError(LEDGER_BAD)
        latest = today()
        confirmed = _date(row["confirmed_on"], latest=latest)
        if row["withdrawn_on"] is not None and _date(row["withdrawn_on"], latest=latest) < confirmed:
            raise ConfirmError(LEDGER_BAD)
    except ConfirmError:
        raise ConfirmError(LEDGER_BAD) from None
    return dict(row)


def parse_ledger(doc: Any) -> list[dict]:
    """The entries of a version-1 document; any deviation (shape, field, date, duplicate pair) is a refusal."""
    if (not isinstance(doc, dict) or set(doc) != {"version", "entries"} or type(doc["version"]) is not int
            or doc["version"] != VERSION or not isinstance(doc["entries"], list)):
        raise ConfirmError(LEDGER_BAD)
    entries = [_checked_entry(row) for row in doc["entries"]]
    if len({(e["vessel_id"], e["mmsi"]) for e in entries}) != len(entries):
        raise ConfirmError(LEDGER_BAD)
    return entries


# ---- the private file ------------------------------------------------------------------------

def ledger_path(region: str, sink: str, var: Path | None = None) -> Path:
    _identity(region, sink, "x", "000000000")
    return Path(var if var is not None else fleet_var()) / region / "confirmations" / f"{sink}.json"


def _no_symlinks(path: Path) -> None:
    for item in (path.parent.parent, path.parent, path):
        if item.is_symlink():
            raise ConfirmError(LEDGER_BAD)


def load_confirmations(region: str, sink: str, var: Path | None = None) -> list[dict]:
    """The sink's entries (withdrawn ones included); an absent ledger is empty and nothing is created."""
    path = ledger_path(region, sink, var)
    _no_symlinks(path)
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except FileNotFoundError:
        return []
    except OSError:
        raise ConfirmError(LEDGER_BAD) from None
    try:
        with os.fdopen(descriptor, "rb") as handle:
            return parse_ledger(json.loads(handle.read().decode("utf-8")))
    except (OSError, ValueError):  # includes JSON and UTF-8 errors
        raise ConfirmError(LEDGER_BAD) from None


def _write(path: Path, entries: Iterable[Mapping]) -> None:
    body = json.dumps({"version": VERSION, "entries": sorted(entries, key=lambda e: (e["vessel_id"], e["mmsi"]))},
                      indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    try:
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _update(region: str, sink: str, var: Path | None, change: Callable[[list[dict]], tuple[list[dict], int]]) -> int:
    """Apply ``change`` (entries -> (entries, affected)) under an exclusive lock; the affected count.

    Everything is validated on a dry pass first, so a refusal creates nothing. The ledger is read again once the
    lock is held, so two local writers cannot lose each other's update.
    """
    path = ledger_path(region, sink, var)
    _no_symlinks(path)
    change(load_confirmations(region, sink, var))
    created = not path.parent.exists()
    try:
        os.makedirs(path.parent, mode=0o700, exist_ok=True)
        if created:
            os.chmod(path.parent, 0o700)
        _no_symlinks(path)
        lock = os.open(path.with_name(f"{sink}.lock"), os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except OSError:
        raise ConfirmError(LEDGER_BAD) from None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        entries, affected = change(load_confirmations(region, sink, var))
        if affected:
            try:
                _write(path, entries)
            except OSError:
                raise ConfirmError("the confirmation ledger could not be written") from None
        return affected
    finally:
        os.close(lock)  # releases the lock


# ---- add / withdraw --------------------------------------------------------------------------

def _held(held: Callable[[], Mapping[str, str]], vessel_id: str, mmsi: str) -> None:
    if held().get(vessel_id) != mmsi:
        raise ConfirmError(NOT_HELD)


def add(region: str, sink: str, vessel_id: str, mmsi: str, method: str, confirmed_on: str, evidence_ref: str,
        held: Callable[[], Mapping[str, str]], *, var: Path | None = None, now: date | None = None) -> int:
    """Record a confirmation; 1 when the ledger changed, 0 for an identical one already standing."""
    vessel_id, mmsi = _identity(region, sink, vessel_id, mmsi)
    if method not in METHODS:
        raise ConfirmError("unknown method")
    when = _date(confirmed_on, latest=now or today())
    row = {"vessel_id": vessel_id, "mmsi": mmsi, "method": method, "confirmed_on": when.isoformat(),
           "evidence_ref": _text(EVIDENCE, evidence_ref, "invalid evidence reference"), "withdrawn_on": None}
    _held(held, vessel_id, mmsi)

    def change(entries: list[dict]) -> tuple[list[dict], int]:
        old = next((e for e in entries if (e["vessel_id"], e["mmsi"]) == (vessel_id, mmsi)), None)
        if old is None:
            return entries + [row], 1
        if old["withdrawn_on"] is None:
            if old == row:
                return entries, 0
            raise ConfirmError("a different confirmation stands for this vessel and MMSI; withdraw it first")
        if not (when > _date(old["confirmed_on"]) and when >= _date(old["withdrawn_on"])):
            raise ConfirmError("a re-confirmation must be dated after the earlier confirmation and not before its withdrawal")
        return [row if e is old else e for e in entries], 1

    return _update(region, sink, var, change)


def withdraw(region: str, sink: str, vessel_id: str, mmsi: str, withdrawn_on: str,
             held: Callable[[], Mapping[str, str]], *, var: Path | None = None, now: date | None = None) -> int:
    """Withdraw a confirmation; 1 when the ledger changed, 0 for a repeat of the same withdrawal."""
    vessel_id, mmsi = _identity(region, sink, vessel_id, mmsi)
    when = _date(withdrawn_on, latest=now or today())
    _held(held, vessel_id, mmsi)

    def change(entries: list[dict]) -> tuple[list[dict], int]:
        old = next((e for e in entries if (e["vessel_id"], e["mmsi"]) == (vessel_id, mmsi)), None)
        if old is None:
            raise ConfirmError("no confirmation is recorded for this vessel and MMSI")
        if old["withdrawn_on"] is not None:
            if old["withdrawn_on"] == when.isoformat():
                return entries, 0
            raise ConfirmError("this confirmation is already withdrawn on another date")
        if when < _date(old["confirmed_on"]):
            raise ConfirmError("a withdrawal cannot predate the confirmation")
        return [{**old, "withdrawn_on": when.isoformat()} if e is old else e for e in entries], 1

    return _update(region, sink, var, change)


def active_pairs(entries: Iterable[Mapping]) -> set[tuple[str, str]]:
    """The (vessel id, MMSI) pairs whose confirmation has not been withdrawn."""
    return {(e["vessel_id"], e["mmsi"]) for e in entries if e.get("withdrawn_on") is None}


# ---- the registry (read only) ----------------------------------------------------------------

def read_registry(region: str, sink: str, var: Path | None = None) -> Snapshot:
    """The selected registry's vessels; never writes: staging opens an existing SQLite file read-only."""
    try:
        if sink == "staging":
            path = Path(var if var is not None else fleet_var()) / "staging" / f"{region}.sqlite"
            if not path.is_file():
                raise ConfirmError(REGISTRY_BAD)
            db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
            try:
                return Snapshot.from_sqlite(db, region, facts=False)
            finally:
                db.close()
        worker = WorkerSink(worker_base(), region, new_run_id(), lambda: 0)
        try:
            return load_snapshot(worker, region)
        finally:
            worker.close()
    except ConfirmError:
        raise
    except Exception:  # transport, token, schema: the cause may hold a URL, so none of it is shown
        raise ConfirmError(REGISTRY_BAD) from None


def held_mmsi(snapshot: Snapshot) -> dict[str, str]:
    """``{vessel id: MMSI}`` for each registry vessel that has one."""
    return {v["id"]: str(v["mmsi"]).strip() for v in snapshot.vessels
            if isinstance(v.get("id"), str) and v.get("mmsi") not in (None, "")}


def listing(entries: Iterable[Mapping], held: Mapping[str, str]) -> list[dict]:
    """Opaque fields only, ordered by vessel id and MMSI; ``state`` is withdrawn, active or stale (not held now)."""
    rows = []
    for e in sorted(entries, key=lambda e: (e["vessel_id"], e["mmsi"])):
        state = "withdrawn" if e["withdrawn_on"] else "active" if held.get(e["vessel_id"]) == e["mmsi"] else "stale"
        rows.append({"vessel_id": e["vessel_id"], "mmsi": e["mmsi"], "method": e["method"],
                     "confirmed_on": e["confirmed_on"], "withdrawn_on": e["withdrawn_on"], "state": state})
    return rows


# ---- command line ----------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # argparse echoes the offending argument; this never does
        self.print_usage(sys.stderr)
        self.exit(2, "confirm: invalid or missing arguments\n")


def _parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="python -m skippercast.fleet confirm", allow_abbrev=False,
                     description="Record, withdraw and list private operator-confirmed charter identities.")
    actions = parser.add_subparsers(dest="action", required=True, parser_class=_Parser)

    def common(sub: argparse.ArgumentParser, vessel: bool = True) -> None:
        sub.add_argument("--region", required=True, help="fleet region id, e.g. CA")
        sub.add_argument("--sink", default="staging", help="staging (default) or worker: the registry and ledger to use")
        if vessel:
            sub.add_argument("--vessel-id", required=True)
            sub.add_argument("--mmsi", required=True, help="nine digits")

    add_parser = actions.add_parser("add", allow_abbrev=False, help="record a confirmation")
    common(add_parser)
    add_parser.add_argument("--method", required=True, help="one of: " + ", ".join(METHODS))
    add_parser.add_argument("--confirmed-on", required=True, help="YYYY-MM-DD, not in the future")
    add_parser.add_argument("--evidence-ref", required=True, help="opaque private token, 1-128 of A-Z a-z 0-9 _ -")
    withdraw_parser = actions.add_parser("withdraw", allow_abbrev=False, help="withdraw a confirmation")
    common(withdraw_parser)
    withdraw_parser.add_argument("--withdrawn-on", required=True, help="YYYY-MM-DD, not in the future")
    common(actions.add_parser("list", allow_abbrev=False, help="list entries (no evidence references)"), vessel=False)
    return parser


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.sink not in SINKS or not REGION.fullmatch(args.region):
            raise ConfirmError("invalid region or sink")
        registry: dict[str, str] = {}

        def held() -> Mapping[str, str]:
            if not registry:
                registry.update(held_mmsi(read_registry(args.region, args.sink)))
            return registry

        if args.action == "list":
            entries = load_confirmations(args.region, args.sink)
            print(json.dumps({"confirmations": listing(entries, held() if entries else {})}, indent=2, sort_keys=True))
            return 0
        if args.action == "add":
            affected = add(args.region, args.sink, args.vessel_id, args.mmsi, args.method, args.confirmed_on,
                           args.evidence_ref, held)
        else:
            affected = withdraw(args.region, args.sink, args.vessel_id, args.mmsi, args.withdrawn_on, held)
    except ConfirmError as error:
        print(f"confirm {args.action}: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"action": args.action, "affected": affected}, sort_keys=True))
    return 0
