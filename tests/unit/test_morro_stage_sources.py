"""The publication check joins the saved page to both reviewed contour products."""
from hashlib import sha256
import json

import pytest

from scripts.relief.morro_stage_sources import check, main
from skippercast.platform.contracts import OWNER_DISPLAY_BASIS

STYLE = 'b' * 64
CREDIT = 'NOAA & partners; lidar DEM 2022'
HTML_CREDIT = 'Credit: NOAA &amp; partners; lidar DEM 2022'


def _source(ident, title):
    return {'id': ident, 'name': title, 'provider': 'NOAA',
            'rights': {'public_display': 'allowed', 'attribution': CREDIT}}


def _row(title, date=''):
    return (f'<li><strong>{title}</strong> · NOAA<br>'
            f'Provides: Seabed depth{date}<br>{HTML_CREDIT} · <a>Source page</a></li>')


def _page(shading, contours):
    return ('<section id="data-sources"><h3>In use on live layers</h3>'
            '<h4 id="region-morro-bay">Morro Bay</h4>'
            f'<h5>Depth shading</h5><ul>{shading}</ul>'
            f'<h5>Depth contours</h5><ul>{contours}</ul>'
            '<h4 id="region-other">Another region</h4>'
            f'<h5>Depth contours</h5><ul>{_row("Overview DEM")}</ul></section>')


def _contours(ident, date, *, overview):
    provenance = {'region_id': 'morro-bay', 'set': 'ft-v3', 'units': 'ft', 'contours': STYLE, 'features': 1,
                  'sources': [{'source_id': ident, 'survey_date': date, 'attribution': CREDIT}]}
    if overview:
        provenance['overview'] = {'max_zoom': 12}
    return {'type': 'FeatureCollection', 'provenance': provenance,
            'features': [{'properties': {'source_id': ident, 'survey_date': date}}]}


@pytest.fixture
def candidate(tmp_path):
    args = {}
    catalogue = {'schema_version': 1,
                 'sources': [_source('shade', '2022 Survey DEM'), _source('wide', 'Overview DEM'),
                             _source('detail', 'Detailed DEM')]}
    for name, doc in {
        'catalogue': catalogue,
        'release': {'schema': 'sc-relief-release/1', 'region': 'morro-bay', 'private': False,
                    'style': {'contours': STYLE},
                    'sources': [{'id': 'shade', 'attribution': CREDIT, 'survey_dates': ['unstated']}]},
        'overview': _contours('wide', 'unstated', overview=True),
        'detail': _contours('detail', '2011', overview=False),
    }.items():
        raw = json.dumps(doc).encode()
        path = tmp_path / f'{name}.json'
        path.write_bytes(raw)
        args[name] = path
        if name != 'catalogue':
            args[f'{name}_sha256'] = sha256(raw).hexdigest()
    args['page'] = tmp_path / 'sources.html'
    args['page'].write_text(_page(_row('2022 Survey DEM'), _row('Overview DEM') + _row('Detailed DEM', ' · Date: survey 2011')), encoding='utf-8')
    return args


def test_cli_checks_both_contour_levels_and_year_in_product_name_is_not_a_survey_date(candidate, capsys):
    # Real sources use years in product names/credits; a claim in the date field is different.
    argv = [part for key, value in candidate.items() for part in ('--' + key.replace('_', '-'), str(value))]
    assert main(argv) == 0
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['scope'] == 'saved-sources-html'
    assert receipt['html_sha256'] == sha256(candidate['page'].read_bytes()).hexdigest()
    assert receipt['shading'] == {'shade': ['unstated']}
    assert receipt['contours'] == {'wide': ['unstated'], 'detail': ['2011']}


@pytest.mark.parametrize(('before', 'after', 'error'), [
    # A matching credit in the wrong region is not evidence for the overview asset.
    (_row('Overview DEM'), '', 'Depth contours: missing credits for wide'),
    # An exact title is not a substitute for the required producer credit.
    (HTML_CREDIT, 'Credit: NOAA', 'Depth shading: wrong or missing credit'),
    # The product name is dated, but neither it nor a literal date claim establishes a survey year.
    (_row('2022 Survey DEM'), _row('2022 Survey DEM', ' · Date: survey 2022'), 'unsupported survey'),
    ('Date: survey 2011', 'Date: survey 2012', 'unsupported survey'),
])
def test_saved_page_refuses_missing_credit_or_unsupported_dates(candidate, before, after, error):
    page = candidate['page']
    text = page.read_text(encoding='utf-8')
    assert before in text
    page.write_text(text.replace(before, after, 1), encoding='utf-8')
    with pytest.raises(ValueError, match=error):
        check(**candidate)


def test_valid_overview_cannot_substitute_for_independently_pinned_detail(candidate):
    candidate['detail'] = candidate['overview']
    with pytest.raises(ValueError, match='detail: artifact SHA-256'):
        check(**candidate)


def test_even_pinned_contour_with_unsupported_feature_year_fails(candidate):
    # Copy in feature properties is what Chart actually uses; provenance alone does not prove it.
    path = candidate['detail']
    doc = json.loads(path.read_bytes())
    doc['features'][0]['properties']['survey_date'] = '2022'
    raw = json.dumps(doc).encode()
    path.write_bytes(raw)
    candidate['detail_sha256'] = sha256(raw).hexdigest()
    with pytest.raises(ValueError, match='feature disagrees'):
        check(**candidate)


def test_catalogue_display_decision_does_not_infer_rights_from_allowed_label(candidate):
    # Two real Morro rows have an explicit owner display decision and a separate publication veto.
    path = candidate['catalogue']
    doc = json.loads(path.read_bytes())
    row = doc['sources'][0]
    row['publication_allowed'] = False
    path.write_text(json.dumps(doc), encoding='utf-8')
    with pytest.raises(ValueError, match='allowed catalogue credit'):
        check(**candidate)
    row['rights']['owner_public_display'] = {'decision': 'allowed', 'basis': OWNER_DISPLAY_BASIS}
    path.write_text(json.dumps(doc), encoding='utf-8')
    assert check(**candidate)['shading'] == {'shade': ['unstated']}
