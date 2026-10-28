"""Create C3-only synthetic terrain-RGB PNG and contour MVT; no survey/cache IO."""
import binascii
import json
import math
from pathlib import Path
import struct
import zlib

OUT = Path(__file__).parent / "fixtures" / "viewer-demo"


def varint(value):
    result = bytearray()
    while value > 127:
        result.append((value & 127) | 128)
        value >>= 7
    return bytes(result + bytes([value]))


def field(number, value):
    return varint(number << 3 | 2) + varint(len(value)) + value


def integer(number, value):
    return varint(number << 3) + varint(value)


def zigzag(n):
    return (n << 1) ^ (n >> 63)


def wave(y):
    return 22 * math.sin(y * math.pi * 4) + 10 * math.cos(y * math.pi * 7)


def png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", binascii.crc32(kind + data) & 0xFFFFFFFF)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    size, extent, zoom = 256, 4096, 12
    x = math.floor((-120.98 + 180) / 360 * 2**zoom)
    y = math.floor((1 - math.asinh(math.tan(math.radians(35.43))) / math.pi) / 2 * 2**zoom)
    west, east = x / 2**zoom * 360 - 180, (x + 1) / 2**zoom * 360 - 180
    lat = lambda row: math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * row / 2**zoom))))
    south, north = lat(y + 1), lat(y)
    raw = bytearray()
    for row in range(size):
        raw.append(0)
        for col in range(size):
            height = -(30 + 250 * col / (size - 1) + wave(row / (size - 1)))
            code = round((height + 10000) * 10)
            raw.extend((code >> 16, (code >> 8) & 255, code & 255))
    png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)) + png_chunk(b"IDAT", zlib.compress(raw)) + png_chunk(b"IEND", b"")
    tiles = OUT / str(zoom) / str(x)
    tiles.mkdir(parents=True, exist_ok=True)
    (tiles / f"{y}.png").write_bytes(png)
    features, values = [], []
    # Every 10 ft through 600 ft; 100 ft beyond. No real-world depth claims.
    levels = list(range(10, 601, 10)) + list(range(700, 1001, 100))
    for depth in levels:
        points = [(round((depth * .3048 - 30 - wave(i / 128)) / 250 * extent), round(i / 128 * extent)) for i in range(129)]
        # Entire fixture line inside the tile, so no spurious clipped edge joins.
        if not all(0 <= a <= extent for a, _ in points):
            continue
        geom, px, py = [], 0, 0
        for i, (a, b) in enumerate(points):
            if i == 0:
                geom.append(9)  # MoveTo, count 1
            elif i == 1:
                geom.append((len(points) - 1) << 3 | 2)  # LineTo
            geom.extend((zigzag(a - px), zigzag(b - py)))
            px, py = a, b
        index = len(values)
        values.append(integer(5, depth))  # MVT uint_value
        features.append(integer(1, index + 1) + field(2, varint(0) + varint(index)) + integer(3, 2) + field(4, b"".join(map(varint, geom))))
    layer = field(1, b"contours") + b"".join(field(2, f) for f in features) + field(3, b"depth_ft") + b"".join(field(4, v) for v in values) + integer(5, extent) + integer(15, 2)
    (tiles / f"{y}.mvt").write_bytes(field(3, layer))
    manifest = dict(schemaVersion=1, region="Central Coast · synthetic C3 demonstration", synthetic=True,
                    bounds=[west, south, east, north], center=[(west + east) / 2, (south + north) / 2],
                    zoom=15.5, tileZoom=zoom, tileSize=size, terrain="{z}/{x}/{y}.png", contours="{z}/{x}/{y}.mvt", contourLayer="contours",
                    sources=[dict(id="c3-analytic-fixture", label="Analytic slope and waves (not a survey)", url=None,
                                  attribution="SkipperCast C3 synthetic fixture generator", license="Repository LICENSE; original synthetic fixture",
                                  datum="Arbitrary synthetic zero; no geodetic datum", resolutionM=math.cos(math.radians(35.43)) * 40075016.686 / 2**zoom / size,
                                  permissionRequired=False)])
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps(dict(synthetic=True, terrain_bytes=len(png), contour_features=len(features), tile=[zoom, x, y], output=str(OUT))))


if __name__ == "__main__":
    main()
