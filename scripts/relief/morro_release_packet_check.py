#!/usr/bin/env python3
"""Join the six hosted Morro phone captures to the exact R8 release, offline.

Supply the authorized workers.dev origin, the exact candidate's preview plan and
pointer, the R8 envelope SHA-256 and the successful live-check receipt from that
origin. The browser operator's capture.json uses schema sc-morro-stage-phone/1
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
from pathlib import Path
import re
import struct
import sys

REGION = 'morro-bay'
VIEWS = {(theme, zoom) for theme in ('light', 'dark') for zoom in (11, 13, 15)}
STAGE_ORIGIN = re.compile(r'https://([a-z0-9-]+-stage)\.[a-z0-9-]+\.workers\.dev')
PNG_HEADER = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR'
PNG_END = b'\x00\x00\x00\x00IEND\xaeB\x60\x82'


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

    live = _document(args.live)
    checks = live.get('checks')
    _require(live.get('verdict') == 'PASS' and live.get('region') == REGION and live.get('base') == origin
             and live.get('deployed') == commit and isinstance(checks, list)
             and all(isinstance(c, dict) and c.get('status') == 'PASS' for c in checks),
             'live check did not pass on the exact planned origin and commit')
    # Other valid rows repeat names (e.g. digest chunks); these four must be unique.
    for check in ('deploy', 'pointer', 'contours', 'survey'):
        rows = [c for c in checks if c.get('check') == check]
        _require(len(rows) == 1, f'live check must prove {check} exactly once')
        if check != 'deploy':
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
        _require(len(png) >= 45 and png.startswith(PNG_HEADER) and png.endswith(PNG_END)
                 and list(struct.unpack('>II', png[16:24])) == viewport, f'{label}: PNG must match phone viewport')
        digests.add(digest)
        result.append(dict(theme=theme, zoom=zoom, file=path.name, png_sha256=digest))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--stage-origin', required=True, help='authorized isolated hosted origin (no trailing slash)')
    parser.add_argument('--envelope-sha256', required=True, help='exact envelope fed to R8, independent of capture')
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
