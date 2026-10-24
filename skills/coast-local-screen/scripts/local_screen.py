#!/usr/bin/env python3
"""COAST tier-1 local screener: every window of one finished window-set plan.

Order is fixed: deterministic checks first (re-hash every ref the run summary
pins, copy producer statistics, derive bounded raster statistics, compare shared
edges with neighbouring windows), then a local text model on each window's stats
line, then a local vision model on a deterministic 256 x 256 hillshade. A model
verdict never overrides a hash mismatch or a pipeline hold; any model reply that
is not "pass" is "flag" (recall over precision). The output is
review/tier1/flagged-windows.json (coast-tier1-screen-v1). It flags; it never
accepts a plan. Tier 3 decides.

Subcommands:
  stats     deterministic checks + hillshade thumbnails -> review/tier1/stats.json
  text      local text model per mapped window          -> review/tier1/text.json
  vision    local vision model per mapped window        -> review/tier1/vision.json
  assemble  combine the three                            -> review/tier1/flagged-windows.json
  all       stats, text, vision, assemble in that order
  fixture-eval  run the text/vision prompts over the bake-off screening fixtures

Local-only: the endpoint must be a loopback http URL; nothing else is opened.
Read-only on the plan directory except the --out directory under review/.
Every output file is written once (O_EXCL); a re-screen uses a new --out.
Needs numpy + rasterio (the checkout's survey venv) for the stats step only.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import base64
import hashlib
import http.client
import json
import math
import os
from pathlib import Path
import re
import stat
import struct
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib

SCHEMA = "coast-tier1-screen-v1"
STATS_SCHEMA = "coast-tier1-stats-v1"
TEXT_SCHEMA = "coast-tier1-text-v1"
VISION_SCHEMA = "coast-tier1-vision-v1"
WINDOW_SCHEMA = "coast-tier1-window-stats-v1"
EVAL_SCHEMA = "coast-tier1-fixture-eval-v1"
CHECKS_VERSION = "coast-local-screen stats v1"
MAX_CELLS = 262_144                  # the acquire stage's window bound
MAX_JSON_BYTES = 64 * 1024 * 1024
MAX_RASTER_BYTES = 256 * 1024 * 1024
THUMB_PX = 256
AZIMUTH_DEG, ALTITUDE_DEG = 315.0, 45.0
DEFAULT_ENDPOINT = "http://127.0.0.1:8003/v1"
DEFAULT_MODEL = "qwen3.8:27b-thinkingcap-q6"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}
# Defaults of skills/coast-campaign-shared/config/tier2-thresholds.json (design 5.4, B1a);
# --thresholds reads that file when it exists. The values in force are recorded in stats.json.
DEFAULT_THRESHOLDS = {"tier1_valid_fraction_min": 0.5, "tier1_edge_valid_min": 0.5,
                      "tier1_slope_p99_max_deg": 60.0, "edge_step_should_m": 2.0}
DETERMINISTIC_FLAGS = ("HASH_MISMATCH", "PLAN_INTEGRITY", "HOLD", "STATE_INCONSISTENT", "NOT_MAPPED",
                       "DERIVED_UNAVAILABLE", "COUNT_MISMATCH", "DEPTH_RANGE_OUT", "VALID_FRACTION_LOW",
                       "EDGE_VALID_LOW", "SLOPE_P99_HIGH", "NEIGHBOUR_STEP")
TEXT_REASONS = ("DEPTH_IMPLAUSIBLE", "VALID_LOW", "HOLES", "EDGE_GAP", "NEIGHBOUR_STEP",
                "SLOPE_SPIKE", "COUNT_MISMATCH", "HOLD", "OTHER")
VISION_ARTEFACTS = ("seam", "stripe", "misalignment", "void", "noise", "other")
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
RUN_NAME = re.compile(r"run-(\d{2,})\.json")
DESIGN_RUN_NAME = re.compile(r"run-summary-(\d{2,})\.json")
HEX = re.compile(r"[0-9a-f]{64}")


class Refused(ValueError):
    """A precondition the screener will not work around (exit 2)."""


# ----------------------------------------------------------------------------- io

def utc(epoch=None):
    return datetime.fromtimestamp(time.time() if epoch is None else epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def _relative(path):
    if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path or "\x00" in path
            or any(p in {"", ".", ".."} for p in path.split("/"))):
        raise Refused(f"confined relative POSIX path required: {path!r}")
    return path


def _no_symlinks(path):
    cursor = Path(path.anchor)
    for part in path.parts[1:]:
        cursor /= part
        if cursor.is_symlink():
            raise Refused(f"symlink in path refused: {cursor}")


def read_bytes(root, relative, limit=MAX_JSON_BYTES):
    """Read a regular file under root without following symlinks; bounded."""
    path = root / _relative(relative)
    _no_symlinks(path)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise Refused(f"regular bounded file required: {relative}")
        return stream.read()


def file_ref(root, path):
    path = Path(path)
    relative = path.relative_to(root).as_posix()
    raw = read_bytes(root, relative, MAX_RASTER_BYTES)
    return {"path": relative, "sha256": sha256(raw), "bytes": len(raw)}


def check_ref(root, ref, limit=MAX_RASTER_BYTES):
    """Return (bytes or None, problem or None) for a {path, sha256, bytes} ref (H1)."""
    if not isinstance(ref, dict) or not HEX.fullmatch(str(ref.get("sha256", ""))) or type(ref.get("bytes")) is not int:
        return None, f"invalid ref: {str(ref)[:160]}"
    try:
        raw = read_bytes(root, ref["path"], limit)
    except (OSError, Refused) as error:
        return None, f"ref unreadable: {ref.get('path')}: {error.__class__.__name__}"
    if len(raw) != ref["bytes"] or sha256(raw) != ref["sha256"]:
        return None, f"ref hash/bytes mismatch: {ref['path']}"
    return raw, None


def write_once(path, raw):
    path = Path(path)
    _no_symlinks(path.parent)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"sha256": sha256(raw), "bytes": len(raw)}


def load_json(raw):
    return json.loads(raw, parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def header(schema, args, author_model):
    env = os.environ.get
    return {"schema": schema, "created_utc": utc(),
            "author_profile": env("COAST_AUTHOR_PROFILE") or "local-worker",
            "author_model": author_model,
            "card_id": env("COAST_CARD_ID") or getattr(args, "card_id", None),
            "code_commit": env("COAST_CODE_COMMIT"), "skill_commit": env("COAST_SKILL_COMMIT")}


# ----------------------------------------------------------------------------- plan

class Plan:
    """The plan directory, its queue root and the run summary to screen."""

    def __init__(self, plan_dir, run_summary=None, out=None):
        plan_dir = Path(plan_dir)
        if not plan_dir.is_absolute() or ".." in plan_dir.parts:
            raise Refused("--plan-dir must be an absolute normalized path")
        _no_symlinks(plan_dir)
        if plan_dir.parent.name != "plans" or not plan_dir.is_dir():
            raise Refused("--plan-dir must be <queue root>/plans/<plan-id>")
        self.dir, self.root, self.plan_id = plan_dir, plan_dir.parent.parent, plan_dir.name
        self.summary_path = Path(run_summary) if run_summary else self._latest()
        if not self.summary_path.is_absolute() or not self.summary_path.is_relative_to(plan_dir):
            raise Refused("--run-summary must be an absolute path inside the plan directory")
        out = Path(out) if out else plan_dir / "review" / "tier1"
        if not out.is_absolute() or ".." in out.parts or not out.is_relative_to(plan_dir / "review"):
            raise Refused("--out must be an absolute directory under <plan-dir>/review/")
        self.out = out
        raw = read_bytes(self.root, self.summary_path.relative_to(self.root).as_posix())
        self.summary_ref = {"path": self.summary_path.relative_to(self.root).as_posix(), "sha256": sha256(raw), "bytes": len(raw)}
        self.summary = load_json(raw)
        if self.summary.get("schema") != "coast-run-summary-v1":
            raise Refused("run summary schema coast-run-summary-v1 required")

    def _latest(self):
        found = []
        runs = self.dir / "runs"
        if runs.is_dir():  # PC-9 bridge_run layout: plans/<plan-id>/runs/run-NN.json
            found = [(int(m.group(1)), runs / p.name) for p in runs.iterdir() if (m := RUN_NAME.fullmatch(p.name))]
        if not found:      # design 3.2 fixture layout: plans/<plan-id>/run-summary-NN.json
            found = [(int(m.group(1)), self.dir / p.name) for p in self.dir.iterdir() if (m := DESIGN_RUN_NAME.fullmatch(p.name))]
        if not found:
            raise Refused("no run summary in the plan directory (runs/run-NN.json)")
        return max(found)[1]

    def tier1_ref(self, name):
        return file_ref(self.root, self.out / name)


def _unknown(value):
    if isinstance(value, dict):
        return {k: _unknown(v) for k, v in value.items()}
    return None if value == "unknown" else value


def normalize(plan):
    """Plan-level problems + one record per window, from either receipt shape.

    The PC-9 shape (bridge_run.py: runs/run-NN.json with ``enqueue`` and per-stage
    ``products``) is primary; the design-3.2 fixture shape (``enqueue_receipt``,
    ``terrain_ref``/``support_ref``/``cells_ref``) is the adapter.
    """
    s, root = plan.summary, plan.root
    problems, integrity, admission, catalog = [], [], None, None
    # PC-9 is the default; only a summary carrying the design-3.2 receipt keys (and none of PC-9's) uses the
    # adapter, so deleting a PC-9 ref can never switch the screener onto the adapter's lighter rules.
    pc9 = any(k in s for k in ("admission", "bridge", "enqueue")) or not any(
        k in s for k in ("bridge_receipt", "enqueue_receipt"))
    required = ("admission", "bridge", "enqueue") if pc9 else ("bridge_receipt", "enqueue_receipt")
    plan_refs = [(name, s.get(name)) for name in required]
    if s.get("continuation_of"):
        plan_refs.append(("continuation_of", s["continuation_of"]))
    checked = []
    for name, ref in plan_refs:
        if ref is None:                      # a required receipt that is absent fails closed, never skipped
            checked.append({"name": name, "path": None, "ok": False})
            problems.append(f"{name}: required ref missing from the run summary")
            integrity.append(f"required ref missing: {name}")
            continue
        raw, problem = check_ref(root, ref, MAX_JSON_BYTES)
        checked.append({"name": name, "path": ref.get("path") if isinstance(ref, dict) else None, "ok": problem is None})
        if problem:
            problems.append(f"{name}: {problem}")
        elif name == "admission":
            admission = load_json(raw)
    if admission is None and not pc9 and (plan.dir / "admission.json").is_file():
        raw = read_bytes(root, (plan.dir / "admission.json").relative_to(root).as_posix())
        admission = load_json(raw)
    if pc9 and admission is not None and not isinstance(admission.get("catalog"), dict):
        integrity.append("admission has no catalog ref")    # DEPTH_RANGE_OUT would silently never fire
    if admission and isinstance(admission.get("catalog"), dict):
        raw, problem = check_ref(root, admission["catalog"], MAX_JSON_BYTES)
        checked.append({"name": "catalog", "path": admission["catalog"].get("path"), "ok": problem is None})
        if problem:
            problems.append(f"catalog: {problem}")
        else:
            catalog = load_json(raw)
    if pc9 and s.get("problems"):
        problems.extend(f"run summary problem: {p}" for p in s["problems"])
    adm_list = [w for w in (admission or {}).get("windows", []) if isinstance(w, dict)]
    adm_windows = {w.get("window_key"): w for w in adm_list}
    if admission is not None and (len(adm_windows) != len(adm_list) or not all(isinstance(k, str) for k in adm_windows)):
        integrity.append("admission windows have duplicate or invalid window_key")
    grids = {g.get("grid_sha256"): g.get("definition") for g in (admission or {}).get("grids", []) if isinstance(g, dict)}
    tiles = {}
    for src in (admission or {}).get("sources", []):
        if isinstance(src, dict) and isinstance(src.get("tiles"), dict):
            tiles[src.get("source_id")] = src["tiles"]
    depth_ranges = {}
    for row in (catalog or {}).get("candidates", []):
        rng = (row.get("metadata") or {}).get("depth_range_m") if isinstance(row, dict) else None
        if isinstance(rng, list) and len(rng) == 2 and all(isinstance(v, (int, float)) for v in rng):
            depth_ranges[row.get("source_id")] = sorted(float(v) for v in rng)
    by_key, order = {}, []
    for w in s.get("windows", []):
        key = w.get("window_key") if isinstance(w, dict) else None
        if not isinstance(key, str):
            problems.append(f"invalid window_key: {key!r}")
            integrity.append("run summary has a window without a valid window_key")
            continue
        if key in by_key:                    # duplicate: keep the first, mark it, never silently drop the key
            problems.append(f"duplicate window_key: {key}")
            integrity.append(f"duplicate window_key in run summary: {key}")
            by_key[key]["integrity"].append("DUPLICATE_IN_RUN_SUMMARY")
            continue
        rec = (_pc9_window if pc9 else _design_window)(w, adm_windows.get(key), grids, tiles)
        rec["integrity"] = []
        by_key[key] = rec
        order.append(key)
    if admission is not None:
        # The admitted population is the review population: every admitted key gets a record, in admission
        # order; admitted keys missing from the run summary are preserved as non-pass, extra keys are kept.
        expected = [k for k in adm_windows if isinstance(k, str)]
        missing = [k for k in expected if k not in by_key]
        extra = [k for k in order if k not in adm_windows]
        for key in missing:
            by_key[key] = _missing_window(key, adm_windows[key])
        for key in extra:
            by_key[key]["integrity"].append("NOT_IN_ADMISSION")
        if missing or extra:
            problems.append(f"run summary windows differ from admission windows: {len(missing)} missing, {len(extra)} extra")
            integrity.extend([f"admitted window missing from run summary: {k}" for k in missing]
                             + [f"run summary window not in admission: {k}" for k in extra])
        observed = order
        order = expected + extra
        if not (missing or extra) and observed != expected:
            problems.append("run summary window order differs from admission order")
    elif pc9:
        integrity.append("admission unavailable: the admitted window population cannot be reconciled")
    windows = []
    for key in order:
        rec = by_key[key]
        rec["expected_depth_range_m"] = depth_ranges.get(rec["source_id"])
        windows.append(rec)
    return {"problems": problems, "integrity_problems": integrity, "plan_refs": checked, "windows": windows,
            "shape": "pc9" if pc9 else "design-3.2-fixture"}


def _missing_window(key, adm):
    """An admitted window the run summary does not report: kept in the population, never a pass."""
    pixel = adm.get("pixel_window")
    window_dir = adm.get("window_dir")
    if not isinstance(window_dir, str) or not HEX.fullmatch(window_dir):
        window_dir = sha256(key.encode())
    return {"window_key": key, "source_id": adm.get("source_id"), "idx": adm.get("idx"), "window_dir": window_dir,
            "state": "missing_from_run_summary", "unfinished_reason": "missing_from_run_summary",
            "stage_states": {}, "holds": [], "refs": [], "terrain_ref": None, "support_ref": None, "cells_ref": None,
            "producer": {}, "grid": adm.get("grid_sha256"),
            "origin": pixel[:2] if isinstance(pixel, list) and len(pixel) == 4 else None, "pixel_window": pixel,
            "integrity": ["MISSING_FROM_RUN_SUMMARY"]}


def _holds(stages):
    out = []
    for name in ("acquire", "qualify", "map", "render"):
        for h in (stages.get(name) or {}).get("holds") or []:
            if h not in out:
                out.append(h)
    return out


def _pc9_window(w, adm, grids, tiles):
    stages = w.get("stages") or {}
    refs = []
    for name in ("acquire", "qualify", "map"):
        info = stages.get(name) or {}
        for label, ref in (("input_manifest", info.get("input_manifest")), ("result", info.get("result_ref"))):
            if ref:
                refs.append((f"{name}.{label}", ref))
        for label, ref in sorted((info.get("products") or {}).items()):
            refs.append((f"{name}.products.{label}", ref))
    m, q = stages.get("map") or {}, stages.get("qualify") or {}
    products = m.get("products") or {}
    support = q.get("support") or {}
    key = w["window_key"]
    grid = (adm or {}).get("grid_sha256")
    pixel = (adm or {}).get("pixel_window")
    window_dir = (adm or {}).get("window_dir")
    if not isinstance(window_dir, str) or not HEX.fullmatch(window_dir):
        window_dir = sha256(key.encode())
    return {"window_key": key, "source_id": w.get("source_id"), "idx": (adm or {}).get("idx"),
            "window_dir": window_dir,
            "state": w.get("state"), "unfinished_reason": w.get("unfinished_reason"),
            "stage_states": {n: (stages.get(n) or {}).get("state") for n in ("acquire", "qualify", "map")},
            "holds": _holds(stages), "refs": refs,
            "terrain_ref": products.get("terrain"), "support_ref": products.get("mask"), "cells_ref": products.get("cells"),
            "producer": {"valid_cells": support.get("valid_cells"), "mask_sha256": support.get("mask_sha256"),
                         "native_valid_count": m.get("native_valid_count"), "depth_m": _unknown(m.get("depth_m"))},
            "grid": grid, "origin": pixel[:2] if isinstance(pixel, list) and len(pixel) == 4 else None,
            "pixel_window": pixel}


def _design_window(w, adm, grids, tiles):
    stages = w.get("stages") or {}
    refs = []
    for name in ("acquire", "qualify", "map"):
        info = stages.get(name) or {}
        for label in ("result_ref", "mapping_input_ref", "run_ref", "cells_ref", "terrain_ref", "support_ref"):
            if info.get(label):
                refs.append((f"{name}.{label}", info[label]))
    m, q = stages.get("map") or {}, stages.get("qualify") or {}
    states = {n: (stages.get(n) or {}).get("state") for n in ("acquire", "qualify", "map")}
    if states["map"] == "done":
        state = "map_done"
    elif "held" in states.values():
        state = "held"
    else:
        state = w.get("terminal_state") if w.get("terminal") else "unfinished"
    idx, origin = w.get("idx"), None
    t = tiles.get(w.get("source_id"))
    if isinstance(idx, int) and t and isinstance(t.get("cols"), int) and t["cols"] > 0:
        origin = [(idx % t["cols"]) * 512, (idx // t["cols"]) * 512]
    return {"window_key": w["window_key"], "source_id": w.get("source_id"), "idx": idx,
            "window_dir": sha256(w["window_key"].encode()), "state": state, "unfinished_reason": None,
            "stage_states": states, "holds": _holds(stages), "refs": refs,
            "terrain_ref": m.get("terrain_ref"), "support_ref": m.get("support_ref"), "cells_ref": m.get("cells_ref"),
            "producer": {"valid_cells": q.get("valid_cells"), "mask_sha256": q.get("mask_sha256"),
                         "native_valid_count": m.get("native_valid_count"), "depth_m": _unknown(m.get("depth_m"))},
            "grid": w.get("source_id") if origin else None, "origin": origin, "pixel_window": None}


# ----------------------------------------------------------------------------- rasters

def _resolution(cells_raw, raster_res):
    """Cell size in metres: the producer's cells.json native_resolution_m, else a projected raster's
    transform; None (-> slope unavailable) when neither is known in metres."""
    if cells_raw is not None:
        try:
            value = load_json(cells_raw).get("native_resolution_m")
        except ValueError:
            value = None
        if isinstance(value, (int, float)) and value > 0:
            return [float(value), float(value)]
        if isinstance(value, list) and len(value) == 2 and all(isinstance(v, (int, float)) and v > 0 for v in value):
            return [float(value[0]), float(value[1])]
    return raster_res


def read_window(terrain_raw, support_raw):
    """Bounded read of the verified bytes (never a path, so what is hashed is what is read)."""
    import numpy as np
    from rasterio.io import MemoryFile
    with MemoryFile(terrain_raw) as mem, mem.open() as ds:
        if ds.width * ds.height > MAX_CELLS:
            raise ValueError(f"terrain exceeds {MAX_CELLS} cells")
        band = ds.read(1, masked=True)
        depth = np.asarray(band.filled(np.nan), dtype="float64")
        terrain_valid = ~np.ma.getmaskarray(band) & np.isfinite(depth)
        projected = ds.crs is not None and ds.crs.is_projected
        res = [abs(ds.transform.a), abs(ds.transform.e)] if projected else None
    with MemoryFile(support_raw) as mem, mem.open() as ds:
        if (ds.height, ds.width) != depth.shape:
            raise ValueError("support raster shape differs from terrain")
        support = ds.read(1) > 0
    return depth, terrain_valid, support, res


def derive(depth, terrain_valid, support, res):
    import numpy as np
    valid = terrain_valid & support
    cells = depth.size
    out = {"cells": int(cells), "valid_cells": int(valid.sum()), "hole_cells": int(cells - valid.sum()),
           "interpolated_cells": 0, "valid_fraction": round(float(valid.sum()) / cells, 6),
           "nodata_fraction": round(1.0 - float(terrain_valid.sum()) / cells, 6),
           "support_terrain_disagreement_cells": int((support & ~terrain_valid).sum())}
    border = np.zeros(depth.shape, bool)
    border[0, :] = border[-1, :] = border[:, 0] = border[:, -1] = True
    out["edge_valid_fraction"] = round(float(valid[border].mean()), 6)
    values = depth[valid]
    if values.size:
        out.update(depth_min_m=round(float(values.min()), 4), depth_max_m=round(float(values.max()), 4),
                   depth_median_m=round(float(np.median(values)), 4),
                   depth_p99_m=round(float(np.percentile(values, 99)), 4))
    else:
        out.update(depth_min_m=None, depth_max_m=None, depth_median_m=None, depth_p99_m=None)
    out["slope_p99_deg"] = None
    if min(depth.shape) >= 3 and values.size and res and res[0] > 0 and res[1] > 0:
        masked = np.where(valid, depth, np.nan)
        gy, gx = np.gradient(masked, res[1], res[0])
        slope = np.degrees(np.arctan(np.hypot(gx, gy)))
        finite = slope[np.isfinite(slope)]
        if finite.size:
            out["slope_p99_deg"] = round(float(np.percentile(finite, 99)), 4)
    unavailable = [k for k in ("depth_median_m", "depth_p99_m", "slope_p99_deg") if out[k] is None]
    out["unavailable_reason"] = ("null: " + ", ".join(unavailable) + " (no valid cells, window < 3x3 or no finite slope)"
                                 if unavailable else None)
    return out, valid


def edge_delta(a, b):
    """Shared-edge depth step between two windows of one grid: median(a - b) over cells valid in both."""
    import numpy as np
    (ax, ay), (bx, by) = a["origin"], b["origin"]
    ah, aw = a["depth"].shape
    bh, bw = b["depth"].shape
    if bx == ax + aw or ax == bx + bw:            # east / west neighbour
        lo, hi = max(ay, by), min(ay + ah, by + bh)
        if hi <= lo:
            return None
        east = bx == ax + aw
        da = a["depth"][lo - ay:hi - ay, aw - 1 if east else 0]
        db = b["depth"][lo - by:hi - by, 0 if east else bw - 1]
        va = a["valid"][lo - ay:hi - ay, aw - 1 if east else 0]
        vb = b["valid"][lo - by:hi - by, 0 if east else bw - 1]
        direction = "E" if east else "W"
    elif by == ay + ah or ay == by + bh:          # south / north neighbour
        lo, hi = max(ax, bx), min(ax + aw, bx + bw)
        if hi <= lo:
            return None
        south = by == ay + ah
        da = a["depth"][ah - 1 if south else 0, lo - ax:hi - ax]
        db = b["depth"][0 if south else bh - 1, lo - bx:hi - bx]
        va = a["valid"][ah - 1 if south else 0, lo - ax:hi - ax]
        vb = b["valid"][0 if south else bh - 1, lo - bx:hi - bx]
        direction = "S" if south else "N"
    else:
        return None
    both = va & vb
    median = round(float(np.median(da[both] - db[both])), 4) if both.any() else None
    return {"window_key": b["window_key"], "direction": direction, "edge_cells": int(both.sum()), "delta_median_m": median}


def hillshade_png(depth, valid, res):
    """256 x 256 RGBA PNG: hillshade (az 315, alt 45, true cell size, elevation = -depth) modulated by a
    linear stretch over the window's own depth range (shallow light, deep dark); nodata transparent;
    nearest-neighbour fit, centred; zlib level 9 and no ancillary chunks, so bytes are deterministic."""
    import numpy as np
    h, w = depth.shape
    res = res or [1.0, 1.0]                             # unknown metric cell size: relief unscaled
    values = depth[valid]
    lo, hi = (float(values.min()), float(values.max())) if values.size else (0.0, 0.0)
    filled = np.where(valid, depth, (lo + hi) / 2.0)
    z = -filled
    if min(h, w) >= 2:
        dz_drow, dz_dcol = np.gradient(z, res[1] or 1.0, res[0] or 1.0)
    else:
        dz_drow = dz_dcol = np.zeros_like(z)
    dzdx, dzdy = dz_dcol, -dz_drow                      # x east, y north (rows run south)
    az, alt = math.radians(AZIMUTH_DEG), math.radians(ALTITUDE_DEG)
    light = (math.sin(az) * math.cos(alt), math.cos(az) * math.cos(alt), math.sin(alt))
    norm = np.sqrt(dzdx ** 2 + dzdy ** 2 + 1.0)
    shade = np.clip((-dzdx * light[0] - dzdy * light[1] + light[2]) / norm, 0.0, 1.0)
    if values.size:                                     # gentle seafloor relief: stretch shade over its p1-p99,
        s_lo, s_hi = np.percentile(shade[valid], [1, 99])   # gain capped at 3 so survey noise is not amplified
        if s_hi - s_lo > 1e-6:
            gain = min(1.0 / (s_hi - s_lo), 3.0)
            mid = (s_lo + s_hi) / 2.0
            shade = np.clip(0.5 + (shade - mid) * gain, 0.0, 1.0)
    stretch = (filled - lo) / (hi - lo) if hi > lo else np.zeros_like(filled)
    gray = np.rint(255.0 * shade * (1.0 - 0.45 * stretch)).astype("uint8")
    alpha = np.where(valid, 255, 0).astype("uint8")
    scale = THUMB_PX / max(h, w)
    th, tw = max(1, min(THUMB_PX, round(h * scale))), max(1, min(THUMB_PX, round(w * scale)))
    rows = np.minimum((np.arange(th) + 0.5) / scale, h - 1).astype(int)
    cols = np.minimum((np.arange(tw) + 0.5) / scale, w - 1).astype(int)
    canvas = np.zeros((THUMB_PX, THUMB_PX, 2), "uint8")
    y0, x0 = (THUMB_PX - th) // 2, (THUMB_PX - tw) // 2
    canvas[y0:y0 + th, x0:x0 + tw, 0] = gray[np.ix_(rows, cols)]
    canvas[y0:y0 + th, x0:x0 + tw, 1] = alpha[np.ix_(rows, cols)]
    return encode_png(canvas.tobytes(), THUMB_PX, THUMB_PX, channels=2)


def encode_png(pixels, width, height, channels=2):
    """Minimal deterministic PNG (8-bit; 2 = gray+alpha, 4 = RGBA), filter 0 per row."""
    color = {1: 0, 2: 4, 3: 2, 4: 6}[channels]
    stride = width * channels
    raw = b"".join(b"\x00" + pixels[y * stride:(y + 1) * stride] for y in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, color, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ----------------------------------------------------------------------------- stats

def load_thresholds(path):
    if not path:
        return dict(DEFAULT_THRESHOLDS), {"source": "builtin-defaults (design 5.4)"}
    raw = Path(path).read_bytes()
    doc = load_json(raw)
    if not isinstance(doc, dict):
        raise Refused(f"{path}: thresholds must be a JSON object")
    # The shared tier2 file also carries tier-2 keys; only a misspelt tier1_* key is unknown here.
    unknown = sorted(k for k in doc if k.startswith("tier1_") and k not in DEFAULT_THRESHOLDS)
    if unknown:
        raise Refused(f"{path}: unknown tier-1 thresholds {unknown}")
    values = dict(DEFAULT_THRESHOLDS)
    for key in DEFAULT_THRESHOLDS:
        if key not in doc:
            continue
        value = doc[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise Refused(f"{path}: threshold {key} must be a finite number, not {value!r}")
        values[key] = float(value)
    return values, {"source": str(path), "sha256": sha256(raw), "bytes": len(raw)}


def cmd_stats(args):
    t0 = time.monotonic()
    plan = Plan(args.plan_dir, args.run_summary, args.out)
    thresholds, threshold_source = load_thresholds(args.thresholds)
    plan.out.mkdir(parents=True, exist_ok=True)
    if (plan.out / "stats.json").exists():
        raise Refused(f"{plan.out / 'stats.json'} exists; use a new --out for a re-screen")
    norm = normalize(plan)
    plan_problem = any(not r["ok"] for r in norm["plan_refs"])
    arrays, results = {}, []
    for rec in norm["windows"]:
        det = {"hash_ok": True, "hash_problems": [], "refs_checked": 0, "state": rec["state"],
               "stage_states": rec["stage_states"], "holds": rec["holds"], "unfinished_reason": rec["unfinished_reason"],
               "producer": rec["producer"], "derived": None, "neighbours": [], "neighbour_delta_median_m": None,
               "neighbour_note": None, "depth_range_plausible": None, "depth_range_reason": "catalog_range_unavailable",
               "integrity": rec["integrity"], "flags": []}
        raws = {}
        for label, ref in rec["refs"]:
            limit = MAX_JSON_BYTES if str(ref.get("path", "")).endswith(".json") else MAX_RASTER_BYTES
            raw, problem = check_ref(plan.root, ref, limit)
            det["refs_checked"] += 1
            if problem:
                det["hash_ok"] = False
                det["hash_problems"].append(f"{label}: {problem}")
            else:
                raws[ref["path"]] = raw
        if plan_problem:
            det["hash_ok"] = False
            det["hash_problems"].append("plan-level receipt problem (see summary.plan_problems)")
        if not det["hash_ok"]:
            det["flags"].append("HASH_MISMATCH")
        if norm["integrity_problems"] or rec.get("integrity"):
            det["flags"].append("PLAN_INTEGRITY")
        held_stage = "held" in (rec["stage_states"] or {}).values()
        held = rec["state"] == "held" or bool(rec["holds"]) or held_stage
        if held:                                   # any hold, held stage or held state: never a pass
            det["flags"].append("HOLD")
        if rec["state"] not in ("held", "map_done"):
            det["flags"].append("NOT_MAPPED")
        unfinished_stage = any(v != "done" for v in (rec["stage_states"] or {}).values())
        if ((rec["state"] == "map_done" and (rec["holds"] or held_stage or unfinished_stage))
                or (rec["state"] == "held" and not rec["holds"])):
            det["flags"].append("STATE_INCONSISTENT")
        thumb = None
        if rec["state"] == "map_done":
            derived = {"from": {"terrain": (rec["terrain_ref"] or {}).get("sha256"),
                                "support": (rec["support_ref"] or {}).get("sha256")}}
            terrain = raws.get((rec["terrain_ref"] or {}).get("path"))
            support = raws.get((rec["support_ref"] or {}).get("path"))
            cells_raw = raws.get((rec["cells_ref"] or {}).get("path"))
            try:
                if terrain is None or support is None:
                    raise ValueError("terrain/support ref missing or failed re-hash")
                depth, terrain_valid, support_mask, res = read_window(terrain, support)
                res = _resolution(cells_raw, res)
                derived["resolution_m"] = res
                stats, valid = derive(depth, terrain_valid, support_mask, res)
                derived.update(stats)
                arrays[rec["window_key"]] = dict(window_key=rec["window_key"], depth=depth, valid=valid,
                                                 origin=rec["origin"], grid=rec["grid"])
                try:
                    png = hillshade_png(depth, valid, res)
                    wdir = plan.out / "windows" / rec["window_dir"]
                    wdir.mkdir(parents=True, exist_ok=True)
                    meta = write_once(wdir / "hillshade.png", png)
                    thumb = dict(path=(wdir / "hillshade.png").relative_to(plan.root).as_posix(), px=THUMB_PX, **meta)
                except Exception as error:  # noqa: BLE001 - a failed render is a flag, never a crash
                    thumb = {"error": f"{error.__class__.__name__}: {str(error)[:160]}"}
            except Exception as error:  # noqa: BLE001 - unreadable raster -> DERIVED_UNAVAILABLE
                derived.update({k: None for k in ("valid_fraction", "nodata_fraction", "edge_valid_fraction",
                                                  "depth_median_m", "depth_p99_m", "slope_p99_deg")})
                derived["unavailable_reason"] = f"{error.__class__.__name__}: {str(error)[:200]}"
            det["derived"] = derived
            _deterministic_rules(det, rec, thresholds)
        results.append({"rec": rec, "det": det, "thumbnail": thumb})
    _neighbours(results, arrays, thresholds)
    windows = []
    for item in results:
        rec, det = item["rec"], item["det"]
        det["flags"] = [f for f in DETERMINISTIC_FLAGS if f in det["flags"]]
        entry = {"window_key": rec["window_key"], "source_id": rec["source_id"], "idx": rec["idx"],
                 "window_dir": rec["window_dir"], "pixel_window": rec["pixel_window"],
                 "expected_depth_range_m": rec["expected_depth_range_m"], "deterministic": det,
                 "thumbnail": item["thumbnail"]}
        if rec["state"] == "map_done" or det["flags"]:
            wdir = plan.out / "windows" / rec["window_dir"]
            wdir.mkdir(parents=True, exist_ok=True)
            write_once(wdir / "stats.json", canonical(dict(schema=WINDOW_SCHEMA, plan_id=plan.plan_id, **entry)))
            entry["stats_file"] = file_ref(plan.root, wdir / "stats.json")
        windows.append(entry)
    doc = dict(header(STATS_SCHEMA, args, None), plan_id=plan.plan_id, plan_sha256=plan.summary.get("plan_sha256"),
               run_summary=plan.summary_ref, receipt_shape=norm["shape"], deterministic_checks_version=CHECKS_VERSION,
               thresholds=thresholds, thresholds_source=threshold_source, plan_problems=norm["problems"],
               plan_integrity_problems=norm["integrity_problems"],
               plan_refs=norm["plan_refs"], windows=windows, wall_s=round(time.monotonic() - t0, 3))
    meta = write_once(plan.out / "stats.json", canonical(doc))
    flagged = sum(bool(w["deterministic"]["flags"]) for w in windows)
    print(json.dumps({"stats": str(plan.out / "stats.json"), **meta, "windows": len(windows),
                      "deterministic_flagged": flagged, "plan_problems": len(norm["problems"])}, sort_keys=True))
    return 0


def _deterministic_rules(det, rec, thresholds):
    d, p, flags = det["derived"], rec["producer"], det["flags"]
    required = ("valid_fraction", "edge_valid_fraction", "depth_median_m", "depth_p99_m", "slope_p99_deg")
    if any(d.get(k) is None for k in required):
        flags.append("DERIVED_UNAVAILABLE")      # a null statistic never satisfies a pass rule
        return
    if p.get("native_valid_count") is not None and p["native_valid_count"] != d["valid_cells"]:
        flags.append("COUNT_MISMATCH")
    if p.get("valid_cells") is not None and p["valid_cells"] != d["valid_cells"]:
        flags.append("COUNT_MISMATCH")
    if d["valid_fraction"] < thresholds["tier1_valid_fraction_min"]:
        flags.append("VALID_FRACTION_LOW")
    if d["edge_valid_fraction"] < thresholds["tier1_edge_valid_min"]:
        flags.append("EDGE_VALID_LOW")
    if d["slope_p99_deg"] > thresholds["tier1_slope_p99_max_deg"]:
        flags.append("SLOPE_P99_HIGH")
    rng = rec["expected_depth_range_m"]
    if rng:
        tol = 0.05 * max(rng[1] - rng[0], abs(rng[1]), 1.0)
        det["depth_range_plausible"] = bool(rng[0] - tol <= d["depth_min_m"] and d["depth_max_m"] <= rng[1] + tol)
        det["depth_range_reason"] = "catalog depth_range_m +- 5 %"
        if not det["depth_range_plausible"]:
            flags.append("DEPTH_RANGE_OUT")


def _neighbours(results, arrays, thresholds):
    for item in results:
        rec, det = item["rec"], item["det"]
        if rec["state"] != "map_done":
            continue
        if rec["origin"] is None or rec["grid"] is None:
            det["neighbour_note"] = "neighbours: none (no tile geometry in the receipts)"
            continue
        same = [o for o in results if o is not item and o["rec"]["grid"] == rec["grid"] and o["rec"]["origin"] is not None]
        mine = arrays.get(rec["window_key"])
        compared = []
        for other in same:
            theirs = arrays.get(other["rec"]["window_key"])
            if mine is None or theirs is None:
                continue
            delta = edge_delta(mine, theirs)
            if delta:
                compared.append(delta)
        det["neighbours"] = sorted(compared, key=lambda d: d["window_key"])
        steps = [d["delta_median_m"] for d in compared if d["delta_median_m"] is not None]
        if steps:
            det["neighbour_delta_median_m"] = max(steps, key=abs)
            if abs(det["neighbour_delta_median_m"]) > thresholds["edge_step_should_m"]:
                det["flags"].append("NEIGHBOUR_STEP")
        det["neighbour_note"] = (None if steps else
                                 "neighbours: none" if not compared else "neighbours: no shared valid edge cells")


# ----------------------------------------------------------------------------- models

def check_endpoint(endpoint):
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme != "http" or parsed.hostname not in LOOPBACK:
        raise Refused(f"local-only: endpoint must be http on loopback ({sorted(LOOPBACK)}), got {endpoint!r}")
    return endpoint.rstrip("/")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow a redirect, even to loopback: a validated local endpoint must not lead anywhere else."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused(f"local-only: HTTP {code} redirect refused (to {str(newurl)[:160]!r})")


def _opener():
    """No proxies, no redirects; only the default http handler (loopback URLs checked by the callers)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


def _post(url, body, timeout):
    """The only model call: loopback JSON POST (tests replace this function)."""
    check_endpoint(url)
    request = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with _opener().open(request, timeout=timeout) as response:
        return json.loads(response.read())


def _get(url, timeout):
    check_endpoint(url)
    with _opener().open(url, timeout=timeout) as response:
        return json.loads(response.read())


class Client:
    def __init__(self, endpoint, model, *, timeout, retries, retry_wait, max_tokens):
        self.endpoint, self.model = check_endpoint(endpoint), model
        self.timeout, self.retries, self.retry_wait, self.max_tokens = timeout, retries, retry_wait, max_tokens
        self.down = threading.Event()
        self.fingerprints = set()

    def model_tag(self):
        try:
            listing = _get(self.endpoint + "/models", self.timeout)
            ids = [m.get("id") for m in listing.get("data", []) if isinstance(m, dict)]
            return ",".join(i for i in ids if i) or None
        except Exception:  # noqa: BLE001
            return None

    def chat(self, content):
        if self.down.is_set():
            return {"error": "ENDPOINT_UNAVAILABLE"}
        body = {"model": self.model, "messages": [{"role": "user", "content": content}],
                "max_tokens": self.max_tokens, "temperature": 0}
        last = None
        for attempt in range(self.retries + 1):
            if attempt:
                time.sleep(self.retry_wait)
            t0 = time.monotonic()
            try:
                reply = _post(self.endpoint + "/chat/completions", body, self.timeout)
            except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, ValueError) as error:
                # HTTPException covers IncompleteRead: a truncated body is a failed attempt, never a reply.
                last = f"{error.__class__.__name__}: {str(error)[:160]}"
                continue
            latency = round(time.monotonic() - t0, 3)
            if reply.get("system_fingerprint"):
                self.fingerprints.add(reply["system_fingerprint"])
            choice = (reply.get("choices") or [{}])[0]
            text = (choice.get("message") or {}).get("content")
            usage = reply.get("usage") or {}
            return {"content": text if isinstance(text, str) else "", "latency_s": latency,
                    "tokens_in": usage.get("prompt_tokens"), "tokens_out": usage.get("completion_tokens"),
                    "finish_reason": choice.get("finish_reason"), "attempts": attempt + 1}
        self.down.set()
        return {"error": "ENDPOINT_UNAVAILABLE", "detail": last}


THINK = re.compile(r"<think>.*?</think>", re.S | re.I)
PASS_LINE = re.compile(r"pass\.?", re.I)
FLAG_LINE = re.compile(r"flag\.?", re.I)


def parse_reply(content, vocabulary, *, upper, finish_reason=None):
    """(verdict, found, raw, reply_format). 'pass' only for a complete reply whose whole answer is the
    single line `pass` (prompt contract); everything else - contradictions, extra lines, an unclosed
    think block, a truncated completion - is 'flag' (recall first). reply_format records why."""
    text = THINK.sub("", content or "")
    if re.search(r"</think>", text, re.I) and not re.search(r"<think>", text, re.I):
        text = re.split(r"</think>", text, flags=re.I)[-1]   # server stripped the opening tag
    text = text.strip()
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if finish_reason not in (None, "stop"):
        fmt = "truncated"
    elif re.search(r"</?think>", text, re.I):
        fmt = "malformed"
    elif len(lines) == 1 and PASS_LINE.fullmatch(lines[0]):
        fmt = "pass"
    elif lines and FLAG_LINE.fullmatch(lines[0]) and len(lines) <= 2 and not any(
            re.search(r"\bpass\b", line, re.I) for line in lines[1:]):
        fmt = "flag"
    else:
        fmt = "malformed"
    verdict = "pass" if fmt == "pass" else "flag"
    found = []
    for word in re.findall(r"[A-Za-z_]+", text):
        token = word.upper() if upper else word.lower()
        if token in vocabulary and token not in found:
            found.append(token)
    if verdict == "flag" and not found:
        found = ["OTHER" if upper else "other"]
    return verdict, (found[:3] if upper else found), text[:2000], fmt


def prompt(name):
    raw = (PROMPTS / f"{name}.md").read_bytes()
    return raw.decode(), sha256(raw)


def stats_line(window):
    """The compact per-window facts the text model sees (no paths, no hashes)."""
    det = window["deterministic"]
    d = det.get("derived") or {}
    p = det.get("producer") or {}
    return {"window_key": window["window_key"], "state": det["state"], "holds": det["holds"],
            "cells_total": d.get("cells"), "valid_cells": d.get("valid_cells"), "hole_cells": d.get("hole_cells"),
            "interpolated_cells": d.get("interpolated_cells"), "valid_fraction": d.get("valid_fraction"),
            "nodata_fraction": d.get("nodata_fraction"), "edge_valid_fraction": d.get("edge_valid_fraction"),
            "producer_valid_cells": p.get("valid_cells"), "producer_native_valid_count": p.get("native_valid_count"),
            "depth_m_positive_down": {"min": d.get("depth_min_m"), "median": d.get("depth_median_m"),
                                      "p99": d.get("depth_p99_m"), "max": d.get("depth_max_m"),
                                      "producer": p.get("depth_m")},
            "expected_depth_range_m": window.get("expected_depth_range_m"),
            "slope_p99_deg": d.get("slope_p99_deg"),
            "neighbour_delta_median_m": {n["direction"]: n["delta_median_m"] for n in det.get("neighbours", [])},
            "deterministic_flags": det["flags"]}


def _load_stats(plan):
    ref = plan.tier1_ref("stats.json")
    raw, problem = check_ref(plan.root, ref, MAX_JSON_BYTES)
    if problem:
        raise Refused(problem)
    stats = load_json(raw)
    if stats.get("schema") != STATS_SCHEMA or stats.get("run_summary") != plan.summary_ref:
        raise Refused("stats.json does not pin this run summary; run `stats` first with the same --out")
    return stats, ref


def _screen(args, kind):
    t0 = time.monotonic()
    plan = Plan(args.plan_dir, args.run_summary, args.out)
    target = plan.out / f"{kind}.json"
    if target.exists():
        raise Refused(f"{target} exists; use a new --out for a re-screen")
    stats, stats_ref = _load_stats(plan)
    client = Client(args.endpoint, args.model, timeout=args.timeout, retries=args.retries,
                    retry_wait=args.retry_wait, max_tokens=args.max_tokens)
    template, prompt_sha = prompt(kind)
    todo = [w for w in stats["windows"] if w["deterministic"]["state"] == "map_done"]

    def one(window):
        if kind == "text":
            content = template.replace("{stats}", json.dumps(stats_line(window), sort_keys=True))
            reply = client.chat(content)
        else:
            thumb = window.get("thumbnail") or {}
            if not thumb.get("path"):
                return window["window_key"], {"verdict": "flag", "artefacts": ["other"], "error": "THUMBNAIL_UNAVAILABLE",
                                              "latency_s": None, "tokens_in": None, "tokens_out": None, "raw": None}
            png, problem = check_ref(plan.root, thumb, MAX_JSON_BYTES)
            if problem or png is None:
                return window["window_key"], {"verdict": "flag", "artefacts": ["other"], "error": "THUMBNAIL_HASH_MISMATCH",
                                              "latency_s": None, "tokens_in": None, "tokens_out": None, "raw": None}
            reply = client.chat([{"type": "text", "text": template},
                                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}])
        label = "reasons" if kind == "text" else "artefacts"
        if "error" in reply:
            out = {"verdict": None, "error": reply["error"], "detail": reply.get("detail"),
                   "latency_s": None, "tokens_in": None, "tokens_out": None, "raw": None, label: []}
        else:
            verdict, found, raw, fmt = parse_reply(reply["content"], TEXT_REASONS if kind == "text" else VISION_ARTEFACTS,
                                                   upper=kind == "text", finish_reason=reply["finish_reason"])
            out = {"verdict": verdict, "latency_s": reply["latency_s"], "tokens_in": reply["tokens_in"],
                   "tokens_out": reply["tokens_out"], "finish_reason": reply["finish_reason"], "raw": raw, "error": None,
                   "reply_format": fmt, label: [] if verdict == "pass" else found}
        return window["window_key"], out

    with ThreadPoolExecutor(max_workers=max(1, args.slots)) as pool:
        verdicts = dict(pool.map(one, todo))
    doc = dict(header(TEXT_SCHEMA if kind == "text" else VISION_SCHEMA, args, args.model),
               plan_id=plan.plan_id, plan_sha256=stats.get("plan_sha256"), run_summary=plan.summary_ref, stats=stats_ref,
               screener={"endpoint": client.endpoint, "model_alias": args.model, "model_tag": client.model_tag(),
                         "system_fingerprints": sorted(client.fingerprints), "prompt_sha256": prompt_sha,
                         "thinking_budget": args.thinking_budget, "max_tokens": args.max_tokens,
                         "slots": max(1, args.slots), "timeout_s": args.timeout, "retries": args.retries},
               endpoint_unavailable=client.down.is_set(), windows=verdicts, wall_s=round(time.monotonic() - t0, 3))
    meta = write_once(target, canonical(doc))
    flagged = sum(v["verdict"] != "pass" for v in verdicts.values())
    print(json.dumps({kind: str(target), **meta, "screened": len(verdicts), "flagged": flagged,
                      "endpoint_unavailable": client.down.is_set()}, sort_keys=True))
    return 0


def cmd_text(args):
    return _screen(args, "text")


def cmd_vision(args):
    return _screen(args, "vision")


# ----------------------------------------------------------------------------- assemble

def cmd_assemble(args):
    t0 = time.monotonic()
    plan = Plan(args.plan_dir, args.run_summary, args.out)
    target = plan.out / "flagged-windows.json"
    if target.exists():
        raise Refused(f"{target} exists; use a new --out for a re-screen")
    stats, stats_ref = _load_stats(plan)
    models = {}
    for kind in ("text", "vision"):
        ref = plan.tier1_ref(f"{kind}.json")
        raw, problem = check_ref(plan.root, ref, MAX_JSON_BYTES)
        if problem:
            raise Refused(problem)
        doc = load_json(raw)
        if doc.get("stats") != stats_ref:
            raise Refused(f"{kind}.json does not pin the current stats.json")
        models[kind] = (doc, ref)
    text, vision = models["text"][0], models["vision"][0]
    if text["screener"]["model_alias"] != vision["screener"]["model_alias"]:
        model_alias = text["screener"]["model_alias"] + "+" + vision["screener"]["model_alias"]
    else:
        model_alias = text["screener"]["model_alias"]
    endpoint_down = text["endpoint_unavailable"] or vision["endpoint_unavailable"]
    windows, counts = [], dict(windows=0, pass_=0, flag=0, held=0, hash_mismatches=0, deterministic_flags=0,
                               text_flags=0, vision_flags=0, derived_unavailable=0)
    tokens_in = tokens_out = 0
    for w in stats["windows"]:
        det = w["deterministic"]
        key = w["window_key"]
        mapped = det["state"] == "map_done"
        t = text["windows"].get(key) if mapped else None
        v = vision["windows"].get(key) if mapped else None
        text_model = None if t is None else {"verdict": t["verdict"], "reasons": t.get("reasons") or [],
                                             "tokens_in": t["tokens_in"], "tokens_out": t["tokens_out"],
                                             "latency_s": t["latency_s"], "error": t.get("error"), "raw": t.get("raw"),
                                             "reply_format": t.get("reply_format")}
        vision_model = None if v is None else {"thumbnail": w.get("thumbnail"), "verdict": v["verdict"],
                                               "artefacts": v.get("artefacts") or [], "tokens_in": v["tokens_in"],
                                               "tokens_out": v["tokens_out"], "latency_s": v["latency_s"],
                                               "error": v.get("error"), "raw": v.get("raw"),
                                               "reply_format": v.get("reply_format")}
        reasons = list(det["flags"])
        if mapped and (text_model is None or text_model["verdict"] != "pass"):
            reasons.append("TEXT_" + ("UNAVAILABLE" if text_model is None or text_model["verdict"] is None else "FLAG"))
        if mapped and (vision_model is None or vision_model["verdict"] != "pass"):
            reasons.append("VISION_" + ("UNAVAILABLE" if vision_model is None or vision_model["verdict"] is None else "FLAG"))
        # Fixed precedence: a hash mismatch is a flag whatever else; a held window is reported, not screened;
        # a hold on any stage, a plan integrity problem or any deterministic or model flag -> flag;
        # pass only when there is no hold and all three passed.
        if "HASH_MISMATCH" in det["flags"]:
            tier1 = "flag"
        elif det["state"] == "held":
            tier1 = "held"
        elif reasons or det["holds"] or "HOLD" in det["flags"]:
            tier1 = "flag"
        else:
            tier1 = "pass"
        counts["windows"] += 1
        counts["pass_" if tier1 == "pass" else tier1] += 1
        counts["hash_mismatches"] += "HASH_MISMATCH" in det["flags"]
        counts["deterministic_flags"] += bool(set(det["flags"]) - {"HOLD"})
        counts["text_flags"] += bool(text_model and text_model["verdict"] == "flag")
        counts["vision_flags"] += bool(vision_model and vision_model["verdict"] == "flag")
        counts["derived_unavailable"] += "DERIVED_UNAVAILABLE" in det["flags"]
        for m in (text_model, vision_model):
            tokens_in += (m or {}).get("tokens_in") or 0
            tokens_out += (m or {}).get("tokens_out") or 0
        windows.append({"window_key": key, "source_id": w["source_id"], "idx": w["idx"], "window_dir": w["window_dir"],
                        "deterministic": det, "stats_file": w.get("stats_file"), "text_model": text_model,
                        "vision_model": vision_model, "tier1": tier1, "tier1_reasons": reasons})
    plan_flags = []
    if not counts["windows"]:
        plan_flags.append("EMPTY_POPULATION")      # nothing screened is never a clean screen
    if endpoint_down:
        plan_flags.append("ENDPOINT_UNAVAILABLE")
    if stats["plan_problems"]:
        plan_flags.append("PLAN_RECEIPT_PROBLEM")
    integrity_problems = stats.get("plan_integrity_problems", ["stats.json predates plan integrity checks"])
    if integrity_problems:
        plan_flags.append("PLAN_INTEGRITY")
    must = sorted(w["window_key"] for w in windows if w["tier1"] in {"flag", "held"})
    summary = {"windows": counts["windows"], "pass": counts["pass_"], "flag": counts["flag"], "held": counts["held"],
               "hash_mismatches": counts["hash_mismatches"], "deterministic_flags": counts["deterministic_flags"],
               "text_flags": counts["text_flags"], "vision_flags": counts["vision_flags"],
               "derived_unavailable": counts["derived_unavailable"], "flags": plan_flags,
               "plan_problems": stats["plan_problems"], "plan_integrity_problems": integrity_problems,
               "wall_s": round(stats["wall_s"] + text["wall_s"] + vision["wall_s"] + time.monotonic() - t0, 3),
               "stage_wall_s": {"stats": stats["wall_s"], "text": text["wall_s"], "vision": vision["wall_s"]},
               "slots_used": max(text["screener"]["slots"], vision["screener"]["slots"]),
               "tokens_in": tokens_in, "tokens_out": tokens_out,
               "must_examine": must,
               "must_examine_note": "every flag and held window_key; the V- (tier 3) review must examine all of them "
                                    "in addition to its random sample"}
    doc = dict(header(SCHEMA, args, model_alias), plan_id=plan.plan_id, plan_sha256=stats.get("plan_sha256"),
               run_summary=plan.summary_ref, receipt_shape=stats["receipt_shape"],
               inputs={"stats": stats_ref, "text": models["text"][1], "vision": models["vision"][1]},
               screener={"endpoint": text["screener"]["endpoint"], "model_alias": model_alias,
                         "model_tag": text["screener"]["model_tag"] or vision["screener"]["model_tag"],
                         "system_fingerprints": sorted(set(text["screener"]["system_fingerprints"])
                                                       | set(vision["screener"]["system_fingerprints"])),
                         "prompt_sha256": {"text": text["screener"]["prompt_sha256"],
                                           "vision": vision["screener"]["prompt_sha256"]},
                         "thinking_budget": text["screener"]["thinking_budget"],
                         "slots": summary["slots_used"]},
               deterministic_checks_version=stats["deterministic_checks_version"], thresholds=stats["thresholds"],
               thresholds_source=stats["thresholds_source"], review_required=True, accepted=False,
               windows=windows, summary=summary)
    meta = write_once(target, canonical(doc))
    print(json.dumps({"flagged_windows": str(target), **meta, "windows": summary["windows"], "flag": summary["flag"],
                      "held": summary["held"], "pass": summary["pass"], "hash_mismatches": summary["hash_mismatches"],
                      "derived_unavailable": summary["derived_unavailable"], "flags": plan_flags,
                      "must_examine": len(must)}, sort_keys=True))
    return 0


def cmd_all(args):
    for step in (cmd_stats, cmd_text, cmd_vision, cmd_assemble):
        step(args)
    return 0


# ----------------------------------------------------------------------------- fixture eval

def _fixture_line(receipt):
    """Adapter: bake-off screen_text receipt -> the stats line shape the text prompt expects."""
    counts = receipt.get("counts") or {}
    total = receipt.get("cells_total")
    band = receipt.get("expected_band") or {}
    depth = receipt.get("depth_m") or {}
    valid = counts.get("valid")

    def down(v):
        return None if v is None else round(-float(v), 4)    # fixture depths are elevations (negative down)
    # The real lane has no interpolation and holes = cells without valid support, so the fixture's
    # hole + fill cells both count as holes; producer and derived counts are the same receipt value.
    return {"window_key": receipt.get("window_id"), "state": "map_done" if receipt.get("status") != "held" else "held",
            "holds": receipt.get("hold_reasons") or [], "cells_total": total, "valid_cells": valid,
            "hole_cells": total - valid if total is not None and valid is not None else None, "interpolated_cells": 0,
            "producer_valid_cells": valid, "producer_native_valid_count": valid,
            "valid_fraction": round(valid / total, 6) if valid is not None and total else None,
            "depth_m_positive_down": {"min": down(depth.get("max")), "median": down(depth.get("median")),
                                      "max": down(depth.get("min"))},
            "expected_depth_range_m": sorted(v for v in (down(band.get("shallow_m")), down(band.get("deep_m"))) if v is not None) or None,
            "slope_p95_deg": receipt.get("slope_p95_deg"),
            "neighbour_delta_median_m": receipt.get("neighbour_delta_m") or {}, "deterministic_flags": []}


def _confusion(rows):
    tp = sum(r["gold"] and r["verdict"] != "pass" for r in rows)
    fp = sum(not r["gold"] and r["verdict"] != "pass" for r in rows)
    fn = sum(r["gold"] and r["verdict"] == "pass" for r in rows)
    tn = sum(not r["gold"] and r["verdict"] == "pass" for r in rows)
    recall = tp / (tp + fn) if tp + fn else None
    precision = tp / (tp + fp) if tp + fp else None
    f2 = (5 * precision * recall / (4 * precision + recall)) if precision and recall else None
    lat = sorted(r["latency_s"] for r in rows if r["latency_s"] is not None)
    p95 = lat[min(len(lat) - 1, math.ceil(0.95 * len(lat)) - 1)] if lat else None
    return {"n": len(rows), "tp": tp, "fp": fp, "fn": fn, "tn": tn, "recall": recall, "precision": precision,
            "f2": f2, "latency_p95_s": p95, "errors": sum(r["verdict"] is None for r in rows)}


def cmd_fixture_eval(args):
    out = Path(args.out)
    if not out.is_absolute() or out.exists():
        raise Refused("--out must be an absolute path that does not exist")
    client = Client(args.endpoint, args.model, timeout=args.timeout, retries=args.retries,
                    retry_wait=args.retry_wait, max_tokens=args.max_tokens)
    report = dict(header(EVAL_SCHEMA, args, args.model), screener={"endpoint": client.endpoint, "model_alias": args.model,
                  "slots": max(1, args.slots)}, suites={})
    if args.text_fixtures:
        template, psha = prompt("text")
        items = json.loads(Path(args.text_fixtures).read_text())

        def one_text(item):
            reply = client.chat(template.replace("{stats}", json.dumps(_fixture_line(item["receipt"]), sort_keys=True)))
            verdict = (parse_reply(reply.get("content"), TEXT_REASONS, upper=True, finish_reason=reply.get("finish_reason"))
                       if "error" not in reply else (None, [], None, None))
            return {"id": item["id"], "gold": bool(item["gold"]["flag"]), "gold_type": item["gold"].get("type"),
                    "verdict": verdict[0], "reasons": verdict[1], "reply_format": verdict[3],
                    "latency_s": reply.get("latency_s")}
        with ThreadPoolExecutor(max_workers=max(1, args.slots)) as pool:
            rows = list(pool.map(one_text, items))
        report["suites"]["text"] = {"fixtures": str(args.text_fixtures), "prompt_sha256": psha,
                                    "metrics": _confusion(rows), "rows": rows}
    if args.vision_fixtures:
        template, psha = prompt("vision")
        items = json.loads(Path(args.vision_fixtures).read_text())

        def one_vision(item):
            png = Path(item["image"]).read_bytes()
            if item.get("image_sha256") and sha256(png) != item["image_sha256"]:
                return {"id": item["id"], "gold": bool(item["gold"]["flag"]), "verdict": None, "artefacts": [],
                        "latency_s": None, "error": "fixture image sha256 mismatch"}
            reply = client.chat([{"type": "text", "text": template},
                                 {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}])
            verdict = (parse_reply(reply.get("content"), VISION_ARTEFACTS, upper=False, finish_reason=reply.get("finish_reason"))
                       if "error" not in reply else (None, [], None, None))
            return {"id": item["id"], "gold": bool(item["gold"]["flag"]), "gold_type": item["gold"].get("type"),
                    "natural_feature": item["gold"].get("natural_feature"), "verdict": verdict[0],
                    "artefacts": verdict[1], "reply_format": verdict[3], "latency_s": reply.get("latency_s")}
        with ThreadPoolExecutor(max_workers=max(1, args.slots)) as pool:
            rows = list(pool.map(one_vision, items))
        report["suites"]["vision"] = {"fixtures": str(args.vision_fixtures), "prompt_sha256": psha,
                                      "metrics": _confusion(rows), "rows": rows}
    report["screener"]["model_tag"] = client.model_tag()
    report["screener"]["system_fingerprints"] = sorted(client.fingerprints)
    report["endpoint_unavailable"] = client.down.is_set()
    meta = write_once(out, canonical(report))
    print(json.dumps({"fixture_eval": str(out), **meta,
                      **{k: v["metrics"] for k, v in report["suites"].items()}}, sort_keys=True))
    return 0


# ----------------------------------------------------------- canonical round mode

REQUIRED_MEASUREMENTS = ("valid_fraction", "depth_median_m", "depth_p99_m",
                         "nodata_fraction", "edge_valid_fraction", "slope_p99_deg")
CANONICAL_VERSION = "coast-tier1-canonical-v1"


def _shared_review():
    # Script-local dependency, never imported by product code. Legacy mode does
    # not import the shared/GIS validation stack until canonical mode is selected.
    import importlib.util
    name = "review_common"
    if name not in sys.modules:
        path = Path(__file__).resolve().parents[2] / "coast-sign-off/scripts/review_common.py"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise Refused("shared review helper unavailable")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def _metadata(path):
    """Only CLI-selected deployment metadata is read before root resolution."""
    common = _shared_review()
    path = common.absolute(str(path))
    with common.directory_fd(path.parent) as fd:
        leaf = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        with os.fdopen(leaf, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > common.LIMIT:
                raise Refused("bounded regular root metadata required")
            return common.loads(stream.read(common.LIMIT + 1))


def _round_write(resolver, path, raw):
    """Create only admitted descendants via no-follow directory descriptors."""
    common = _shared_review()
    root_id, relative = common.location(resolver, path)
    parts = relative.split("/")
    with common.directory_fd(resolver.bindings[root_id]) as root:
        fd = os.dup(root)
        try:
            for part in parts[:-1]:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = child
            leaf = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
            with os.fdopen(leaf, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
        finally:
            os.close(fd)
    ref = dict(root_id=root_id, path=relative, sha256=sha256(raw), bytes=len(raw))
    resolver.read(ref)
    return ref


class Round:
    """Explicit immutable context; no glob, latest lookup or producer rewrite."""

    def __init__(self, roots, context_path):
        self.common = c = _shared_review()
        # Launcher-supplied actual runtime, not the requested endpoint alias;
        # checked before any write or model call so no mode runs unattributed.
        self.provenance = {}
        for field in ("author_profile", "author_model", "card_id", "code_commit", "skill_commit"):
            supplied = os.environ.get("COAST_" + field.upper())
            if not supplied:
                raise Refused("actual screener provenance required: COAST_" + field.upper())
            self.provenance[field] = supplied
        self._derived = None
        bindings = _metadata(roots)  # operator-selected bindings, not a receipt
        self.resolver = c.Resolver(bindings, allowed_root_ids=bindings)
        self.context_ref = c.pin(self.resolver, context_path)
        self.context = c.trusted_context(self.resolver, self.context_ref)
        if self.context["mode"] != "normal":
            raise Refused("diagnostic context requires corrective integrity review, not screening")
        c.GraphValidator(self.resolver).reference(self.context_ref, contract="coast-review-context-v1")
        self.queue_id = "queue:" + self.context["campaign_segment_id"]
        self.admission = self.doc(self.context["admission"])
        self.run = self.doc(self.context["run"])
        if self.run["schema"] != "coast-run-summary-v2":
            raise Refused("hash-bound coast_receipt_versions v2 run required")
        self.legacy = self.doc(self.run["legacy_run"])
        self.thresholds = self.doc(self.context["thresholds"])
        self.catalog = self.doc(self.admission["catalog"])
        self.windows = self.admission["windows"]
        self.cells = {w["window_key"]: w for w in self.run["window_cells"]}
        self.native = {w["window_key"]: w for w in self.legacy["windows"]}
        if set(self.cells) != {w["window_key"] for w in self.windows}:
            raise Refused("run/admission window population mismatch")
        self.directory = (self.resolver.bindings[self.queue_id] / "plans" / self.context["plan_id"] /
                          "review" / f"r{self.context['review_round']:02d}" / f"a{self.context['attempt']:02d}" / "tier1")

    def doc(self, ref):
        return self.common.document(self.resolver, ref)

    def derived(self):
        """Stats re-derived from the pinned inputs; a supplied stats file is a claim, not proof."""
        if self._derived is None:
            self._derived = _derive_stats(self)
        return self._derived

    def read(self, path):
        ref = self.common.pin(self.resolver, path)
        return self.doc(ref), ref

    def output_path(self, path, name):
        if path != self.directory / name:
            raise Refused("output must use its immutable plan/round/attempt address")
        _no_symlinks(path)
        if path.exists():
            raise Refused("output exists; prepare a new attempt")

    def write(self, path, value):
        return _round_write(self.resolver, path, canonical(value))

    def base(self, kind):
        value = self.common.review_base(kind, self.context, self.context_ref, None)
        value.update(self.provenance)
        value["created_utc"] = utc()
        return value


def _measurement(status, value=None, reason=None, inputs=()):
    return dict(status=status, value=value, reason=reason, inputs=list(inputs), method_version=CANONICAL_VERSION)


def _flag(key, code, detail, evidence=()):
    return dict(window_key=key, severity="must", code=code, detail=detail, evidence=list(evidence))


def _adjacent(a, b):
    if a["source_id"] != b["source_id"] or a["grid_sha256"] != b["grid_sha256"]:
        return False
    ax, ay, aw, ah = a["pixel_window"]
    bx, by, bw, bh = b["pixel_window"]
    return ((ax + aw == bx or bx + bw == ax) and max(ay, by) < min(ay + ah, by + bh) or
            (ay + ah == by or by + bh == ay) and max(ax, bx) < min(ax + aw, bx + bw))


def _canonical_stats(round_, args):
    r = round_
    r.output_path(args.out, "stats.json")
    if args.thumbnail_dir != r.directory / "windows":
        raise Refused("thumbnail directory must belong to this round/attempt")
    _no_symlinks(args.thumbnail_dir)
    for window in r.windows:
        thumb_path = args.thumbnail_dir / window["window_dir"] / "hillshade.png"
        _no_symlinks(thumb_path)
        if thumb_path.exists():
            raise FileExistsError("partial attempt thumbnail exists; prepare a new attempt")
    # Every check runs on the complete in-memory result before the first write.
    doc, thumbnails = r.derived()
    _validate_intermediate(doc, "stats")
    for path, (expected, png) in thumbnails.items():
        if _round_write(r.resolver, path, png) != expected:
            raise Refused("thumbnail write differs from its derivation")
    return doc


def _derive_stats(round_):
    """Pure: no writes. Returns the stats document and the thumbnails it references."""
    r = round_
    rows, arrays, thumbnails = [], {}, {}
    for window in r.windows:
        key = window["window_key"]
        cell, native = r.cells[key], r.native[key]
        state, producer = cell["state"], cell["producer"]
        held = state == "held" or any(s.get("holds") or s.get("state") == "held" for s in native["stages"].values())
        entry = dict(window_key=key, stage_state=state, status="held" if held else "unavailable",
                     producer_fields=[], measurements={}, text_response=None, vision_response=None,
                     text_verdict="not_mapped", vision_verdict="not_mapped", thumbnail=None, flags=[])
        rows.append(dict(window_key=key, producer=producer, entry=entry))
        if held:
            entry["flags"].append(_flag(key, "HOLD", "pipeline hold; never quality acceptance"))
        for name in (*REQUIRED_MEASUREMENTS, "neighbour_delta", "catalog_range"):
            entry["measurements"][name] = _measurement("not_applicable", reason="pipeline_not_mapped")
        if producer is not None:
            cells = r.doc(producer)
            for name in ("count", "min", "max", "mean", "p80"):
                entry["producer_fields"].append(dict(field_path="depth_m." + name, source=producer,
                                                      value=cells.get("depth_m", {}).get(name)))
        if state != "map_done":
            if not held:
                entry["flags"].append(_flag(key, "NOT_MAPPED", state))
            continue
        entry["status"] = "flag" if producer is not None else "unavailable"
        entry["text_verdict"] = entry["vision_verdict"] = "unavailable"
        inputs = [] if producer is None else [producer]
        catalog_row = next((v for v in r.catalog.get("candidates", []) if v.get("source_id") == window["source_id"]), {})
        depth_range = catalog_row.get("metadata", {}).get("depth_range_m")
        try:
            from coast_receipt_versions import typed
            if producer is None:
                raise Refused("mapped window has no bound cells producer")
            if depth_range is not None:
                if not isinstance(depth_range, list) or len(depth_range) != 2 or not all(type(v) in (int, float) for v in depth_range):
                    raise Refused("invalid stated catalog depth range")
                depth_range = sorted(depth_range)
            products = native["stages"]["map"]["products"]
            terrain, support = typed(products["terrain"]), typed(products["mask"])
            inputs += [terrain, support]
            if max(terrain["bytes"], support["bytes"]) > MAX_RASTER_BYTES:
                raise Refused("raster byte bound exceeded")
            depth, terrain_valid, mask, res = read_window(r.resolver.read(terrain), r.resolver.read(support))
            res = _resolution(r.resolver.read(producer) if producer else None, res)
            derived, valid = derive(depth, terrain_valid, mask, res)
            png = hillshade_png(depth, valid, res)
            thumb_path = r.directory / "windows" / window["window_dir"] / "hillshade.png"
            root_id, relative = r.common.location(r.resolver, thumb_path)
            thumbnail = dict(root_id=root_id, path=relative, sha256=sha256(png), bytes=len(png))
            # Commit window evidence only after every input check above passed.
            arrays[key] = dict(window_key=key, depth=depth, valid=valid, origin=window["pixel_window"][:2])
            thumbnails[thumb_path] = (thumbnail, png)
            entry["thumbnail"] = thumbnail
            for name in REQUIRED_MEASUREMENTS:
                value = derived[name]
                entry["measurements"][name] = (_measurement("measured", value, inputs=inputs) if value is not None else
                    _measurement("unavailable", reason=derived["unavailable_reason"] or "derivation unavailable", inputs=inputs))
            rec = dict(producer=dict(native_valid_count=cell["native_valid_count"]), expected_depth_range_m=depth_range)
            det = dict(derived=derived, flags=[], depth_range_plausible=None)
            _deterministic_rules(det, rec, r.thresholds)
            for code in det["flags"]:
                entry["flags"].append(_flag(key, code, "deterministic raster check", inputs))
            entry["measurements"]["catalog_range"] = (
                _measurement("not_applicable", reason="catalog_range_absent") if depth_range is None else
                _measurement("unavailable", reason="catalog_range_not_evaluated", inputs=inputs) if det["depth_range_plausible"] is None else
                _measurement("measured", int(det["depth_range_plausible"]), inputs=[*inputs, r.admission["catalog"]]))
        except (ValueError, OSError, KeyError, TypeError) as error:
            for name in REQUIRED_MEASUREMENTS:
                entry["measurements"][name] = _measurement("unavailable", reason=str(error), inputs=inputs)
            entry["measurements"]["catalog_range"] = (_measurement("not_applicable", reason="catalog_range_absent") if depth_range is None else
                                                      _measurement("unavailable", reason="raster_unavailable", inputs=inputs))
        if any(entry["measurements"][name]["status"] == "unavailable" for name in REQUIRED_MEASUREMENTS):
            if not any(f["code"] == "DERIVED_UNAVAILABLE" for f in entry["flags"]):
                entry["flags"].append(_flag(key, "DERIVED_UNAVAILABLE", "required raster measurement unavailable", inputs))
    for window, row in zip(r.windows, rows, strict=True):
        entry, key = row["entry"], row["window_key"]
        if entry["stage_state"] != "map_done":
            continue
        neighbours = [w for w in r.windows if w != window and _adjacent(window, w)]
        inputs = [] if row["producer"] is None else [row["producer"]]
        deltas = []
        for other in neighbours:
            theirs = arrays.get(other["window_key"])
            mine = arrays.get(key)
            if mine is not None and theirs is not None:
                delta = edge_delta(mine, theirs)
                if delta is not None and delta["delta_median_m"] is not None:
                    deltas.append(delta["delta_median_m"])
                    inputs.append(r.cells[other["window_key"]]["producer"])
        if not neighbours:
            measurement = _measurement("not_applicable", reason="no_geometric_neighbours")
        elif len(deltas) != len(neighbours):
            measurement = _measurement("unavailable", reason="expected_neighbour_evidence_unavailable", inputs=inputs)
            entry["flags"].append(_flag(key, "DERIVED_UNAVAILABLE", "expected neighbour unavailable", inputs))
        else:
            value = max(deltas, key=abs)
            measurement = _measurement("measured", value, inputs=inputs)
            if abs(value) > r.thresholds["edge_step_should_m"]:
                entry["flags"].append(_flag(key, "NEIGHBOUR_STEP", "shared-edge median exceeds pinned threshold", inputs))
        entry["measurements"]["neighbour_delta"] = measurement
    return dict(schema=CANONICAL_VERSION, mode="stats", context=r.context_ref, run=r.context["run"],
                thresholds=r.context["thresholds"], windows=rows), thumbnails


def _validate_intermediate(doc, mode):
    """B2-owned shape; no invented fields in the shared Tier1 contract."""
    keys = {"schema", "mode", "context", "run", "windows"}
    keys |= {"thresholds"} if mode == "stats" else {"stats", "telemetry"}
    if not isinstance(doc, dict) or set(doc) != keys or doc["schema"] != CANONICAL_VERSION or doc["mode"] != mode:
        raise Refused("invalid canonical intermediate shape")
    if not isinstance(doc["windows"], list):
        raise Refused("canonical windows must be an ordered list")
    from jsonschema import Draft202012Validator
    shared = Path(__file__).resolve().parents[2] / "coast-campaign-shared/schemas/coast-tier1-screen-v1.schema.json"
    definition = load_json(shared.read_bytes())
    entry_schema = Draft202012Validator(definition["properties"]["windows"]["items"])
    ref_schema = Draft202012Validator(definition["properties"]["run"])
    for name in ("context", "run", "thresholds" if mode == "stats" else "stats"):
        if list(ref_schema.iter_errors(doc[name])):
            raise Refused("invalid intermediate Ref: " + name)
    if mode != "stats" and list(Draft202012Validator(definition["properties"]["telemetry"]).iter_errors(doc["telemetry"])):
        raise Refused("invalid intermediate telemetry")
    for row in doc["windows"]:
        expected = {"window_key", "producer", "entry"} if mode == "stats" else {"window_key", "producer", "response", "verdict", "error"}
        if not isinstance(row, dict) or set(row) != expected or not isinstance(row["window_key"], str):
            raise Refused("invalid canonical window shape")
        if row["producer"] is not None and list(ref_schema.iter_errors(row["producer"])):
            raise Refused("invalid intermediate producer Ref")
        if mode == "stats":
            if list(entry_schema.iter_errors(row["entry"])):
                raise Refused("invalid canonical stats entry")
        elif (row["verdict"] not in ("pass", "flag", "not_mapped", "unavailable") or
              row["error"] is not None and not isinstance(row["error"], str) or
              row["response"] is not None and list(ref_schema.iter_errors(row["response"]))):
            raise Refused("invalid canonical model entry")


def _bind_stats_window(position, row, window, cell, round_):
    """One deciding gate for positional identity and producer binding, all modes."""
    key, producer = window["window_key"], cell["producer"]
    if row is None or row["window_key"] != key or row["producer"] != producer:
        return [key]
    entry = row.get("entry")
    if entry is not None:
        if entry["window_key"] != key or entry["stage_state"] != cell["state"]:
            return [key]
        if producer is None:
            if entry["producer_fields"] or entry["status"] not in ("held", "unavailable"):
                return [key]
        else:
            fields = round_.doc(producer).get("depth_m", {})
            expected_fields = [dict(field_path="depth_m." + name, source=producer, value=fields.get(name))
                               for name in ("count", "min", "max", "mean", "p80")]
            if entry["producer_fields"] != expected_fields:
                return [key]
            if any(m["status"] == "measured" and producer not in m["inputs"] for m in entry["measurements"].values()):
                return [key]
        derived = round_.derived()[0]["windows"]
        if position >= len(derived) or entry != derived[position]["entry"]:
            return [key]  # measurements, flags or thumbnail differ from what the pinned inputs give
        thumb = entry["thumbnail"]
        if thumb is not None:
            expected = (round_.directory / "windows" / window["window_dir"] / "hillshade.png").relative_to(
                round_.resolver.bindings[round_.queue_id]).as_posix()
            if thumb["root_id"] != round_.queue_id or thumb["path"] != expected:
                return [key]
            round_.resolver.read(thumb)
    if entry is None and cell["state"] == "map_done" and row["response"] is None:
        return [key]
    if entry is None and cell["state"] != "map_done" and (row["response"] is not None or row["verdict"] != "not_mapped"):
        return [key]
    response = row.get("response")
    if response is not None:
        value = round_.doc(response)
        if (value["window_key"] != key or value["producer"] != producer or
                value["context"] != round_.context_ref or value["verdict"] != row["verdict"] or value["error"] != row["error"]):
            return [key]
    return []


def _bound_intermediate(round_, path, mode, stats_ref=None):
    r = round_
    doc, ref = r.read(path)
    _validate_intermediate(doc, mode)
    if doc["context"] != r.context_ref or doc["run"] != r.context["run"]:
        raise Refused("intermediate context/run pin mismatch")
    if mode == "stats" and doc["thresholds"] != r.context["thresholds"]:
        raise Refused("intermediate threshold pin mismatch")
    if mode != "stats" and doc["stats"] != stats_ref:
        raise Refused("model response stats pin mismatch")
    problems = []
    for i, window in enumerate(r.windows):
        row = doc["windows"][i] if i < len(doc["windows"]) else None
        problems.extend(_bind_stats_window(i, row, window, r.cells[window["window_key"]], r))
    if len(doc["windows"]) > len(r.windows):
        problems += [row["window_key"] for row in doc["windows"][len(r.windows):]]
    if problems:
        raise Refused("WINDOW_BINDING: " + ", ".join(problems))
    if mode != "stats":
        for row in doc["windows"]:
            if row["response"] is None:
                continue
            response = r.doc(row["response"])
            if response["stats"] != doc["stats"] or response["prompt"] not in r.context["prompts"]:
                raise Refused("response input binding mismatch")
            raw = response["raw"]
            expected = "unavailable" if raw.get("error") else parse_reply(
                raw.get("content"), TEXT_REASONS if mode == "text" else VISION_ARTEFACTS,
                upper=mode == "text", finish_reason=raw.get("finish_reason"))[0]
            if row["verdict"] != expected or row["error"] != raw.get("error"):
                raise Refused("response verdict differs from retained reply")
    return doc, ref


def _canonical_screen(r, args):
    kind = args.command
    r.output_path(args.out, kind + ".json")
    stats, stats_ref = _bound_intermediate(r, args.stats, "stats")
    if args.slots < 1:
        raise Refused("slots must be positive and card-admitted")
    for window in r.windows:
        path = r.directory / "windows" / window["window_dir"] / (kind + "-response.txt")
        _no_symlinks(path)
        if path.exists():
            raise Refused("partial response exists; prepare a new attempt")
    client = Client(args.endpoint, args.model, timeout=60, retries=1, retry_wait=0, max_tokens=1024)
    prompts = [ref for ref in r.context["prompts"] if Path(ref["path"]).name == kind + ".md"]
    if len(prompts) != 1:
        raise Refused("context must pin exactly one " + kind + ".md prompt")
    template = r.resolver.read(prompts[0]).decode()
    started = time.monotonic()

    def chat(content):
        try:
            return client.chat(content)
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as error:
            return dict(error="MALFORMED_RESPONSE", detail=f"{type(error).__name__}: {error}")

    def one(row):
        key, entry = row["window_key"], row["entry"]
        result = dict(window_key=key, producer=row["producer"], response=None, verdict="not_mapped", error=None)
        if entry["stage_state"] != "map_done":
            return result
        if kind == "text":
            content = template.replace("{stats}", json.dumps(entry, sort_keys=True))
            reply = chat(content)
        elif entry["thumbnail"] is None:
            reply = dict(error="THUMBNAIL_UNAVAILABLE")
        else:
            png = r.resolver.read(entry["thumbnail"])
            content = [{"type": "text", "text": template},
                       {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(png).decode()}}]
            reply = chat(content)
        verdict = "unavailable"
        if "error" not in reply:
            verdict = parse_reply(reply["content"], TEXT_REASONS if kind == "text" else VISION_ARTEFACTS,
                                  upper=kind == "text", finish_reason=reply["finish_reason"])[0]
        value = dict(window_key=key, producer=row["producer"], context=r.context_ref, stats=stats_ref,
                     verdict=verdict, error=reply.get("error"), raw=reply, endpoint=client.endpoint,
                     model=args.model, prompt=prompts[0])
        response = r.write(r.directory / "windows" / sha256(key.encode()) / (kind + "-response.txt"), value)
        return dict(result, response=response, verdict=verdict, error=reply.get("error"))

    # Sequential consumption caps an unavailable endpoint at TWO attempts for
    # the whole mode. slots records the admitted ceiling, not a new concurrency grant.
    results = [one(row) for row in stats["windows"]]
    tokens = []
    for row in results:
        if row["response"] is not None:
            raw = r.doc(row["response"])["raw"]
            tokens.extend([raw.get("tokens_in"), raw.get("tokens_out")])
    telemetry = dict(wall_s=round(time.monotonic() - started, 6),
                     tokens=sum(tokens) if tokens and all(type(n) is int and n >= 0 for n in tokens) else None,
                     endpoint=client.endpoint, model=args.model, prompt_sha256=prompts[0]["sha256"], slots=args.slots)
    return dict(schema=CANONICAL_VERSION, mode=kind, context=r.context_ref, run=r.context["run"],
                stats=stats_ref, windows=results, telemetry=telemetry)


def _canonical_assemble(r, args):
    import copy
    r.output_path(args.out, "flagged-windows.json")
    stats, stats_ref = _bound_intermediate(r, args.stats, "stats")
    text, text_ref = _bound_intermediate(r, args.text, "text", stats_ref)
    vision, vision_ref = _bound_intermediate(r, args.vision, "vision", stats_ref)
    windows = []
    for row, tx, vi in zip(stats["windows"], text["windows"], vision["windows"], strict=True):
        entry = copy.deepcopy(row["entry"])
        if entry["stage_state"] == "map_done":
            unavailable = any(entry["measurements"][name]["status"] != "measured" for name in REQUIRED_MEASUREMENTS)
            unavailable |= entry["measurements"]["neighbour_delta"]["status"] == "unavailable"
            if unavailable and not any(f["code"] == "DERIVED_UNAVAILABLE" for f in entry["flags"]):
                entry["flags"].append(_flag(entry["window_key"], "DERIVED_UNAVAILABLE", "required evidence incomplete"))
        for kind, result in (("text", tx), ("vision", vi)):
            entry[kind + "_response"] = result["response"]
            entry[kind + "_verdict"] = result["verdict"]
            if entry["stage_state"] == "map_done" and result["verdict"] != "pass":
                entry["flags"].append(_flag(entry["window_key"], result["error"] or kind.upper() + "_FLAG",
                                             kind + " assessment is not pass", [result["response"]] if result["response"] else []))
        if entry["stage_state"] == "map_done":
            entry["status"] = "unavailable" if row["producer"] is None else "flag" if entry["flags"] else "pass"
        windows.append(entry)
    telemetry = dict(vision["telemetry"])
    telemetry["wall_s"] += text["telemetry"]["wall_s"]
    a, b = text["telemetry"]["tokens"], vision["telemetry"]["tokens"]
    telemetry["tokens"] = a + b if a is not None and b is not None else None
    # Shared schema has one model/endpoint/prompt slot: identify both precisely
    # in the pinned per-window envelopes, never claim one alias ran both modes.
    telemetry["model"] = json.dumps(dict(text=text["telemetry"]["model"], vision=vision["telemetry"]["model"]), sort_keys=True)
    telemetry["endpoint"] = json.dumps(dict(text=text["telemetry"]["endpoint"], vision=vision["telemetry"]["endpoint"]), sort_keys=True)
    telemetry["prompt_sha256"] = sha256(canonical(dict(text=text["telemetry"]["prompt_sha256"], vision=vision["telemetry"]["prompt_sha256"])))
    counts = {"pass_count" if state == "pass" else state: sum(w["status"] == state for w in windows)
              for state in ("pass", "flag", "held", "unavailable")}
    doc = dict(r.base("tier1-screen"), run=r.context["run"], windows=windows, counts=counts, telemetry=telemetry)
    r.common.validate(doc, r.resolver, root_id=r.queue_id)
    return doc


def canonical_main(argv):
    c = _shared_review()
    parser = argparse.ArgumentParser(description="Immutable round-addressed Tier1 adapter")
    parser.add_argument("command", choices=("stats", "text", "vision", "assemble"))
    for name in ("roots", "context", "out"):
        parser.add_argument("--" + name, required=True, type=c.absolute)
    for name in ("stats", "text", "vision", "thumbnail-dir"):
        parser.add_argument("--" + name, type=c.absolute)
    parser.add_argument("--endpoint")
    parser.add_argument("--model")
    parser.add_argument("--slots", type=int)
    args = parser.parse_args(argv)
    try:
        required = {"stats": ("thumbnail_dir",), "text": ("stats", "endpoint", "model", "slots"),
                    "vision": ("stats", "endpoint", "model", "slots"), "assemble": ("stats", "text", "vision")}[args.command]
        if any(getattr(args, key) is None for key in required):
            raise Refused("explicit mode inputs required: " + ", ".join(required))
        r = Round(args.roots, args.context)
        doc = (_canonical_stats(r, args) if args.command == "stats" else
               _canonical_assemble(r, args) if args.command == "assemble" else _canonical_screen(r, args))
        if args.command != "assemble":
            _validate_intermediate(doc, args.command)
        ref = r.write(args.out, doc)
        print(json.dumps(dict(output=ref, windows=len(doc["windows"])), sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps(dict(schema="coast-local-screen-error-v1", command=args.command, error=str(error))), file=sys.stderr)
        return 2


# ----------------------------------------------------------------------------- cli

def parser():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    def model_flags(p):
        p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="loopback OpenAI-compatible base URL")
        p.add_argument("--model", default=DEFAULT_MODEL, help="model alias sent to the endpoint and recorded")
        p.add_argument("--slots", type=int, default=1, help="parallel requests (1 today; 3-4 after the operator raises the cap)")
        p.add_argument("--timeout", type=float, default=300.0)
        p.add_argument("--retries", type=int, default=2, help="retries per call before ENDPOINT_UNAVAILABLE")
        p.add_argument("--retry-wait", type=float, default=60.0)
        p.add_argument("--max-tokens", type=int, default=1024)
        p.add_argument("--thinking-budget", type=int, default=512, help="the server's --reasoning-budget (recorded only)")

    for name in ("stats", "text", "vision", "assemble", "all"):
        p = sub.add_parser(name)
        p.add_argument("--plan-dir", required=True, type=Path, help="absolute $COAST_ROOT/<seg>/plans/<plan-id>")
        p.add_argument("--run-summary", type=Path, help="absolute run summary (default: latest runs/run-NN.json)")
        p.add_argument("--out", type=Path, help="absolute output dir under <plan-dir>/review/ (default review/tier1)")
        p.add_argument("--card-id")
        if name in ("stats", "all"):
            p.add_argument("--thresholds", type=Path, help="tier2-thresholds.json (default: built-in design 5.4 values)")
        if name in ("text", "vision", "all"):
            model_flags(p)
    p = sub.add_parser("fixture-eval")
    p.add_argument("--text-fixtures", type=Path)
    p.add_argument("--vision-fixtures", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--card-id")
    model_flags(p)
    return ap


COMMANDS = {"stats": cmd_stats, "text": cmd_text, "vision": cmd_vision, "assemble": cmd_assemble, "all": cmd_all,
            "fixture-eval": cmd_fixture_eval}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if any(arg == "--roots" or arg.startswith("--roots=") or arg == "--context" or arg.startswith("--context=") for arg in argv):
        return canonical_main(argv)
    args = parser().parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (Refused, OSError, ValueError, KeyError) as error:
        print(json.dumps({"schema": "coast-local-screen-error-v1", "command": args.command,
                          "error": f"{error.__class__.__name__}: {error}"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
