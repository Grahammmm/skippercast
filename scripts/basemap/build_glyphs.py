"""Build the basemap label glyphs (FE-72, docs/plans/front-end/design.md § 4).

MapLibre draws text from signed-distance-field glyph ranges
(`{fontstack}/{range}.pbf`, 256 code points each). This writes them for DM
Sans Medium from the self-hosted web/fonts/dm-sans-latin.woff2 (SIL OFL 1.1,
no Reserved Font Name), so the chart's labels use the app's type (D6) and no
glyph is fetched from a third party. Only the ranges the Latin subset fills
are written; MapLibre skips a missing range's characters.

Format: the MapLibre glyph protobuf at 24 px with a 3 px border, radius 8
and cutoff 0.25 (the values node-fontnik and TinySDF use); `top` is the
bitmap top minus the ascender, as fontnik writes it. The distance field is
computed on a 4x supersampled rendering and averaged down.

    python scripts/basemap/build_glyphs.py          # needs fonttools, brotli, Pillow, numpy, scipy
    python scripts/basemap/build_glyphs.py --check  # rebuild in memory, compare with the pins, write nothing

Output: dist/basemap/glyphs/dm-sans-medium/{0-255,8192-8447}.pbf; update their
hashes in scripts/web-vendor-sha256.json after a rebuild. Paste the printed
`versions:` line into the commit that changes the glyph files.
"""
import argparse
import hashlib
import importlib.util
import json
import platform
import sys
from importlib import metadata
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "web/fonts/dm-sans-latin.woff2"
STACK = "dm-sans-medium"
OUT = ROOT / "dist/basemap/glyphs" / STACK
PINS = ROOT / "scripts/web-vendor-sha256.json"
PREFIX = f"dist/basemap/glyphs/{STACK}/"
WEIGHT, SIZE, BORDER, RADIUS, CUTOFF, SCALE = 500, 24, 3, 8, 0.25, 4
RANGES = (0, 8192)
MODULES = {"fonttools": "fontTools", "brotli": "brotli", "Pillow": "PIL", "numpy": "numpy", "scipy": "scipy"}
np = distance_transform_edt = None  # set by build() from _libs(); glyph() uses them


def _libs():
    """The font stack, imported only to build so importing this module needs none of it."""
    missing = [package for package, module in MODULES.items() if importlib.util.find_spec(module) is None]
    if missing:
        print(f"build_glyphs: needs fonttools, brotli, Pillow, numpy, scipy (missing: {', '.join(missing)})", file=sys.stderr)
        raise SystemExit(2)
    import numpy
    from fontTools.ttLib import TTFont
    from fontTools.varLib.instancer import instantiateVariableFont
    from PIL import ImageFont
    from scipy.ndimage import distance_transform_edt
    return numpy, TTFont, instantiateVariableFont, ImageFont, distance_transform_edt


def versions():
    found = {"python": platform.python_version()}
    for package in MODULES:
        try:
            found[package.lower()] = metadata.version(package)
        except metadata.PackageNotFoundError:
            found[package.lower()] = "absent"
    return found


def varint(n):
    out = bytearray()
    while True:
        byte, n = n & 0x7F, n >> 7
        out.append(byte | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field(number, value):
    """One protobuf field: bytes are length-delimited, ints are varints (sint32 already zigzagged)."""
    if isinstance(value, bytes):
        return varint(number << 3 | 2) + varint(len(value)) + value
    return varint(number << 3) + varint(value)


def zigzag(n):
    return (n << 1) ^ (n >> 31)


def glyph(font, ascender, code):
    char = chr(code)
    advance = round(font.getlength(char) / SCALE)
    mask, (ox, oy) = font.getmask2(char, mode="L", anchor="ls")
    hi = np.asarray(mask, dtype=np.uint8).reshape(mask.size[1], mask.size[0])
    ys, xs = np.nonzero(hi)
    if not len(xs):
        return field(1, code) + field(3, 0) + field(4, 0) + field(5, 0) + field(6, zigzag(-ascender)) + field(7, advance)
    # Crop to the ink: Pillow's mask spans the advance, side bearings included.
    hi = hi[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    ox, oy = ox + int(xs.min()), oy + int(ys.min())
    h, w = hi.shape
    left, right = ox // SCALE, -(-(ox + w) // SCALE)
    top, bottom = oy // SCALE, -(-(oy + h) // SCALE)
    width, height = right - left, bottom - top
    pad = BORDER * SCALE
    canvas = np.zeros(((height + 2 * BORDER) * SCALE, (width + 2 * BORDER) * SCALE), dtype=np.uint8)
    y0, x0 = oy - top * SCALE + pad, ox - left * SCALE + pad
    canvas[y0:y0 + h, x0:x0 + w] = hi
    inside = canvas > 127
    signed = (distance_transform_edt(~inside) - distance_transform_edt(inside)) / SCALE
    blocks = signed.reshape(height + 2 * BORDER, SCALE, width + 2 * BORDER, SCALE).mean(axis=(1, 3))
    bitmap = np.clip(np.round(255 - 255 * (blocks / RADIUS + CUTOFF)), 0, 255).astype(np.uint8)
    return (field(1, code) + field(2, bitmap.tobytes()) + field(3, width) + field(4, height)
            + field(5, zigzag(left)) + field(6, zigzag(-top - ascender)) + field(7, advance))


def build():
    """Each range's repo path and the exact bytes `write` puts there, built in memory."""
    global np, distance_transform_edt
    np, TTFont, instantiateVariableFont, ImageFont, distance_transform_edt = _libs()
    source = TTFont(SOURCE)
    source.flavor = None
    instance = instantiateVariableFont(source, {"wght": WEIGHT})
    ascender = round(instance["hhea"].ascent * SIZE / instance["head"].unitsPerEm)
    data = BytesIO()
    instance.save(data)
    font = ImageFont.truetype(BytesIO(data.getvalue()), SIZE * SCALE, layout_engine=ImageFont.Layout.BASIC)
    codes = set(instance.getBestCmap())
    built = {}
    for start in RANGES:
        name = f"{start}-{start + 255}"
        glyphs = b"".join(field(3, glyph(font, ascender, c)) for c in range(start, start + 256) if c in codes)
        stack = field(1, STACK.encode()) + field(2, name.encode()) + glyphs
        built[f"{PREFIX}{name}.pbf"] = field(1, stack)
    return built


def write(built):
    OUT.mkdir(parents=True, exist_ok=True)
    for rel, data in built.items():
        (OUT / Path(rel).name).write_bytes(data)
        print(f"{rel}: {len(data)} bytes")


def check(built):
    """One line per range against scripts/web-vendor-sha256.json; 0 only when every line is `match`."""
    try:
        pins = json.loads(PINS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pins = None
    if not isinstance(pins, dict):
        print("build_glyphs: pin file unreadable", file=sys.stderr)
        return 2
    lines = [(f"match {rel}" if hashlib.sha256(data).hexdigest() == pins[rel] else f"differs {rel}")
             if rel in pins else f"unpinned {rel}" for rel, data in built.items()]
    lines += [f"not built {rel}" for rel in pins if rel.startswith(PREFIX) and rel.endswith(".pbf") and rel not in built]
    for line in lines:
        print(line)
    return 0 if lines and all(line.startswith("match ") for line in lines) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build the basemap label glyphs.")
    parser.add_argument("--check", action="store_true", help="rebuild in memory and compare with the pins; write nothing")
    args = parser.parse_args(argv)
    print("versions: " + " ".join(f"{name}={version}" for name, version in versions().items()), flush=True)
    if args.check:
        return check(build())
    write(build())
    return 0


if __name__ == "__main__":
    sys.exit(main())
