"""Minimal 8-bit PNG codec (stdlib + numpy) for the style scripts and their tests.

Encodes greyscale or RGB arrays with per-row filter choice (minimum sum of absolute values)
and decodes any non-interlaced 8-bit greyscale/RGB/RGBA PNG (all five filter types).
"""

import struct
import zlib

import numpy as np

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COLOUR_TYPES = {1: 0, 3: 2, 4: 6}  # channels -> PNG colour type
_CHANNELS = {0: 1, 2: 3, 6: 4}


def _chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = np.abs(p - a), np.abs(p - b), np.abs(p - c)
    return np.where((pa <= pb) & (pa <= pc), a, np.where(pb <= pc, b, c))


def encode(pixels):
    """PNG bytes of a uint8 array shaped (rows, cols) or (rows, cols, 1|3|4)."""
    a = np.asarray(pixels)
    if a.dtype != np.uint8:
        raise ValueError("PNG encoder takes uint8 pixels")
    if a.ndim == 2:
        a = a[..., None]
    rows, cols, channels = a.shape
    raw = a.reshape(rows, cols * channels).astype(np.int16)
    left = np.zeros_like(raw)
    left[:, channels:] = raw[:, :-channels]
    up = np.zeros_like(raw)
    up[1:] = raw[:-1]
    upleft = np.zeros_like(raw)
    upleft[1:, channels:] = raw[:-1, :-channels]
    candidates = np.stack([raw, raw - left, raw - up, raw - (left + up) // 2, raw - _paeth(left, up, upleft)]) % 256
    cost = np.minimum(candidates, 256 - candidates).sum(axis=2)
    choice = cost.argmin(axis=0)
    filtered = candidates[choice, np.arange(rows)].astype(np.uint8)
    body = np.concatenate([choice.astype(np.uint8)[:, None], filtered], axis=1).tobytes()
    header = struct.pack(">IIBBBBB", cols, rows, 8, _COLOUR_TYPES[channels], 0, 0, 0)
    return SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(body, 9)) + _chunk(b"IEND", b"")


def decode(data):
    """uint8 array (rows, cols, channels) of an 8-bit non-interlaced PNG."""
    if data[:8] != SIGNATURE:
        raise ValueError("not a PNG")
    pos, idat, header = 8, [], None
    while pos < len(data):
        (length,) = struct.unpack(">I", data[pos:pos + 4])
        kind, body = data[pos + 4:pos + 8], data[pos + 8:pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise ValueError("PNG has no IHDR")
    cols, rows, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in _CHANNELS or interlace:
        raise ValueError(f"unsupported PNG: depth {depth}, colour type {colour}, interlace {interlace}")
    bpp = _CHANNELS[colour]
    stride = cols * bpp
    raw = np.frombuffer(zlib.decompress(b"".join(idat)), np.uint8).reshape(rows, stride + 1)
    out = np.zeros((rows, stride), np.uint8)
    previous = np.zeros(stride, np.uint8)
    for r in range(rows):
        kind, line = raw[r, 0], raw[r, 1:]
        if kind == 0:
            row = line.copy()
        elif kind == 2:
            row = (line.astype(np.uint16) + previous) % 256
        elif kind == 1:
            row = line.reshape(cols, bpp).astype(np.int64).cumsum(axis=0) % 256
        elif kind in (3, 4):
            row = [0] * stride
            cur, prev = line.tolist(), previous.tolist()
            for i in range(stride):
                a = row[i - bpp] if i >= bpp else 0
                b = prev[i]
                if kind == 3:
                    predictor = (a + b) // 2
                else:
                    c = prev[i - bpp] if i >= bpp else 0
                    p = a + b - c
                    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                    predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                row[i] = (cur[i] + predictor) % 256
        else:
            raise ValueError(f"bad PNG filter {kind}")
        out[r] = np.asarray(row, np.int64).reshape(stride) % 256
        previous = out[r]
    return out.reshape(rows, cols, bpp)
