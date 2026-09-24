"""Audit original CSUMB SCC bathymetry/terrain grids without promoting fishing points.

The reviewed archive is distributed by NOAA NCEI, but CSUMB produced the survey.
Only exact hash-pinned originals are opened. This script deliberately has no path
to a target catalog or waypoint exporter.
"""

import argparse
import hashlib
import io
import json
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
import rasterio


ROOT = Path(__file__).resolve().parents[1]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def metadata_text(zipped, grid, tag):
    root = ElementTree.fromstring(zipped.read(f"{grid}/metadata.xml"))
    values = [" ".join("".join(node.itertext()).split()) for node in root.iter()
              if node.tag.rsplit("}", 1)[-1].lower() == tag]
    return values[0] if values else ""


def inspect_zip(data, grid, kind):
    with zipfile.ZipFile(io.BytesIO(data)) as archive, tempfile.TemporaryDirectory() as tmp:
        prefix = grid.split("/")[0] + "/"
        for item in archive.infolist():
            name = Path(item.filename)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe archive path")
            if item.filename.startswith(prefix) and not item.is_dir():
                target = Path(tmp) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(item))
        with rasterio.open(Path(tmp) / grid) as dataset:
            values = dataset.read(1, masked=True).compressed()
            if values.size == 0:
                raise ValueError("Grid has no measured cells")
            result = {
                "grid": grid,
                "crs": str(dataset.crs),
                "resolution_m": list(dataset.res),
                "bounds_native": list(dataset.bounds),
                "valid_cells": int(values.size),
                "minimum": float(values.min()),
                "maximum": float(values.max()),
            }
            if kind == "habitat":
                codes, counts = np.unique(values, return_counts=True)
                result["class_counts"] = {str(int(code)): int(count) for code, count in zip(codes, counts)}
        result["process_description"] = metadata_text(archive, grid, "procdesc")
        result["horizontal_accuracy_text"] = metadata_text(archive, grid, "horizpar")
        result["vertical_accuracy_text"] = metadata_text(archive, grid, "vertaccr")
        return result


def audit(spec, cache):
    archive_path = cache / (spec["survey_id"] + "_additional_products.tar.gz")
    if archive_path.stat().st_size != spec["archive_bytes"]:
        raise ValueError("Source archive byte count changed")
    if file_digest(archive_path) != spec["archive_sha256"]:
        raise ValueError("Source archive digest changed")
    with tarfile.open(archive_path, "r:gz") as bundle:
        grids = {}
        for kind in ("bathymetry", "habitat"):
            member = spec[kind + "_member"]
            raw = bundle.extractfile(member).read()
            if digest(raw) != spec[kind + "_member_sha256"]:
                raise ValueError(f"{kind} member digest changed")
            grids[kind] = inspect_zip(raw, spec[kind + "_grid"], kind)
    bathy, habitat = grids["bathymetry"], grids["habitat"]
    if bathy["crs"] != habitat["crs"] or bathy["bounds_native"] != habitat["bounds_native"]:
        raise ValueError("Native bathymetry and terrain classification do not align")
    if spec["native_vertical_datum"].lower() not in bathy["process_description"].lower():
        raise ValueError("Declared native vertical datum missing from original metadata")
    if "Rough and smooth habitat" not in habitat["process_description"]:
        raise ValueError("Unexpected habitat-class semantics")
    return {
        "source_id": spec["id"], "producer": spec["producer"],
        "archive_url": spec["archive_url"], "documentation_url": spec["documentation_url"],
        "archive_sha256": spec["archive_sha256"], "native_vertical_datum": spec["native_vertical_datum"],
        "status": "held-from-fishing-targets", "reason": spec["limitations"],
        "bathymetry": bathy, "terrain_habitat": habitat,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "catalog/csumb-scc-native-sources.json")
    parser.add_argument("--cache", type=Path, default=ROOT / "var/noaa-native-cache")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/data/csumb-scc-native-source-review.json")
    args = parser.parse_args()
    sources = json.loads(args.manifest.read_text())["sources"]
    result = {"schema_version": 1, "scope": "original-csumb-scc-native-grid-review",
              "reviewed_at": datetime.now(timezone.utc).isoformat(),
              "publication_status": "source-evidence-only", "sources": [audit(s, args.cache) for s in sources]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".partial")
    temporary.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    temporary.replace(args.output)
    print(json.dumps({"sources": len(result["sources"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
