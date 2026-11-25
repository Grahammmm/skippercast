#!/usr/bin/env python3
"""Render a local Morro stage /sources.html from the exact candidate assets.

Pass a reviewed, isolated candidate tree and independent SHA-256 pins from its
release preparation records (not hashes calculated from the inputs here). Use a
new output directory outside the tree. This produces an overlay and prints its
receipt, not a deployment or a hosted /sources verification.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts import build_sources_register as register  # noqa: E402
from skippercast.platform.contracts import indexed, owner_display_cleared  # noqa: E402
from skippercast.platform.depth_contours import UNSTATED_SURVEY_DATE, selected_survey_date  # noqa: E402
from skippercast.relief import package  # noqa: E402

REGION = 'morro-bay'
INPUTS = {
    'pointer': f'catalog/relief/{REGION}.json',
    'overview': f'dist/regions/{REGION}/depth-contours-overview.geojson',
    'detail': f'dist/regions/{REGION}/depth-contours.geojson',
    'catalogue': 'catalog/sources.json',
}


def _pinned(tree, name, expected):
    raw = package.artifact_path(tree, INPUTS[name]).read_bytes()
    if not package.is_sha256(expected) or sha256(raw).hexdigest() != expected:
        raise ValueError(f'{name}: SHA-256 differs from the reviewed pin')
    return package.decode_document(raw)


def _contour_rows(doc, name, style):
    p = doc['provenance']
    if (doc['type'] != 'FeatureCollection' or p['region_id'] != REGION or p['set'] != 'ft-v3'
            or p['units'] != 'ft' or p['contours'] != style or ('overview' in p) != (name == 'overview')
            or 'publication_held' in doc or 'publication_held' in p
            or not doc['features'] or len(doc['features']) != p['features']):
        raise ValueError(f'wrong or held {name} Morro ft-v3 contours')
    return ((r['source_id'], r['attribution'], [r['survey_date']]) for r in p['sources'])


def _credits(sources, rows):
    dates = {}
    for ident, credit, values in rows:
        row = sources.get(ident, {})
        rights = row.get('rights', {})
        if (rights.get('public_display') != 'allowed' or not register.listed(row, live=True)
                or (row.get('publication_allowed') is False and not owner_display_cleared(rights))
                or not isinstance(credit, str) or not credit.strip() or credit != rights.get('attribution')):
            raise ValueError(f'{ident}: not a public catalogue credit matching the artifact')
        if not isinstance(values, list) or not values:
            raise ValueError(f'{ident}: missing survey-date provenance')
        dates.setdefault(ident, set()).update(
            d if d == UNSTATED_SURVEY_DATE else selected_survey_date({'survey_date': d}) for d in values
        )
    if not dates:
        raise ValueError('candidate layer has no source credits')
    extras = {}
    for ident, values in dates.items():
        row = sources[ident]
        catalog_date = row.get('survey_date') or row.get('survey_year')
        if catalog_date:
            if values != {str(catalog_date)} or UNSTATED_SURVEY_DATE in values:
                raise ValueError(f'{ident}: unsupported catalogue survey date in candidate layer')
            extras[ident] = ''  # the register already renders the date from the catalogue
        elif values == {UNSTATED_SURVEY_DATE}:
            extras[ident] = 'survey date not stated'
        elif len(values) == 1:
            extras[ident] = 'survey ' + next(iter(values))
        else:
            extras[ident] = ''  # no single date is supported by this layer
    return extras


def render(tree, pins):
    """Return (overlay bytes, local receipt); never write to the candidate tree."""
    pointer, overview, detail, catalogue = (_pinned(tree, name, pins[name]) for name in INPUTS)
    if (pointer['region'] != REGION or pointer['status'] != 'reviewed' or pointer['private'] is not False
            or not package.is_sha256(pointer['release_sha256'])):
        raise ValueError('expected a reviewed public Morro pointer')
    style = pointer['style']['contours']
    if not package.is_sha256(style):
        raise ValueError('Morro pointer does not pin a contour style')
    data = register.collect(tree)
    if data['sources'] != indexed(catalogue, 'sources'):
        raise ValueError('source register did not use the pinned catalogue')
    morro = next((r for r in data['regions'] if r['id'] == REGION), None)
    if morro is None:
        raise ValueError('source register does not include Morro Bay')
    shading = _credits(data['sources'], ((r['id'], r['attribution'], r['survey_dates']) for r in pointer['sources']))
    contours = _credits(data['sources'], (*_contour_rows(detail, 'detail', style),
                                         *_contour_rows(overview, 'overview', style)))
    morro['depth_detail'] = register._depth_detail(pointer)
    morro['layers'].update({register.DEPTH_SHADING: shading, register.DEPTH_CONTOURS: contours})
    block, _ = register.render(data)
    source_page = package.artifact_path(tree, register.PAGE.as_posix()).read_text(encoding='utf-8')
    html = register.splice(source_page, block).encode('utf-8')
    return html, {'schema': 'sc-morro-sources-overlay/1', 'scope': 'stage-local only', 'region': REGION,
                  **{f'{name}_sha256': pins[name] for name in INPUTS},
                  'release_sha256': pointer['release_sha256'], 'html_sha256': sha256(html).hexdigest(),
                  'shading_sources': list(shading), 'contour_sources': list(contours)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True, help='reviewed isolated candidate tree')
    parser.add_argument('--out', type=Path, required=True, help='new output directory outside both checkouts')
    for name in INPUTS:
        parser.add_argument(f'--{name}-sha256', required=True)
    args = parser.parse_args(argv)
    try:
        tree, out = args.tree.resolve(strict=True), args.out.resolve()
        if any(out.is_relative_to(root) for root in (tree, ROOT)):
            raise ValueError('output must be outside the controller and candidate trees')
        html, receipt = render(tree, {name: getattr(args, f'{name}_sha256') for name in INPUTS})
        out.mkdir()
        with (out / 'sources.html').open('xb') as file:
            file.write(html)
    except (OSError, ValueError, KeyError, TypeError, register.RegisterError) as error:
        print(f'Morro sources overlay held: {error}', file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
