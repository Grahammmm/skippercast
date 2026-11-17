#!/usr/bin/env python3
"""Roll per-sector relief receipts into one 0-300 ft coverage table (offline, stdlib only).

Reads <sector>/mosaic/manifest.json (band_0_300ft, SCMAP-02) and <sector>/coverage.json
(detail_coverage sidecar, SCMAP-01). Sources overlap, so per-tier figures are never summed.
"""
import argparse
import json
import sys
from pathlib import Path

LIMIT_M = 91.44
CELL_KM2 = 100 / 1e6  # 10 m mosaic cells
NOTE = ("Sources overlap: per-source values are not additive and the 'best' columns show the "
        "largest single source, never a sum. Cells are nominal 0-300 ft cover, not habitat grade "
        "or measured survey.")


class Refused(Exception):
    pass


def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise Refused(f"cannot read {path.name}: {exc}")


def need(obj, key, where):
    if not isinstance(obj, dict) or key not in obj:
        raise Refused(f"{where} missing key {key}")
    return obj[key]


def sector_row(directory):
    sector = directory.name
    try:
        manifest = load(directory / "mosaic" / "manifest.json")
        cov = load(directory / "coverage.json")
        band = need(manifest, "band_0_300ft", "manifest.json")
        limits = (need(band, "limit_m", "band_0_300ft"), need(cov, "limit_m", "coverage.json"))
        if any(x != LIMIT_M for x in limits):
            raise Refused(f"limit_m {limits} is not {LIMIT_M}; mixed bands are refused")
        ids = {str(s["code"]): s["id"] for s in need(manifest, "sources", "manifest.json")}
        cells = need(band, "contributor_cells", "band_0_300ft")
        by_source = {ids[str(code)]: round(int(n) * CELL_KM2, 4) for code, n in cells.items()}
        tiers = {"le_2m_km2": [], "5m_km2": []}
        for item in need(cov, "native", "coverage.json"):
            tier = "le_2m_km2" if item["resolution_m"] <= 2 else "5m_km2"
            tiers[tier].append({"id": item["id"], "km2": item["km2"]})
        native = {k: {"sources": v, "max": max((x["km2"] for x in v), default=0.0)}
                  for k, v in tiers.items()}
        return {"sector": sector, "background_km2": need(band, "km2", "band_0_300ft"),
                "background_by_source": by_source, "native": native}
    except Refused as exc:
        raise Refused(f"{sector}: {exc}")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise Refused(f"{sector}: malformed input ({type(exc).__name__}: {exc})")


def markdown(rows):
    out = ["| Sector | Background 0-300 ft km² | Best <=2 m source km² | Best 5 m source km² | Sources |",
           "| --- | --- | --- | --- | --- |"]
    for r in rows:
        names = sorted(r["background_by_source"]) + sorted(
            x["id"] for t in r["native"].values() for x in t["sources"])
        out.append(f"| {r['sector']} | {r['background_km2']} | {r['native']['le_2m_km2']['max']} "
                   f"| {r['native']['5m_km2']['max']} | {', '.join(names)} |")
    return "\n".join(out) + "\n\n" + NOTE + "\n"


def write_atomic(path, text):
    part = path.with_name(path.name + ".part")
    part.write_text(text)
    part.replace(path)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sector", action="append", required=True, type=Path)
    ap.add_argument("--out-json", required=True, type=Path)
    ap.add_argument("--out-md", required=True, type=Path)
    args = ap.parse_args(argv)
    try:
        rows = sorted((sector_row(d) for d in args.sector), key=lambda r: r["sector"])
    except Refused as exc:
        print(f"relief_coverage: {exc}", file=sys.stderr)
        return 2
    doc = {"schema": "relief-coverage/1", "limit_m": LIMIT_M, "note": NOTE, "sectors": rows}
    write_atomic(args.out_json, json.dumps(doc, indent=2, sort_keys=True) + "\n")
    write_atomic(args.out_md, markdown(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
