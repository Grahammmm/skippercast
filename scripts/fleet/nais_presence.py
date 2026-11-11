#!/usr/bin/env python3
"""NAIS transmit check (AISLIVE-02): for a few private targets, count the days each was heard in a window.

Reads NOAA MarineCadastre day files through the existing ``MarineCadastreSource.history`` (same host, policy HTTP
client and parser) and counts, per label, the region-local days with a position inside the named port geofences
("home") and the days with any record in the region box ("anywhere"). It stores nothing: no Worker call, no registry,
``watch.json``, backfill store or ``state.sqlite``; it does not call ``backfill()`` (which needs approved identities
and pushes trips). Stdout carries labels and counts only, never an MMSI, a name or a position.

Exit: 0 at least one day read; 1 every day missing or failed; 2 bad arguments; 3 disk below the floor.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from zoneinfo import ZoneInfo

from skippercast.fleet.ais.backfill import utc_days, window_ms
from skippercast.fleet.ais.sources.base import AisPosition, bbox_of, valid_mmsi
from skippercast.fleet.ais.sources.marinecadastre import CorruptDay, DayNotPublished, MalformedFile, MarineCadastreSource
from skippercast.fleet.ais.store import ais_root
from skippercast.fleet.config import load_region

MAX_DAYS = 7
MAX_LABELS = 5
DEFAULT_PORTS = "morro-bay,port-san-luis"
NOTE = ("\"Not heard\" proves neither that a boat has no transponder nor that it made no trip; "
        "NAIS coverage and the boat's transponder use both vary.")


def _free_gb(path: Path) -> float:
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1e9


def _unique_members(pairs: list[tuple[str, object]]) -> dict[str, object]:
    # json.loads keeps only the last of a repeated member, which would silently change which target a label names
    # (or hide an invalid earlier value). Names are compared after decoding, so "A" and "\u0041" collide.
    members: dict[str, object] = {}
    for name, value in pairs:
        if name in members:
            raise ValueError("duplicate JSON member")
        members[name] = value
    return members


def _targets(path: str) -> dict[str, int]:
    try:
        document = json.loads(Path(path).read_text(), object_pairs_hook=_unique_members)
    except (OSError, ValueError):
        raise ValueError("--targets is not a readable JSON file") from None
    if not isinstance(document, dict) or not 1 <= len(document) <= MAX_LABELS:
        raise ValueError(f"--targets must hold 1 to {MAX_LABELS} labels")
    for label, mmsi in document.items():
        if not re.fullmatch(r"[A-Z]", label):
            raise ValueError("every target label is one capital letter")
        if not valid_mmsi(mmsi):
            raise ValueError(f"target {label} has an invalid MMSI")
    if len(set(document.values())) != len(document):
        raise ValueError("two target labels share one MMSI")
    return dict(document)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--region", required=True)
    parser.add_argument("--from", dest="start", required=True, type=date.fromisoformat, help="first region-local day")
    parser.add_argument("--to", dest="end", required=True, type=date.fromisoformat, help="last region-local day (inclusive)")
    parser.add_argument("--targets", required=True, help="private JSON file {\"A\": mmsi, ...}")
    parser.add_argument("--ports", default=DEFAULT_PORTS, help="comma-separated port ids whose geofences count as home")
    parser.add_argument("--workdir", help="where the temporary day download goes")
    parser.add_argument("--min-free-gb", type=float, default=50.0)
    parser.add_argument("--private-out", help="write per-label day lists here (mode 0600)")
    return parser


def _write_private(path: str, document: dict) -> None:
    # mkstemp creates the file 0600 in the target directory; the contents never sit in a more open file, and an existing
    # (possibly 0644) output is replaced atomically, so a failed write leaves it untouched and the temp file removed.
    target = Path(path)
    fd, temp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
        os.replace(temp, target)
    except BaseException:
        try:
            os.unlink(temp)
        except OSError:
            pass
        raise


def main(argv=None, source=None, out=None) -> int:
    out = out if out is not None else sys.stdout
    parser = _parser()
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--to is before --from")
    if (args.end - args.start).days + 1 > MAX_DAYS:
        parser.error(f"the window is at most {MAX_DAYS} days")
    try:
        targets = _targets(args.targets)
        region = load_region(args.region)
        port_ids = [p.strip() for p in args.ports.split(",") if p.strip()]
        if not port_ids:
            raise ValueError("--ports is empty")
        ports = [region.port(ident) for ident in port_ids]
    except KeyError:
        parser.error("unknown port id")
    except ValueError as error:
        parser.error(str(error))
    workdir = Path(args.workdir) if args.workdir else ais_root(region.id) / "nais-check"
    zone, bbox = ZoneInfo(region.timezone), bbox_of(region.ais)
    first, last = args.start, args.end
    window = window_ms(first, last, region.timezone)
    window_days = {(first + timedelta(days=k)).isoformat() for k in range((last - first).days + 1)}
    free = _free_gb(workdir)
    if free < args.min_free_gb:
        print(f"stopped: {free:.0f} GB free, below {args.min_free_gb:g} GB", file=out)
        return 3
    if source is None:
        source = MarineCadastreSource(workdir=workdir)
    wanted = set(targets.values())
    home = {label: set() for label in targets}
    anywhere = {label: set() for label in targets}
    by_mmsi = {m: label for label, m in targets.items()}
    read, missing, failed = [], [], []
    for day in utc_days(*window):
        free = _free_gb(workdir)
        if free < args.min_free_gb:
            print(f"stopped: {free:.0f} GB free, below {args.min_free_gb:g} GB", file=out)
            return 3
        try:
            for message in source.history(day, bbox, wanted):
                label = by_mmsi.get(message.mmsi)
                if label is None:
                    continue
                local = datetime.fromtimestamp(message.ts / 1000, timezone.utc).astimezone(zone).date().isoformat()
                if local not in window_days:
                    continue
                anywhere[label].add(local)
                if isinstance(message, AisPosition) and any(p.contains(message.lat, message.lon) for p in ports):
                    home[label].add(local)
            read.append(day.isoformat())
        except DayNotPublished:
            missing.append(day.isoformat())
        except (CorruptDay, MalformedFile) as error:
            failed.append(f"{day.isoformat()} ({type(error).__name__})")
    print("# NAIS transmit check (counts only)", file=out)
    print(f"\nWindow: {first.isoformat()} to {last.isoformat()} ({region.timezone} days, {len(window_days)} days). "
          f"Home ports: {', '.join(port_ids)}. UTC day files read: {len(read)} of {len(read) + len(missing) + len(failed)}.\n", file=out)
    print("| Label | Days heard at home ports | Days heard anywhere in region | Days checked |\n|---|---|---|---|", file=out)
    for label in sorted(targets):
        print(f"| {label} | {len(home[label])} | {len(anywhere[label])} | {len(window_days)} |", file=out)
    print(f"\nMissing (not published): {', '.join(missing) or 'none'}", file=out)
    print(f"Failed: {', '.join(failed) or 'none'}\n", file=out)
    print(NOTE, file=out)
    if args.private_out:
        _write_private(args.private_out, {label: {"home_days": sorted(home[label]), "anywhere_days": sorted(anywhere[label])}
                                          for label in sorted(targets)})
    return 0 if read else 1


if __name__ == "__main__":
    sys.exit(main())
