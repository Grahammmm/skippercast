#!/usr/bin/env python3
"""Build the public synthetic engine goldens for the nearshore render engine (MSK-3).

    python scripts/style/make_synthetic_goldens.py [--out DIR]

One seeded 1 m surface (a ridge/boulder field cut by a smooth sand channel, an inshore no-data
hole and a land strip) is block-averaged to 2 m and 4 m. Each grid is rendered with
``skippercast.relief.nearshore`` and the ``baked`` view of the default style. The script writes
``s<cell>m_{closeup,overview,nopiles,mask}.png`` (192 x 192 at 1 m), ``metrics.json`` and
``epochs.json`` (``{"<ENGINE_EPOCH>": {"<png>": sha256}}``) under
``tests/fixtures/style/nearshore-v1.0.0/``.

A PNG is rewritten only when its pixels change. A changed golden set for an epoch that already
has a row is refused: bump ``ENGINE_EPOCH`` in the engine (a deliberate look change) and rerun,
which appends the new row and keeps the old ones.
"""

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

import numpy as np
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skippercast import style  # noqa: E402
from skippercast.relief import nearshore  # noqa: E402
import png8  # noqa: E402

OUT = ROOT / "tests/fixtures/style/nearshore-v1.0.0"
PINS = ROOT / "scripts/web-vendor-sha256.json"
SEED = 20261119
SIZE_M = 192
ORIGIN = (700000.0, 3900000.0)  # west, north of a UTM-like metric grid
CELLS = (1, 2, 4)
KINDS = ("closeup", "overview", "nopiles", "mask")


def surface_1m(seed=SEED):
    """The 1 m synthetic DEM (metres, positive up, NaN = no data) and its bounds."""
    rng = np.random.default_rng(seed)
    n = SIZE_M
    x = (np.arange(n) + 0.5)[None, :] * np.ones((n, 1))
    y = (np.arange(n) + 0.5)[:, None] * np.ones((1, n))
    shore = 172.0
    z = np.where(x < shore, -20.0 * np.clip(1 - x / shore, 0, None) ** 1.3, 0.35 * (x - shore))  # land strip
    channel = np.exp(-((y - 112.0 - 8.0 * np.sin(x / 30.0)) / 12.0) ** 2)  # smooth sand channel
    rock = np.zeros((n, n))
    for _ in range(28):  # boulders
        cx, cy = 12 + rng.random() * 144, 6 + rng.random() * 180
        sigma = 3.5 + rng.random() * 4.0
        rock += (1.4 + rng.random() * 2.4) * np.exp(-((x - cx) ** 2 + (y - cy) ** 2) / (2 * sigma ** 2))
    for _ in range(2):  # ridges
        cx, cy, angle = 24 + rng.random() * 110, 16 + rng.random() * 64, rng.random() * np.pi
        along = (x - cx) * np.cos(angle) + (y - cy) * np.sin(angle)
        across = -(x - cx) * np.sin(angle) + (y - cy) * np.cos(angle)
        rock += (1.2 + rng.random()) * np.exp(-(across / 3.0) ** 2 - (along / 40.0) ** 2)
    rough = ndimage.gaussian_filter(rng.random((n, n)) - 0.5, 1.2, mode="reflect") * 2.2
    rough *= np.clip(rock / 0.6, 0, 1)  # rough rock, smooth sand between boulders
    field = (x < 158).astype(float) * (1 - channel)
    z = z + field * (rock + rough) - 1.6 * channel * (x < shore)
    hole = (x - 164.0) ** 2 + (y - 30.0) ** 2 < 8.0 ** 2  # inshore no-data hole
    z[hole] = np.nan
    west, north = ORIGIN
    return z, (west, north - n, west + n, north)


def block_mean(z, k):
    """Area mean over k x k blocks; a block with any no-data cell is no data."""
    rows, cols = z.shape
    return z[:rows - rows % k, :cols - cols % k].reshape(rows // k, k, cols // k, k).mean(axis=(1, 3))


def synthetic_grids(seed=SEED):
    z, bounds = surface_1m(seed)
    return {k: (z if k == 1 else block_mean(z, k), float(k), bounds) for k in CELLS}


def render(baked, z, cell, bounds):
    """uint8 images per kind, the pile list and the engine metrics for one grid."""
    engine = nearshore.Nearshore(z, cell, bounds, baked)
    mask, piles = engine.piles()
    images = {"closeup": nearshore.to_bytes(engine.base("closeup")),
              "overview": nearshore.to_bytes(engine.base("overview")),
              "nopiles": nearshore.to_bytes(engine.base_nopiles("closeup")),
              "mask": mask.astype(np.uint8) * np.iinfo(np.uint8).max}
    return images, piles, engine.metrics()


def _rounded(value):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def build(out=OUT):
    baked = style.load().view("baked")
    metrics, staged, hashes = {}, {}, {}  # staged: PNG bytes to be on disk; nothing is written before the check
    for cell, (z, size, bounds) in synthetic_grids().items():
        images, piles, m = render(baked, z, size, bounds)
        metrics[f"s{cell}m"] = _rounded({**m, "pile_heights_m": [p["height_m"] for p in piles]})
        for kind in KINDS:
            name = f"s{cell}m_{kind}.png"
            path = out / name
            pixels = images[kind]
            current = path.read_bytes() if path.exists() else None
            if current is not None and np.array_equal(png8.decode(current), pixels.reshape(*pixels.shape[:2], -1)):
                staged[name] = current
            else:
                staged[name] = png8.encode(pixels)
            hashes[name] = sha256(staged[name]).hexdigest()
    epochs_path = out / "epochs.json"
    epochs = json.loads(epochs_path.read_text(encoding="utf-8")) if epochs_path.exists() else {}
    key = str(nearshore.ENGINE_EPOCH)
    if key in epochs and epochs[key] != hashes:
        raise SystemExit(f"golden pixels changed under ENGINE_EPOCH {key}: bump ENGINE_EPOCH in "
                         "src/skippercast/relief/nearshore.py for a deliberate look change, then rerun; "
                         "no file was written")
    out.mkdir(parents=True, exist_ok=True)
    for name, data in staged.items():
        path = out / name
        if not (path.exists() and path.read_bytes() == data):
            path.write_bytes(data)
    epochs[key] = hashes
    epochs_path.write_text(json.dumps(epochs, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    # check_repository.py admits a binary file only with its pin in the shared manifest.
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    prefix = out.resolve().relative_to(ROOT).as_posix() + "/" if out.resolve().is_relative_to(ROOT) else None
    if prefix:
        pins = {k: v for k, v in pins.items() if not k.startswith(prefix)}
        pins.update({prefix + name: digest for name, digest in hashes.items()})
        PINS.write_text(json.dumps(dict(sorted(pins.items())), indent=2) + "\n", encoding="utf-8")
    (out / "metrics.json").write_text(json.dumps({"engine_epoch": nearshore.ENGINE_EPOCH, "seed": SEED,
                                                  "style": baked.version, "baked": baked.digest("baked"),
                                                  "grids": metrics}, indent=1, sort_keys=True) + "\n",
                                      encoding="utf-8")
    return metrics, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=OUT, help="golden directory (default: the test fixtures)")
    args = parser.parse_args()
    metrics, hashes = build(args.out)
    for name, grid in metrics.items():
        print(name, "piles", grid["piles"], "ve", grid["ve"], "valid", grid["valid_frac"], "water", grid["water_frac"])
    for name, digest in sorted(hashes.items()):
        print(name, (args.out / name).stat().st_size, digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
