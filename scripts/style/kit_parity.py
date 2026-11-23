#!/usr/bin/env python3
"""Private kit parity for the nearshore engine against a substrate-off kit oracle (MSK-3).

    kit_parity.py --kit <kit style-guide dir> --out-root <OUT>/_style --kit-python <kit venv python>
                  [--files-manifest kit-v1.0.0.FILES.sha256] [--kit-zip <kit zip>] [--version V]

Runs on AgentOrange only; nothing from the kit is committed or published.

A. ``bash reference/selftest.sh <kit python>`` must print ``SELFTEST OK`` (the private reference
   reproduces the kit goldens in this venv).
B. Every kit file this run opens (reference code, tokens, the case DEMs and pier lines, the xres
   DEMs) must equal its row in the kit's FILES manifest; the kit zip must equal the index pin.
   Class rasters are never opened here, nor by the engine.
C. The oracle: the kit's ``skn_render.py`` with exactly the selftest arguments minus ``--class``,
   per case, into ``<out-root>/oracle/<oracle key>/<case>/`` with ``oracle.json`` (sha256 of every
   file). An existing oracle is verified byte for byte, never regenerated; a missing or changed
   byte is a failure.
D. The engine renders the same grids (base only); the kit's ``compare.py case`` compares base and
   piles with the oracle (``acceptance.base`` / ``acceptance.piles``) and ``compare.py xres`` runs
   over the engine's renders of the xres trio.

Writes ``<out-root>/parity/<parity key>/parity.json`` deterministically (sorted keys, no times or
paths of this run) and ``timing.json`` beside it. Exit 0 only when every check passes.
"""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np  # noqa: E402

from skippercast import style  # noqa: E402
from skippercast.relief import nearshore  # noqa: E402
from skippercast.style import parity  # noqa: E402
import png8  # noqa: E402

XRES = {1: "dem_1m.tif", 2: "dem_2m.tif", 4: "dem_4m.tif"}
ORACLE_FILES = ("base.png", "pile_mask.png", "piles.geojson")  # what compare.py case reads
RUNTIME_PROBE = ("import json, platform, numpy, scipy, PIL, matplotlib, rasterio, pyproj, skimage;"
                 "print(json.dumps({'python': platform.python_version(), 'numpy': numpy.__version__,"
                 "'scipy': scipy.__version__, 'pillow': PIL.__version__, 'matplotlib': matplotlib.__version__,"
                 "'rasterio': rasterio.__version__, 'gdal': rasterio.__gdal_version__, 'pyproj': pyproj.__version__,"
                 "'scikit-image': skimage.__version__}, sort_keys=True))")


class ParityError(Exception):
    pass


def sha(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def dump(value):
    return json.dumps(value, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


def selftest_cases(selftest):
    """{case: args} from the selftest's ``r ...`` render lines, ``--class`` dropped, ``--out`` cut."""
    cases = {}
    for line in selftest.read_text(encoding="utf-8").splitlines():
        if not line.startswith("r $FX/"):
            continue
        words = shlex.split(line)[1:]
        out = words.index("--out")
        case = words[out + 1].removeprefix("$OUT/")
        args = words[:out] + words[out + 2:]
        if "--class" in args:
            at = args.index("--class")
            args = args[:at] + args[at + 2:]
        if any("class" in word for word in args):
            raise ParityError(f"{case}: a class raster is still in the oracle arguments")
        cases[case] = args
    if len(cases) != 5:
        raise ParityError(f"expected the five selftest cases, found {sorted(cases)}")
    return cases


def manifest_rows(path):
    rows = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        digest, name = line.split(None, 1)
        rows[name.strip()] = digest
    return rows


def verify_kit_files(kit, rows, relative):
    """[{path, sha256}] after checking every file against its manifest row (refuse on any miss)."""
    base = kit.parent.parent
    records = []
    for rel in relative:
        path = kit / rel
        key = "./" + path.relative_to(base).as_posix()
        if "class" in rel:
            raise ParityError(f"refusing to open a class raster: {rel}")
        if key not in rows:
            raise ParityError(f"{rel}: no row in the FILES manifest")
        actual = sha(path)
        if actual != rows[key]:
            raise ParityError(f"{rel}: sha256 {actual} != manifest {rows[key]}")
        records.append({"path": rel, "sha256": actual})
    return records


def run_selftest(kit, kit_python, work):
    work.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TMPDIR=str(work))
    proc = subprocess.run(["bash", str(kit / "reference/selftest.sh"), kit_python], capture_output=True,
                          text=True, env=env, timeout=3600)
    lines = [re.sub(r" \(/[^)]*\)$", "", line) for line in proc.stdout.splitlines()]
    ok = proc.returncode == 0 and "SELFTEST OK" in lines
    return {"ok": ok, "exit": proc.returncode, "lines": lines}


def kit_runtime(kit_python):
    proc = subprocess.run([kit_python, "-c", RUNTIME_PROBE], capture_output=True, text=True, check=True)
    return json.loads(proc.stdout)


def build_oracle(kit, kit_python, fixtures, cases, directory):
    """Render the substrate-off oracle once; afterwards only verify its recorded bytes."""
    manifest = directory / "oracle.json"
    if directory.exists():
        if not manifest.exists():
            raise ParityError(f"{directory}: oracle without oracle.json")
        recorded = json.loads(manifest.read_text(encoding="utf-8"))
        for row in recorded["files"]:
            path = directory / row["path"]
            if not path.is_file() or sha(path) != row["sha256"]:
                raise ParityError(f"oracle byte check failed: {row['path']}")
        return recorded["files"], {}
    staging = directory.with_name(directory.name + f".partial-{os.getpid()}")
    seconds = {}
    for case, args in cases.items():
        argv = [arg.replace("$FX", str(fixtures)) for arg in args]
        started = time.monotonic()
        subprocess.run([kit_python, str(kit / "reference/skn_render.py"), *argv, "--out", str(staging / case)],
                       check=True, capture_output=True, cwd=kit / "reference", timeout=3600)
        seconds[case] = round(time.monotonic() - started, 2)
    files = [{"path": p.relative_to(staging).as_posix(), "sha256": sha(p)}
             for p in sorted(staging.rglob("*")) if p.is_file()]
    (staging / "oracle.json").write_text(dump({"files": files}), encoding="utf-8")
    staging.rename(directory)
    return files, seconds


def read_dem(path):
    """The kit reference's DEM reading: masked band 1, scale/offset, implausible heights to NaN."""
    import rasterio
    with rasterio.open(path) as src:
        if src.crs is None or not src.crs.is_projected:
            raise ParityError(f"{path}: DEM must be in a projected metric CRS")
        rx, ry = src.res
        if abs(rx - ry) > 1e-6:
            raise ParityError(f"{path}: DEM cells must be square")
        band = src.read(1, masked=True).astype("f8")
        scale = (src.scales or [1])[0] or 1
        offset = (src.offsets or [0])[0] or 0
        z = band.filled(np.nan) * scale + offset
        t = src.transform
    z[(z < -11000) | (z > 9000)] = np.nan
    rows, cols = z.shape
    return z, float(rx), (t.c, t.f + t.e * rows, t.c + t.a * cols, t.f)


def render_engine(dem, out, baked, zoom_class):
    z, cell, bounds = read_dem(dem)
    started = time.monotonic()
    engine = nearshore.Nearshore(z, cell, bounds, baked)
    mask, piles = engine.piles()
    base = nearshore.to_bytes(engine.base(zoom_class))
    nopiles = nearshore.to_bytes(engine.base_nopiles(zoom_class))
    seconds = time.monotonic() - started
    out.mkdir(parents=True, exist_ok=True)
    (out / "base.png").write_bytes(png8.encode(base))
    (out / "base_nopiles.png").write_bytes(png8.encode(nopiles))
    (out / "pile_mask.png").write_bytes(png8.encode(mask.astype(np.uint8) * np.iinfo(np.uint8).max))
    features = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["x"], p["y"]]},
                 "properties": {k: v for k, v in p.items() if k not in ("x", "y")}} for p in piles]
    (out / "piles.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}), encoding="utf-8")
    area_km2 = z.size * cell * cell / 1e6
    return {"seconds": round(seconds, 3), "cell_m": cell, "km2": round(area_km2, 4),
            "s_per_km2": round(seconds / area_km2, 3), "piles": len(piles)}


def compare(kit, kit_python, *args):
    mode = args[0]
    proc = subprocess.run([kit_python, str(kit / "reference/compare.py"), *map(str, args)],
                          capture_output=True, text=True, timeout=1800)
    if proc.returncode not in (0, 1):
        raise ParityError(f"compare.py {mode} failed: {proc.stderr.strip()[-400:]}")
    report = json.loads(proc.stdout)
    if not isinstance(report, dict) or not isinstance(report.get("pass"), bool):
        raise ParityError(f"compare.py {mode}: expected a JSON object with a boolean 'pass'")
    if proc.returncode != (0 if report["pass"] else 1):
        raise ParityError(f"compare.py {mode}: 'pass' disagrees with exit status {proc.returncode}")
    if mode == "case":
        for field in ("base.png", "piles"):
            if not isinstance(report.get(field), dict):
                raise ParityError(f"compare.py {mode}: expected an object for {field!r}")
    return report


def zoom_class_for(args, baked):
    view = args[args.index("--view") + 1]
    zoom = float(args[args.index("--zoom") + 1])
    # skn_render bakes closeup/pier/base at z16 and an overview at its own zoom.
    if view in ("closeup", "pier", "base"):
        return "closeup"
    return "closeup" if zoom >= baked["rock_piles"]["closeup_min_zoom"] else "overview"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kit", type=Path, required=True, help="the kit's style-guide directory")
    ap.add_argument("--out-root", type=Path, required=True, help="<OUT>/_style")
    ap.add_argument("--kit-python", required=True, help="python of the kit's pinned venv")
    ap.add_argument("--files-manifest", type=Path, help="default: <kit>/../../../kit-v1.0.0.FILES.sha256")
    ap.add_argument("--kit-zip", type=Path, help="default: <kit>/../../../skippercast-nearshore-style-kit-v1.0.0.zip")
    ap.add_argument("--version", help="style version (default: the index default)")
    a = ap.parse_args()
    kit = a.kit.resolve()
    inbox = kit.parent.parent.parent
    manifest = (a.files_manifest or inbox / "kit-v1.0.0.FILES.sha256").resolve()
    kit_zip = (a.kit_zip or inbox / "skippercast-nearshore-style-kit-v1.0.0.zip").resolve()
    out_root = a.out_root.resolve()
    try:
        return run(kit, manifest, kit_zip, out_root, a.kit_python, a.version)
    except (ParityError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"kit_parity: FAIL: {exc}", file=sys.stderr)
        return 1


def run(kit, manifest, kit_zip, out_root, kit_python, version):
    loaded = style.load(version)
    baked = loaded.view("baked")
    index_entry = json.loads((ROOT / "style/index.json").read_bytes())["versions"][loaded.version]
    rows = manifest_rows(manifest)
    files_manifest_sha256 = sha(manifest)
    kit_zip_sha256 = sha(kit_zip)
    if kit_zip_sha256 != index_entry["kit_zip_sha256"]:
        raise ParityError(f"kit zip sha256 {kit_zip_sha256} != index pin {index_entry['kit_zip_sha256']}")

    # Step B: the bytes this run opens.
    cases = selftest_cases(kit / "reference/selftest.sh")
    opened = sorted({arg.replace("$FX/", "fixtures/") for args in cases.values() for arg in args if arg.startswith("$FX/")}
                    | {f"fixtures/cayucos_reef_xres/{name}" for name in XRES.values()})
    reference = verify_kit_files(kit, rows, [f"reference/{name}" for name in (*parity.REFERENCE_FILES, "selftest.sh")]
                                 + ["style-tokens.json"])
    if reference[-1]["sha256"] != index_entry["sha256"]:
        raise ParityError("the kit's style-tokens.json is not the selected style release")
    fixtures = verify_kit_files(kit, rows, opened)
    print("fixture bytes: verified", len(fixtures), "files against", manifest.name)

    # Step A: the reference reproduces its own goldens in this venv.
    selftest = run_selftest(kit, kit_python, out_root / "work/selftest")
    print("\n".join(selftest["lines"]))
    if not selftest["ok"]:
        raise ParityError("kit selftest did not print SELFTEST OK: no oracle, parity not run")

    # Step C: the substrate-off oracle.
    runtime_kit = kit_runtime(kit_python)
    reference_sha = {row["path"].removeprefix("reference/"): row["sha256"] for row in reference
                     if row["path"].removeprefix("reference/") in parity.REFERENCE_FILES}
    okey = parity.oracle_key(kit_zip_sha256, files_manifest_sha256, reference_sha, runtime_kit, cases)
    oracle_dir = out_root / "oracle" / okey
    oracle_files, oracle_seconds = build_oracle(kit, kit_python, kit / "fixtures", cases, oracle_dir)
    print("oracle", okey, "files", len(oracle_files))

    # Step D: the engine on the same grids, compared with the oracle and over the xres trio.
    runtime = parity.engine_runtime()
    edigest = parity.engine_digest()
    b = baked.digest("baked")
    pkey = parity.parity_key(edigest, nearshore.ENGINE_EPOCH, runtime, b, kit_zip_sha256, files_manifest_sha256, okey)
    work = out_root / "work" / pkey
    results, timing = {}, {"oracle_render_seconds": oracle_seconds, "engine": {}}
    for case, args in cases.items():
        ours, ref = work / "ours" / case, work / "ref" / case
        timing["engine"][case] = render_engine(kit / args[0].replace("$FX/", "fixtures/"), ours, baked,
                                               zoom_class_for(args, baked))
        ref.mkdir(parents=True, exist_ok=True)
        for name in ORACLE_FILES:
            shutil.copyfile(oracle_dir / case / name, ref / name)
        oracle_rows = {row["path"]: row["sha256"] for row in oracle_files}
        if any(sha(ref / name) != oracle_rows[f"{case}/{name}"] for name in ORACLE_FILES):
            raise ParityError(f"{case}: oracle copy does not match oracle.json")
        report = compare(kit, kit_python, "case", ours, ref)
        report["case"] = case
        results[case] = report
        print(case, "PASS" if report["pass"] else "FAIL", json.dumps(report["base.png"], sort_keys=True),
              json.dumps(report["piles"], sort_keys=True))
    xres_dirs = []
    for k, name in XRES.items():
        out = work / "ours" / f"xres_{k}m"
        timing["engine"][f"xres_{k}m"] = render_engine(kit / "fixtures/cayucos_reef_xres" / name, out, baked, "closeup")
        xres_dirs.append(out)
    xres = compare(kit, kit_python, "xres", *xres_dirs)
    print("xres", "PASS" if xres["pass"] else "FAIL", json.dumps(xres, sort_keys=True))

    cases_pass = {case: {"pass": r["pass"], "base": r["base.png"], "piles": r["piles"]} for case, r in results.items()}
    ok = selftest["ok"] and all(c["pass"] for c in cases_pass.values()) and xres["pass"]
    doc = {"schema": "sc-style-parity/1", "pass": ok, "parity_key": pkey, "engine_digest": edigest,
           "engine_epoch": nearshore.ENGINE_EPOCH, "runtime": runtime, "style": loaded.version, "baked": b,
           "fixtures": {"kit_zip_sha256": kit_zip_sha256, "files_manifest_sha256": files_manifest_sha256,
                        "files": fixtures, "reference": reference},
           "oracle": {"key": okey, "runtime": runtime_kit, "args": cases, "files": oracle_files,
                      "substrate": "off (selftest arguments minus --class; no class raster opened)"},
           "selftest": selftest, "cases": cases_pass, "xres": xres}
    target = out_root / "parity" / pkey
    target.mkdir(parents=True, exist_ok=True)
    text = dump(doc)
    previous = target / "parity.json"
    if previous.exists() and previous.read_text(encoding="utf-8") != text:
        (target / "parity.json.rerun").write_text(text, encoding="utf-8")
        raise ParityError(f"rerun differs from {previous} (kept as parity.json.rerun)")
    rerun = previous.exists()
    previous.write_text(text, encoding="utf-8")
    (target / "timing.json").write_text(dump(timing), encoding="utf-8")
    print("parity", "PASS" if ok else "FAIL", pkey, "rerun identical" if rerun else "written", previous)
    print("parity.json sha256", sha(previous))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
