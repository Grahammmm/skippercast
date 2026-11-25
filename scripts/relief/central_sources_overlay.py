#!/usr/bin/env python3
"""Render a local STAGE /sources.html with credits for the six Central Coast regions.

Companion of morro_sources_overlay.py (same register, same credit checks), for the Central regions only. Pass a
reviewed, isolated candidate tree and independent SHA-256 pins (a JSON file written from the release preparation
records, not hashes calculated from the inputs here):

  {"tree": "<tree digest of the whole reviewed candidate tree>",
   "catalogue": "<sha256 of catalog/sources.json>",
   "regions": {"<region id>": {"pointer": "<sha256>", "overview": "<sha256>", "detail": "<sha256>"}, ...}}

The `tree` pin binds every file the render can read: the register collector reads region configs, other pointers,
contours and runtime assets, and `dist/sources.html` is spliced verbatim outside the generated block, so a per-input
pin alone would let an edit elsewhere in the tree change the output. The digest is recorded when the candidate tree is
reviewed (`--print-tree-digest` on that reviewed tree), never taken from the tree being rendered. Any file added,
removed or changed (the `.git` directory at the tree root aside) makes the render refuse without writing output.

A region with `overview` and `detail` pins is rendered with shading and contour credits from its published contour pair.
A region with only a `pointer` pin is terrain only: shading credits, and no contour row. Giving only one of the two
contour pins is refused. Use a new output directory outside the tree. This produces an overlay and prints its receipt,
not a deployment or a hosted /sources verification.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import build_sources_register as register  # noqa: E402
from scripts.relief.central_stage_handoff import CENTRAL_RELEASES  # noqa: E402
from scripts.relief.morro_sources_overlay import _credits  # noqa: E402
from skippercast.platform.contracts import indexed  # noqa: E402
from skippercast.relief import package  # noqa: E402

CATALOGUE = 'catalog/sources.json'


def _path(region, name):
    return {'pointer': f'catalog/relief/{region}.json',
            'overview': f'dist/regions/{region}/depth-contours-overview.geojson',
            'detail': f'dist/regions/{region}/depth-contours.geojson'}[name]


def tree_digest(tree):
    """SHA-256 over every path and content below tree (symlinks by target); the root `.git` directory is not content.

    Refuses anything that is not a regular file, directory or symlink, and any symlink that does not resolve to a
    path inside the tree (outside it, into the root `.git`, dangling or looping): the contents behind such a link are
    not hashed here, so an edit there would change the render while the digest stayed the same. A link that stays
    inside the tree is safe because the real file or directory it reaches is walked and hashed at its own path.
    """
    tree = Path(tree).resolve(strict=True)
    git = tree / '.git'
    lines = []
    for here, dirs, files in os.walk(tree, followlinks=False):
        if Path(here) == tree and '.git' in dirs and not git.is_symlink():
            dirs.remove('.git')
        dirs.sort()
        for name in sorted(files) + [d for d in dirs if (Path(here) / d).is_symlink()]:
            path = Path(here) / name
            relative = path.relative_to(tree).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                try:
                    target = path.resolve(strict=True)
                except (OSError, RuntimeError):
                    raise ValueError(f'{relative}: symlink does not resolve') from None
                if not target.is_relative_to(tree) or target == git or target.is_relative_to(git):
                    raise ValueError(f'{relative}: symlink leaves the reviewed tree (its target is not pinned)')
                lines.append(f'l {sha256(os.readlink(path).encode()).hexdigest()} {relative}\n')
            elif stat.S_ISREG(mode):
                lines.append(f'f {sha256(path.read_bytes()).hexdigest()} {relative}\n')
            else:
                raise ValueError(f'{relative}: not a regular file or symlink')
    return sha256(''.join(sorted(lines)).encode()).hexdigest()


def _pinned(tree, relative, expected, label):
    raw = package.artifact_path(tree, relative).read_bytes()
    if not package.is_sha256(expected) or sha256(raw).hexdigest() != expected:
        raise ValueError(f'{label}: SHA-256 differs from the reviewed pin')
    return package.decode_document(raw)


def _contour_rows(doc, region, name, style):
    p = doc['provenance']
    if (doc['type'] != 'FeatureCollection' or p['region_id'] != region or p['set'] != 'ft-v3'
            or p['units'] != 'ft' or p['contours'] != style or ('overview' in p) != (name == 'overview')
            or 'publication_held' in doc or 'publication_held' in p
            or not doc['features'] or len(doc['features']) != p['features']):
        raise ValueError(f'wrong or held {name} ft-v3 contours for {region}')
    return ((r['source_id'], r['attribution'], [r['survey_date']]) for r in p['sources'])


def render(tree, pins):
    """Return (overlay bytes, local receipt); never write to the candidate tree."""
    regions = pins['regions']
    if not package.is_sha256(pins.get('tree')) or tree_digest(tree) != pins['tree']:
        raise ValueError('tree: SHA-256 differs from the reviewed pin (or no tree pin was given)')
    if not isinstance(regions, dict) or not regions or not set(regions) <= set(CENTRAL_RELEASES):
        raise ValueError('pins must name Central Coast regions only')
    catalogue = _pinned(tree, CATALOGUE, pins['catalogue'], 'catalogue')
    data = register.collect(tree)
    if data['sources'] != indexed(catalogue, 'sources'):
        raise ValueError('source register did not use the pinned catalogue')
    receipt_rows = {}
    for region in sorted(regions):
        pin = regions[region]
        if set(pin) - {'pointer', 'overview', 'detail'} or 'pointer' not in pin or ('overview' in pin) != ('detail' in pin):
            raise ValueError(f'{region}: pins must be a pointer, optionally with both overview and detail')
        pointer = _pinned(tree, _path(region, 'pointer'), pin['pointer'], f'{region} pointer')
        if (pointer['region'] != region or pointer['status'] != 'reviewed' or pointer['private'] is not False
                or not package.is_sha256(pointer['release_sha256'])):
            raise ValueError(f'expected a reviewed public pointer for {region}')
        row = next((r for r in data['regions'] if r['id'] == region), None)
        if row is None:
            raise ValueError(f'source register does not include {region}')
        shading = _credits(data['sources'], ((r['id'], r['attribution'], r['survey_dates']) for r in pointer['sources']))
        row['layers'].pop(register.DEPTH_CONTOURS, None)  # terrain only until a contour pair is pinned
        row['layers'][register.DEPTH_SHADING] = shading
        contours = {}
        if 'overview' in pin:
            style = pointer['style']['contours']
            if not package.is_sha256(style):
                raise ValueError(f'{region} pointer does not pin a contour style')
            docs = {name: _pinned(tree, _path(region, name), pin[name], f'{region} {name}') for name in ('detail', 'overview')}
            contours = _credits(data['sources'], (*_contour_rows(docs['detail'], region, 'detail', style),
                                                 *_contour_rows(docs['overview'], region, 'overview', style)))
            row['layers'][register.DEPTH_CONTOURS] = contours
        row['depth_detail'] = register._depth_detail(pointer)
        receipt_rows[region] = {**{k: v for k, v in pin.items()}, 'release_sha256': pointer['release_sha256'],
                                'shading_sources': list(shading), 'contour_sources': list(contours)}
    block, _ = register.render(data)
    source_page = package.artifact_path(tree, register.PAGE.as_posix()).read_text(encoding='utf-8')
    html = register.splice(source_page, block).encode('utf-8')
    if tree_digest(tree) != pins['tree']:
        raise ValueError('tree: changed while the overlay was rendered')
    return html, {'schema': 'sc-central-sources-overlay/1', 'scope': 'stage-local only',
                  'tree_sha256': pins['tree'], 'catalogue_sha256': pins['catalogue'], 'html_sha256': sha256(html).hexdigest(),
                  'regions': receipt_rows}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True, help='reviewed isolated candidate tree')
    parser.add_argument('--out', type=Path, help='new output directory outside both checkouts')
    parser.add_argument('--pins', type=Path, help='independently supplied pin file (JSON)')
    parser.add_argument('--print-tree-digest', action='store_true',
                        help='print the tree digest of the reviewed tree (release preparation) and stop')
    args = parser.parse_args(argv)
    try:
        tree = args.tree.resolve(strict=True)
        if args.print_tree_digest:
            print(tree_digest(tree))
            return 0
        if args.out is None or args.pins is None:
            parser.error('--out and --pins are required to render')
        out = args.out.resolve()
        if any(out.is_relative_to(root) for root in (tree, ROOT)):
            raise ValueError('output must be outside the controller and candidate trees')
        html, receipt = render(tree, json.loads(args.pins.read_text(encoding='utf-8')))
        out.mkdir()
        with (out / 'sources.html').open('xb') as file:
            file.write(html)
    except (OSError, ValueError, KeyError, TypeError, register.RegisterError) as error:
        print(f'Central sources overlay held: {error}', file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
