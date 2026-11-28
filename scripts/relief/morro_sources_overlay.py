#!/usr/bin/env python3
"""Render a local stage /sources.html from the exact candidate assets of one region.

Morro Bay by default; `--region` names one of the Central Coast regions the Central stage preview may
carry (morro_stage_preview.REGIONS), with the same pins and the same checks. A terrain-only region
(morro_stage_preview.TERRAIN_ONLY_REGIONS) has no contour files: it takes only the pointer and catalogue
pins, its pointer must pin no contour style, and the register may credit it no depth contours.

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
from scripts.relief.morro_stage_preview import REGIONS, TERRAIN_ONLY_REGIONS  # noqa: E402

REGION = 'morro-bay'
CONTOUR_INPUTS = ('overview', 'detail')


def inputs(region):
    """The pinned files for `region`; a terrain-only region has no contour files to pin."""
    if region not in REGIONS:
        raise ValueError('region is not one the stage preview may carry')
    if region in TERRAIN_ONLY_REGIONS:
        return {'pointer': f'catalog/relief/{region}.json', 'catalogue': 'catalog/sources.json'}
    return {
        'pointer': f'catalog/relief/{region}.json',
        'overview': f'dist/regions/{region}/depth-contours-overview.geojson',
        'detail': f'dist/regions/{region}/depth-contours.geojson',
        'catalogue': 'catalog/sources.json',
    }


INPUTS = inputs(REGION)


def _name(region):
    return 'Morro' if region == REGION else region


def _pinned(tree, name, expected, region=REGION):
    raw = package.artifact_path(tree, inputs(region)[name]).read_bytes()
    if not package.is_sha256(expected) or sha256(raw).hexdigest() != expected:
        raise ValueError(f'{name}: SHA-256 differs from the reviewed pin')
    return package.decode_document(raw)


def _contour_rows(doc, name, style, region=REGION):
    p = doc['provenance']
    if (doc['type'] != 'FeatureCollection' or p['region_id'] != region or p['set'] != 'ft-v3'
            or p['units'] != 'ft' or p['contours'] != style or ('overview' in p) != (name == 'overview')
            or 'publication_held' in doc or 'publication_held' in p
            or not doc['features'] or len(doc['features']) != p['features']):
        raise ValueError(f'wrong or held {name} {_name(region)} ft-v3 contours')
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


def render(tree, pins, region=REGION):
    """Return (overlay bytes, local receipt); never write to the candidate tree."""
    names = inputs(region)
    docs = {name: _pinned(tree, name, pins[name], region) for name in names}
    pointer, catalogue = docs['pointer'], docs['catalogue']
    if (pointer['region'] != region or pointer['status'] != 'reviewed' or pointer['private'] is not False
            or not package.is_sha256(pointer['release_sha256'])):
        raise ValueError(f'expected a reviewed public {_name(region)} pointer')
    style = pointer['style']['contours']
    terrain_only = region in TERRAIN_ONLY_REGIONS
    if terrain_only and style is not None:
        raise ValueError(f'{region} is terrain-only but its pointer pins a contour style')
    if not terrain_only and not package.is_sha256(style):
        raise ValueError(f'{_name(region)} pointer does not pin a contour style')
    data = register.collect(tree)
    if data['sources'] != indexed(catalogue, 'sources'):
        raise ValueError('source register did not use the pinned catalogue')
    morro = next((r for r in data['regions'] if r['id'] == region), None)
    if morro is None:
        raise ValueError('source register does not include ' + ('Morro Bay' if region == REGION else region))
    shading = _credits(data['sources'], ((r['id'], r['attribution'], r['survey_dates']) for r in pointer['sources']))
    morro['depth_detail'] = register._depth_detail(pointer)
    morro['layers'][register.DEPTH_SHADING] = shading
    contours = {}
    if terrain_only:
        if morro['layers'].get(register.DEPTH_CONTOURS):
            raise ValueError(f'source register credits depth contours for terrain-only {region}')
    else:
        contours = _credits(data['sources'], (*_contour_rows(docs['detail'], 'detail', style, region),
                                             *_contour_rows(docs['overview'], 'overview', style, region)))
        morro['layers'][register.DEPTH_CONTOURS] = contours
    block, _ = register.render(data)
    source_page = package.artifact_path(tree, register.PAGE.as_posix()).read_text(encoding='utf-8')
    html = register.splice(source_page, block).encode('utf-8')
    return html, {'schema': 'sc-morro-sources-overlay/1', 'scope': 'stage-local only', 'region': region,
                  **{f'{name}_sha256': pins[name] for name in names},
                  'release_sha256': pointer['release_sha256'], 'html_sha256': sha256(html).hexdigest(),
                  'shading_sources': list(shading), 'contour_sources': list(contours)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tree', type=Path, required=True, help='reviewed isolated candidate tree')
    parser.add_argument('--out', type=Path, required=True, help='new output directory outside both checkouts')
    parser.add_argument('--region', default=REGION, choices=REGIONS)
    for name in INPUTS:
        parser.add_argument(f'--{name}-sha256', required=name not in CONTOUR_INPUTS)
    args = parser.parse_args(argv)
    for name in CONTOUR_INPUTS:
        given = getattr(args, f'{name}_sha256') is not None
        if args.region in TERRAIN_ONLY_REGIONS and given:
            parser.error(f'--{name}-sha256 does not apply to terrain-only {args.region}')
        if args.region not in TERRAIN_ONLY_REGIONS and not given:
            parser.error(f'the following arguments are required: --{name}-sha256')
    try:
        tree, out = args.tree.resolve(strict=True), args.out.resolve()
        if any(out.is_relative_to(root) for root in (tree, ROOT)):
            raise ValueError('output must be outside the controller and candidate trees')
        html, receipt = render(tree, {name: getattr(args, f'{name}_sha256') for name in inputs(args.region)},
                               args.region)
        out.mkdir()
        with (out / 'sources.html').open('xb') as file:
            file.write(html)
    except (OSError, ValueError, KeyError, TypeError, register.RegisterError) as error:
        print(f'{_name(args.region)} sources overlay held: {error}', file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
