#!/usr/bin/env python3
"""Check saved /sources HTML against independently pinned Morro v2 artifacts.

Use the reviewed package hash and both contour output hashes, not hashes calculated
from the files being checked. This does not fetch a page or certify its origin;
the preview capture must independently bind the HTML to the hosted deployment.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

from skippercast.platform.contracts import indexed, owner_display_cleared  # noqa: E402
from skippercast.platform.depth_contours import UNSTATED_SURVEY_DATE, selected_survey_date  # noqa: E402
from skippercast.relief.package import RELEASE_SCHEMA, decode_document, is_sha256  # noqa: E402

REGION = 'morro-bay'
SHADING = 'Depth shading'
CONTOURS = 'Depth contours'


def _pinned(path, expected, label):
    raw = path.read_bytes()
    if not is_sha256(expected) or sha256(raw).hexdigest() != expected:
        raise ValueError(f'{label}: artifact SHA-256 differs from the reviewed pin')
    return decode_document(raw)


def _credit(catalogue, ident, attribution):
    row = catalogue.get(ident, {})
    rights = row.get('rights', {})
    credit = rights.get('attribution')
    if (rights.get('public_display') != 'allowed'
            or (row.get('publication_allowed') is False and not owner_display_cleared(rights))
            or not isinstance(credit, str) or not credit.strip() or attribution != credit):
        raise ValueError(f'{ident}: artifact attribution differs from an allowed catalogue credit')


def _dates(values):
    if not isinstance(values, list) or not values:
        raise ValueError('missing artifact survey-date provenance')
    return {value if value == UNSTATED_SURVEY_DATE else selected_survey_date({'survey_date': value})
            for value in values}


def _contours(document, style_digest, catalogue, *, overview):
    provenance = document['provenance']
    if (document['type'] != 'FeatureCollection' or provenance['region_id'] != REGION
            or provenance['set'] != 'ft-v3' or provenance['units'] != 'ft'
            or provenance['contours'] != style_digest or ('overview' in provenance) != overview
            or 'publication_held' in document or 'publication_held' in provenance):
        raise ValueError('wrong or held Morro ft-v3 contour artifact')
    dates = {}
    for entry in provenance['sources']:
        ident = entry['source_id']
        if ident in dates:
            raise ValueError(f'duplicate contour source {ident}')
        _credit(catalogue, ident, entry['attribution'])
        dates[ident] = entry['survey_date']
    features = document['features']
    if not features or len(features) != provenance['features']:
        raise ValueError('empty or incomplete ft-v3 contour artifact')
    for feature in features:
        properties = feature['properties']
        if ('publication_held' in feature or 'publication_held' in properties
                or dates[properties['source_id']] != properties['survey_date']):
            raise ValueError('contour feature disagrees with source survey-date provenance or is held')
    return {ident: _dates([value]) for ident, value in dates.items()}


def _clean(text):
    return ' '.join(text.split())


class _MorroRows(HTMLParser):
    """Read text from generated live-layer rows, not credits in other regions or eligible lists."""

    def __init__(self, page):
        super().__init__()
        self.sections = []
        self.morro = False
        self.heading = None
        self.layer = None
        self.item = None
        self.rows = defaultdict(list)
        self.feed(page)
        self.close()

    def handle_starttag(self, tag, attrs):
        ident = dict(attrs).get('id')
        if tag == 'section':
            self.sections.append(ident)
        if 'data-sources' not in self.sections:
            return
        if tag in ('h2', 'h3', 'h4'):
            self.morro = tag == 'h4' and ident == 'region-morro-bay'
            self.layer = None
        elif self.morro and tag == 'h5':
            self.heading = []
        elif self.layer in (SHADING, CONTOURS) and tag == 'li':
            self.item = ['']
        elif self.item is not None and tag == 'br':
            self.item.append('')

    def handle_endtag(self, tag):
        if tag == 'h5' and self.heading is not None:
            self.layer = _clean(''.join(self.heading))
            self.heading = None
        elif tag == 'li' and self.item is not None:
            self.rows[self.layer].append([_clean(line) for line in self.item])
            self.item = None
        elif tag == 'section' and self.sections:
            if self.sections.pop() == 'data-sources':
                self.morro = False
                self.layer = None

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)
        elif self.item is not None:
            self.item[-1] += data


def _check_rows(rows, layer, expected, catalogue):
    headers = {_clean(f"{catalogue[i]['name']} · {catalogue[i]['provider']}"): i for i in expected}
    seen = set()
    for header, *facts in rows.get(layer, []):
        ident = headers.get(header)
        if ident is None or ident in seen:
            raise ValueError(f'{layer}: stale, unexpected or duplicate source row: {header!r}')
        seen.add(ident)
        row = catalogue[ident]
        credit = _clean('Credit: ' + row['rights']['attribution'])
        if not facts or facts.pop().removesuffix(' · Source page') != credit:
            raise ValueError(f'{layer}: wrong or missing credit for {ident}')
        claims = []
        for field in ' · '.join(facts).split(' · '):
            if field.startswith('Date: '):
                claims.extend(field.removeprefix('Date: ').split('; '))
            elif field and (not field.startswith('Provides: ') or re.search(r'\bsurvey(?:ed)?\s+\d', field, re.I)):
                raise ValueError(f'{layer}: unrecognized source facts for {ident}')
        for claim in claims:
            if claim == 'survey date not stated' and expected[ident] == {UNSTATED_SURVEY_DATE}:
                continue
            if row.get('publication_date') and claim == f"published {row['publication_date']}":
                continue
            if claim.startswith('survey ') and expected[ident] == {claim.removeprefix('survey ')} and claim != 'survey unstated':
                continue
            raise ValueError(f'{layer}: unsupported survey or publication date for {ident}: {claim!r}')
    if seen != expected.keys():
        raise ValueError(f'{layer}: missing credits for {", ".join(sorted(expected.keys() - seen))}')


def check(page, catalogue, release, overview, detail, *, release_sha256, overview_sha256, detail_sha256):
    """Return a byte-bound, offline evidence receipt; all inputs are read-only."""
    raw_catalogue = catalogue.read_bytes()
    sources = indexed(decode_document(raw_catalogue), 'sources')
    package = _pinned(release, release_sha256, 'relief release')
    if package['schema'] != RELEASE_SCHEMA or package['region'] != REGION or package['private'] is not False:
        raise ValueError('expected a public Morro relief release')
    style = (package.get('style') or {}).get('contours')
    if not is_sha256(style):
        raise ValueError('relief release does not pin an ft-v3 contour style')
    shading = {}
    for row in package['sources']:
        ident = row['id']
        if ident in shading:
            raise ValueError(f'duplicate shading source {ident}')
        _credit(sources, ident, row['attribution'])
        shading[ident] = _dates(row['survey_dates'])
    if not shading:
        raise ValueError('relief release has no shading sources')
    contour_dates = {}
    for is_overview, path, digest, name in ((True, overview, overview_sha256, 'overview'),
                                            (False, detail, detail_sha256, 'detail')):
        dates = _contours(_pinned(path, digest, name), style, sources, overview=is_overview)
        for ident, values in dates.items():
            contour_dates.setdefault(ident, set()).update(values)
    html = page.read_bytes()
    rows = _MorroRows(html.decode('utf-8')).rows
    for layer, expected in ((SHADING, shading), (CONTOURS, contour_dates)):
        _check_rows(rows, layer, expected, sources)
    return {'schema': 'sc-morro-sources-check/1', 'scope': 'saved-sources-html', 'region': REGION,
            'release_sha256': release_sha256, 'overview_sha256': overview_sha256, 'detail_sha256': detail_sha256,
            'catalogue_sha256': sha256(raw_catalogue).hexdigest(), 'html_sha256': sha256(html).hexdigest(),
            'shading': {i: sorted(dates) for i, dates in shading.items()},
            'contours': {i: sorted(dates) for i, dates in contour_dates.items()}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('page', 'catalogue', 'release', 'overview', 'detail'):
        parser.add_argument(f'--{name}', type=Path, required=True)
    for name in ('release', 'overview', 'detail'):
        parser.add_argument(f'--{name}-sha256', required=True)
    try:
        receipt = check(**vars(parser.parse_args(argv)))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
