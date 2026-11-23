"""Dependency-free check that bytes are one complete, decodable PNG image.

Used before a relief tile is embedded in a preview: a signature/IHDR prefix is not an image.
Checks chunk framing and CRCs, chunk order, then inflates the IDAT stream and requires exactly
the scanline bytes the header implies (valid filter bytes, no truncation, no trailing data).
"""
import struct
from zlib import crc32, decompressobj, error as ZlibError

SIGNATURE = b'\x89PNG\r\n\x1a\n'
CHANNELS = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8), 4: (8, 16), 6: (8, 16)}
SAMPLES = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
CRITICAL = (b'IHDR', b'PLTE', b'IDAT', b'IEND')
# Adam7 passes as (x start, y start, x step, y step).
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))


def _chunks(data):
    pos, kinds = len(SIGNATURE), []
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError('truncated PNG chunk')
        size, kind = struct.unpack_from('>I4s', data, pos)
        end = pos + 12 + size
        if size > 0x7fffffff or end > len(data):
            raise ValueError('truncated PNG chunk')
        body = data[pos + 8:pos + 8 + size]
        if struct.unpack_from('>I', data, end - 4)[0] != crc32(kind + body):
            raise ValueError('PNG chunk checksum mismatch')
        kinds.append((kind, body))
        pos = end
        if kind == b'IEND':
            break
    return kinds, pos


def _scanlines(width, height, depth, color, interlace):
    bits = depth * SAMPLES[color]
    passes = ADAM7 if interlace else ((0, 0, 1, 1),)
    for x0, y0, dx, dy in passes:
        w, h = -(-(width - x0) // dx), -(-(height - y0) // dy)
        if w > 0 and h > 0:
            yield h, 1 + -(-w * bits // 8)


def _check_ancillary_structure(chunks, kinds, first_idat, color, depth):
    """Chunk-level constraints a strict decoder (libpng) treats as fatal: critical chunks, PLTE and tRNS."""
    for kind in kinds:
        if not all(65 <= c <= 90 or 97 <= c <= 122 for c in kind) or (kind[2] & 0x20):
            raise ValueError('PNG chunk name is malformed')
        if not kind[0] & 0x20 and kind not in CRITICAL:
            raise ValueError('PNG has an unknown critical chunk')
    for kind in (b'PLTE', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'iCCP', b'sBIT', b'bKGD', b'hIST', b'pHYs'):
        if kinds.count(kind) > 1:
            raise ValueError(f'PNG has more than one {kind.decode()} chunk')
        if kind in kinds and kinds.index(kind) > first_idat:
            raise ValueError(f'PNG {kind.decode()} chunk comes after IDAT')
    if b'PLTE' in kinds and b'tRNS' in kinds and kinds.index(b'tRNS') < kinds.index(b'PLTE'):
        raise ValueError('PNG tRNS chunk comes before PLTE')
    palette = chunks[kinds.index(b'PLTE')][1] if b'PLTE' in kinds else None
    if color == 3 and palette is None:
        raise ValueError('indexed PNG needs PLTE before IDAT')
    if palette is not None:
        if color in (0, 4):
            raise ValueError('grayscale PNG must not have a PLTE chunk')
        if not palette or len(palette) % 3 or len(palette) // 3 > (1 << min(depth, 8)):
            raise ValueError('PNG PLTE chunk is invalid')
    if b'tRNS' in kinds:
        size = len(chunks[kinds.index(b'tRNS')][1])
        if color in (4, 6) or (color == 0 and size != 2) or (color == 2 and size != 6) \
                or (color == 3 and not 0 < size <= len(palette) // 3):
            raise ValueError('PNG tRNS chunk is invalid')


def validate_png(data, width, height):
    """Raise ValueError unless data is a complete, decodable width×height PNG."""
    if data[:8] != SIGNATURE:
        raise ValueError('missing PNG signature')
    try:
        chunks, end = _chunks(data)
        if end != len(data):
            raise ValueError('trailing bytes after PNG IEND')
        kinds = [kind for kind, _ in chunks]
        if not kinds or kinds[0] != b'IHDR' or kinds[-1] != b'IEND':
            raise ValueError('PNG must start with IHDR and end with IEND')
        if len(chunks[0][1]) != 13 or kinds.count(b'IHDR') != 1 or kinds.count(b'IEND') != 1:
            raise ValueError('malformed PNG header')
        w, h, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', chunks[0][1])
        if (w, h) != (width, height) or depth not in CHANNELS.get(color, ()) or compression or filtering \
                or interlace not in (0, 1):
            raise ValueError('unsupported or mismatched PNG header')
        idat = [i for i, kind in enumerate(kinds) if kind == b'IDAT']
        if not idat or idat != list(range(idat[0], idat[0] + len(idat))):
            raise ValueError('PNG needs one contiguous IDAT run')
        _check_ancillary_structure(chunks, kinds, idat[0], color, depth)
        rows = list(_scanlines(w, h, depth, color, interlace))
        expected = sum(count * size for count, size in rows)
        inflater = decompressobj()
        raw = inflater.decompress(b''.join(chunks[i][1] for i in idat), expected + 1)
        if not inflater.eof or inflater.unconsumed_tail or inflater.unused_data or len(raw) != expected:
            raise ValueError('PNG image data is truncated, oversized or not one zlib stream')
    except (struct.error, ZlibError) as exc:
        raise ValueError(f'PNG is not decodable: {exc}') from exc
    pos = 0
    for count, size in rows:
        for _ in range(count):
            if raw[pos] > 4:
                raise ValueError('PNG scanline has an invalid filter type')
            pos += size
