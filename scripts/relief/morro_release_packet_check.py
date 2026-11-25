#!/usr/bin/env python3
"""Join the six hosted Morro phone captures to the exact R8 release, offline.

Supply the authorized workers.dev origin, the exact candidate's preview plan and
pointer, the R8 envelope SHA-256 and the successful live-check receipt from that
origin. Run from the clone root (or pass --repo): the checker reads git itself to
prove that the supplied pointer bytes are catalog/relief/morro-bay.json at the
planned commit, and that the receipt's merge is the first-parent commit that last
changed it and carries the same bytes (a shallow clone cannot prove that and fails
closed). The browser operator's capture.json uses schema sc-morro-stage-phone/1
and a shots array. In each row record observed region, URL, theme, integer zoom,
layers_closed, viewport [width, height], deployed commit, served pointer SHA-256,
served envelope SHA-256 and png_sha256. Store CSS-scale PNGs next to the receipt
as <theme>-phone-z<zoom>.png. Observe the deployment and pointer for each view;
do not fill the rows from the plan or rename old screenshots.

This checks the evidence join, not its provenance or visual content. Only use
receipts from the authorized capturer and live checker, and keep R8 visual review.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import zlib

REGION = 'morro-bay'
POINTER_KEY = 'catalog/relief/morro-bay.json'
GIT_TIMEOUT = 30
VIEWS = {(theme, zoom) for theme in ('light', 'dark') for zoom in (11, 13, 15)}
STAGE_ORIGIN = re.compile(r'https://([a-z0-9-]+-stage)\.[a-z0-9-]+\.workers\.dev')
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
# Allowed bit depths and samples per pixel for each PNG colour type.
PNG_COLOR = {0: ((1, 2, 4, 8, 16), 1), 2: ((8, 16), 3), 3: ((1, 2, 4, 8), 1), 4: ((8, 16), 2), 6: ((8, 16), 4)}
ADAM7 = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
PNG_LIMIT = 1 << 27
# Chunk placement rules (PNG spec 5.6): each of these may appear once; some only before PLTE,
# some only after it, some only before the first IDAT.
PNG_ONCE = {b'PLTE', b'cHRM', b'gAMA', b'iCCP', b'sBIT', b'sRGB', b'cICP', b'mDCV', b'cLLI', b'bKGD', b'hIST',
            b'tRNS', b'pHYs', b'tIME', b'eXIf'}
PNG_BEFORE_PLTE = {b'cHRM', b'gAMA', b'iCCP', b'sBIT', b'sRGB', b'cICP', b'mDCV', b'cLLI'}
PNG_AFTER_PLTE = {b'bKGD', b'hIST', b'tRNS'}
PNG_BEFORE_IDAT = PNG_BEFORE_PLTE | PNG_AFTER_PLTE | {b'PLTE', b'pHYs', b'sPLT'}
PNG_FIXED = {b'gAMA': 4, b'sRGB': 1, b'pHYs': 9, b'tIME': 7, b'cHRM': 32}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch(rf'[0-9a-f]{{{length}}}', value) is not None


def _read(path, limit):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    _require(len(raw) <= limit, f'{path.name}: input too large')
    return raw


def _object(raw):
    data = json.loads(raw)
    _require(isinstance(data, dict), 'expected a JSON object')
    return data


def _document(path):
    return _object(_read(path, 1 << 20))


def _unfilter(kind, line, previous, step):
    """Reverse one PNG scanline filter (spec 9.2); `kind` is already known to be 0-4."""
    out = bytearray(line)
    for i in range(len(out)):
        left = out[i - step] if i >= step else 0
        up = previous[i]
        corner = previous[i - step] if i >= step else 0
        if kind == 1:
            guess = left
        elif kind == 2:
            guess = up
        elif kind == 3:
            guess = (left + up) // 2
        elif kind == 4:
            near = left + up - corner
            distances = (abs(near - left), abs(near - up), abs(near - corner))
            guess = (left, up, corner)[distances.index(min(distances))]
        else:
            guess = 0
        out[i] = (out[i] + guess) & 255
    return bytes(out)


def _indices(line, depth, count):
    if depth == 8:
        return line[:count]
    per = 8 // depth
    return [(line[i // per] >> (8 - depth * (i % per + 1))) & ((1 << depth) - 1) for i in range(count)]


def _png_chunks(png):
    """Split a PNG into (type, body) pairs, checking framing, CRCs, order and chunk rules."""
    _require(png.startswith(PNG_SIGNATURE), 'not a PNG')
    pos, chunks, seen = len(PNG_SIGNATURE), [], set()
    while pos < len(png):
        _require(pos + 12 <= len(png), 'truncated PNG chunk')
        length, kind = struct.unpack('>I4s', png[pos:pos + 8])
        body, end = png[pos + 8:pos + 8 + length], pos + 12 + length
        _require(end <= len(png) and zlib.crc32(kind + body) == struct.unpack('>I', png[end - 4:end])[0],
                 'corrupt PNG chunk')
        # Four letters, the reserved third one upper case; an unknown critical chunk cannot be decoded.
        _require(re.fullmatch(rb'[A-Za-z]{2}[A-Z][A-Za-z]', kind) is not None, 'invalid PNG chunk type')
        _require(kind in (b'IHDR', b'PLTE', b'IDAT', b'IEND') or kind[0] > 90, 'unsupported critical PNG chunk')
        _require(len(chunks) > 0 or kind == b'IHDR', 'invalid PNG header')
        _require(kind != b'IHDR' or not chunks, 'duplicate PNG header')
        _require(kind not in PNG_ONCE or kind not in seen, 'duplicate PNG chunk')
        idat = seen >= {b'IDAT'}
        _require(not (idat and kind in PNG_BEFORE_IDAT), 'PNG chunk after image data')
        _require(not (kind in PNG_BEFORE_PLTE and b'PLTE' in seen), 'PNG chunk after palette')
        _require(not (kind == b'PLTE' and seen & PNG_AFTER_PLTE), 'PNG palette after the chunks that use it')
        _require(kind != b'IDAT' or not idat or chunks[-1][0] == b'IDAT', 'split PNG image data')
        _require(kind not in PNG_FIXED or length == PNG_FIXED[kind], 'invalid PNG chunk length')
        chunks.append((kind, body))
        seen.add(kind)
        pos = end
        _require(kind != b'IEND' or (length == 0 and pos == len(png)), 'invalid PNG end')
    _require(chunks and chunks[-1][0] == b'IEND' and b'IDAT' in seen, 'PNG has no image data')
    return chunks


def _png_size(png):
    """(width, height) of a PNG that a conforming decoder reads whole; else ValueError.

    Checks chunk framing and CRCs, critical-chunk order, header, palette and transparency rules, and
    the zlib stream; then walks every scanline of every interlace pass for a legal filter byte, and
    palette indices when the palette is smaller than the bit depth allows."""
    chunks = _png_chunks(png)
    _require(len(chunks[0][1]) == 13, 'invalid PNG header')
    width, height, depth, color, compression, filtering, interlace = struct.unpack('>IIBBBBB', chunks[0][1])
    _require(0 < width < 1 << 31 and 0 < height < 1 << 31 and color in PNG_COLOR and depth in PNG_COLOR[color][0]
             and compression == 0 and filtering == 0 and interlace in (0, 1), 'unsupported PNG header')
    parts = dict(chunks)
    palette = len(parts.get(b'PLTE', b'')) // 3
    if b'PLTE' in parts:
        size = len(parts[b'PLTE'])
        _require(color in (2, 3, 6) and size % 3 == 0 and 0 < palette <= (1 << depth if color == 3 else 256),
                 'invalid PNG palette')
    _require(color != 3 or palette, 'indexed PNG has no palette')
    if b'tRNS' in parts:
        size = len(parts[b'tRNS'])
        _require(size == {0: 2, 2: 6}.get(color) or (color == 3 and 0 < size <= palette), 'invalid PNG transparency')
    if b'bKGD' in parts:
        _require(len(parts[b'bKGD']) == {0: 2, 4: 2, 2: 6, 6: 6, 3: 1}[color], 'invalid PNG background')
        _require(color != 3 or parts[b'bKGD'][0] < palette, 'invalid PNG background')
    if b'hIST' in parts:
        _require(color == 3 and len(parts[b'hIST']) == 2 * palette, 'invalid PNG histogram')
    bits = PNG_COLOR[color][1] * depth
    passes = ADAM7 if interlace else ((0, 0, 1, 1),)
    sizes = []  # (columns, rows) for each non-empty pass
    for x0, y0, dx, dy in passes:
        columns, rows = -(-(width - x0) // dx), -(-(height - y0) // dy)
        if columns > 0 and rows > 0:
            sizes.append((columns, rows))
    expected = sum(rows * (1 + -(-columns * bits // 8)) for columns, rows in sizes)
    _require(0 < expected <= PNG_LIMIT, 'PNG image data too large')
    inflater = zlib.decompressobj()
    try:
        data = inflater.decompress(b''.join(body for kind, body in chunks if kind == b'IDAT'), expected + 1)
    except zlib.error:
        raise ValueError('unreadable PNG image data') from None
    _require(inflater.eof and not inflater.unused_data and len(data) == expected, 'PNG image data is the wrong size')
    # Every scanline starts with a filter byte; only 0-4 exist. Indexed pixels must name a palette entry.
    check_indices = color == 3 and palette < 1 << depth
    step, pos = max(1, bits // 8), 0
    for columns, rows in sizes:
        span = -(-columns * bits // 8)
        previous = bytes(span)
        for _ in range(rows):
            kind, line = data[pos], data[pos + 1:pos + 1 + span]
            pos += 1 + span
            _require(kind <= 4, 'invalid PNG scanline filter')
            if check_indices:
                previous = _unfilter(kind, line, previous, step)
                _require(all(i < palette for i in _indices(previous, depth, columns)), 'PNG pixel outside its palette')
    return width, height


def _git(repo, *args):
    try:
        done = subprocess.run(['git', '--no-optional-locks', '-c', 'core.fsmonitor=false', '-C', str(repo), *args],
                              capture_output=True, check=True, timeout=GIT_TIMEOUT)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise ValueError('git could not read the planned commit; run from the clone root that contains it') from None
    return done.stdout


def _bind_pointer(repo, commit, raw):
    """Prove from git that `raw` is the reviewed pointer at the planned commit; return its merge commit."""
    _require(Path(os.fsdecode(_git(repo, 'rev-parse', '--show-toplevel').rstrip(b'\n'))).resolve()
             == Path(repo).resolve(), '--repo must name the clone root')
    _require(_git(repo, 'show', f'{commit}:{POINTER_KEY}') == raw, 'pointer is not the planned commit\'s pointer')
    merge = _git(repo, 'log', '-1', '--first-parent', '--format=%H', commit, '--', POINTER_KEY).strip().decode('ascii')
    _require(_hex(merge, 40) and _git(repo, 'show', f'{merge}:{POINTER_KEY}') == raw,
             'pointer merge does not carry the supplied pointer')
    return merge


def _stage(args):
    origin, envelope = args.stage_origin, args.envelope_sha256
    hostname = STAGE_ORIGIN.fullmatch(origin)
    if hostname is None or not _hex(envelope, 64):
        raise ValueError('expected dedicated HTTPS stage origin and R8 envelope digest')
    plan = _document(args.stage_plan)
    commit = plan.get('commit')
    _require(plan.get('schema') == 'sc-morro-stage-preview/1' and plan.get('region') == REGION
             and plan.get('worker') == hostname[1] and _hex(commit, 40), 'wrong Morro stage plan')
    raw = _read(args.pointer, 1 << 20)
    digest = sha256(raw).hexdigest()
    _require(plan.get('pointer_sha256') == digest, 'pointer does not match the stage plan')
    pointer = _object(raw)
    _require(pointer.get('schema') == 'sc-relief-pointer/1' and pointer.get('region') == REGION
             and pointer.get('status') == 'reviewed' and pointer.get('private') is False
             and pointer.get('envelope_sha256') == envelope, 'pointer is not the public R8 Morro candidate')
    pins = pointer.get('survey_detail')
    _require(isinstance(pins, dict) and set(pins) == {'wire', 'decoded'}
             and all(isinstance(p, dict) and _hex(p.get('sha256'), 64) and type(p.get('bytes')) is int
                     and p['bytes'] > 0 for p in pins.values()), 'missing reviewed survey pins')

    merge = _bind_pointer(args.repo, commit, raw)
    live = _document(args.live)
    checks = live.get('checks')
    _require(live.get('verdict') == 'PASS' and live.get('region') == REGION and live.get('base') == origin
             and live.get('deployed') == commit and isinstance(checks, list)
             and all(isinstance(c, dict) and c.get('status') == 'PASS' for c in checks),
             'live check did not pass on the exact planned origin and commit')
    # The receipt's pointer proof compares the served pointer with the pointer at its own merge commit.
    _require(live.get('merge') == merge, 'live check proved a different pointer merge than git shows')
    # Other valid rows repeat names (e.g. digest chunks); these four must be unique.
    for check in ('deploy', 'pointer', 'contours', 'survey'):
        rows = [c for c in checks if c.get('check') == check]
        _require(len(rows) == 1, f'live check must prove {check} exactly once')
        if check == 'deploy':
            # equal only when the pointer merged at the deployed commit; otherwise that merge precedes it.
            _require(rows[0].get('reason') == ('equal' if merge == commit else 'ancestor'),
                     'live deploy check does not match the pointer merge and planned commit')
        else:
            _require(rows[0].get('reason') == 'identical', f'live check did not serve the pinned {check}')
        if check == 'survey':
            key = f'feeds/tiles/relief/{REGION}/{envelope}/survey/{pins["wire"]["sha256"]}.geojson.br'
            _require(rows[0].get('key') == key and all(rows[0].get(k) == v for k, v in pins.items()),
                     'live survey is not bound to this envelope and pointer')
    return dict(region=REGION, commit=commit, pointer_sha256=digest, envelope_sha256=envelope)


def _shots(capture, origin, expected):
    document = _document(capture)
    rows = document.get('shots')
    _require(document.get('schema') == 'sc-morro-stage-phone/1' and isinstance(rows, list) and len(rows) == len(VIEWS),
             'capture must contain six hosted phone views')
    remaining, digests, result = set(VIEWS), set(), []
    root = capture.parent.resolve()
    for row in rows:
        _require(isinstance(row, dict), 'shot must be a JSON object')
        theme, zoom = row.get('theme'), row.get('zoom')
        _require(isinstance(theme, str) and type(zoom) is int and (theme, zoom) in remaining,
                 'missing, duplicate or unexpected theme and zoom')
        remaining.remove((theme, zoom))
        label = f'{theme}-phone-z{zoom}'
        url = row.get('url')
        _require(isinstance(url, str) and url.startswith(origin + '/'),
                 f'{label}: not captured on the authorized stage origin')
        _require(all(row.get(k) == v for k, v in expected.items()), f'{label}: another region, deployment or release')
        viewport = row.get('viewport')
        _require(row.get('layers_closed') is True and isinstance(viewport, list) and len(viewport) == 2
                 and all(type(n) is int for n in viewport) and 0 < viewport[0] <= 480 and viewport[0] < viewport[1],
                 f'{label}: expected a portrait phone with Layers closed')
        path = root / f'{label}.png'
        _require(path.resolve() == path, f'{label}: screenshot must be a file next to the receipt')
        png = _read(path, 8 << 20)
        digest = sha256(png).hexdigest()
        _require(digest == row.get('png_sha256') and digest not in digests, f'{label}: changed or reused screenshot')
        _require(_png_size(png) == tuple(viewport), f'{label}: PNG must match phone viewport')
        digests.add(digest)
        result.append(dict(theme=theme, zoom=zoom, file=path.name, png_sha256=digest))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stage-origin', required=True, help='authorized isolated hosted origin (no trailing slash)')
    parser.add_argument('--envelope-sha256', required=True, help='exact envelope fed to R8, independent of capture')
    parser.add_argument('--repo', type=Path, default=Path('.'), help='clone root holding the planned commit (default .)')
    for flag in ('--stage-plan', '--pointer', '--live', '--capture'):
        parser.add_argument(flag, required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        expected = _stage(args)
        shots = _shots(args.capture, args.stage_origin, expected)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'FAIL Morro phone evidence: {exc}', file=sys.stderr)
        return 1
    print(json.dumps(dict(schema='sc-morro-stage-phone-check/1', stage_origin=args.stage_origin, **expected, shots=shots)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
