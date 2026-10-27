"""SC53: synthetic producer-shaped rows, full source_rights module, no URL IO."""
from copy import deepcopy
from datetime import date
import json

import pytest

from skippercast.seafloor import rights
from tests._support import ROOT

TODAY = date(2026, 9, 28)
PREFIXES = (
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/',
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/',
)
EXACT_PRODUCTS = (
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/macginitie/'
    'PointLobos/multibeam/data/version2/products/PointLobos_additional_products.tar.gz',
    'https://data.ngdc.noaa.gov/platforms/ocean/ships/macginitie/'
    'MonasteryBeach/multibeam/data/version2/products/Monastery_additional_products.tar.gz',
)
CREDIT = ('Data used in this study were acquired, processed, archived, and distributed '
          'by the Seafloor Mapping Lab of California State University Monterey Bay.')
NOTICE = ('Public noncommercial use only; for-profit use requires express CSUMB SFML '
          'permission. Not for navigation.')
POLICY = 'https://csumb.edu/undersea/sfml-data-library/'
LICENSE = 'csumb-public-use-noncommercial'
RIGHTS_ERROR = '^Source publication rights are unqualified or conflict with producer review$'
ORDINARY_PATHS = (
    'BSS_Block03/original.tar.gz',
    'SCC_Block01/multibeam/data/version2/products/SCC_Block01_additional_products.tar.gz',
    'original.tar.gz', 'survey-v2.1/depth_grid_5m.zip',
    'survey~original/grid+metadata.tar.gz', 'survey/data(1).tar.gz',
)
BAD_PATHS = (
    '../another_cruise/original.tar.gz', './original.tar.gz',
    'survey/../../another_cruise/original.tar.gz', 'survey/./original.tar.gz',
    'survey/..', 'survey/.', '%2e%2e/another_cruise/original.tar.gz',
    '%2E%2E/another_cruise/original.tar.gz', '.%2e/another_cruise/original.tar.gz',
    '%2e./another_cruise/original.tar.gz', '%252e%252e/another_cruise/original.tar.gz',
    '%252E%252E/another_cruise/original.tar.gz', '%2fother/original.tar.gz',
    '%2Fother/original.tar.gz', '%252fother/original.tar.gz',
    'survey%2f..%2foriginal.tar.gz', 'survey%5coriginal.tar.gz',
    'survey%5Coriginal.tar.gz', 'survey%255coriginal.tar.gz',
    'survey\\..\\original.tar.gz', 'survey\\original.tar.gz',
    'original.tar.gz?redirect=another_cruise', 'original.tar.gz?',
    'original.tar.gz#another_cruise', 'original.tar.gz#',
    'survey//original.tar.gz', '/original.tar.gz', '',
    'bad%/original.tar.gz', 'bad%2/original.tar.gz', 'bad%zz/original.tar.gz',
    'encoded%20space/original.tar.gz', 'survey/original.tar.gz\n',
    'survey/ori\tginal.tar.gz', 'survey/ori\rginal.tar.gz',
    'survey/original\x00.tar.gz', 'survey/white space.tar.gz',
    'survey/fullwidth\uff0e.tar.gz',
    'survey/<original>.tar.gz', 'survey/"original".tar.gz',
    'survey/[original].tar.gz', 'survey/{original}.tar.gz',
    'survey/original|metadata.tar.gz', 'survey/original^metadata.tar.gz',
    'survey/`original`.tar.gz',
)


def source_row(url):
    # Keep the actual supported inventory shape, but synthetic producer identity,
    # bytes/hash, URL and review; no source acquisition or source promotion.
    inventory = json.loads((ROOT / 'catalog/surveys.json').read_text())
    row = deepcopy(next(r for r in inventory['surveys'] if r['status'] == 'usable'))
    row.update(id='sc53-synthetic', publisher='CSUMB (NOAA NCEI distributor)',
               license=LICENSE, url=url, sha256='a' * 64, bytes=1234)
    row['rights_review'] = {
        'producer': 'CSUMB SFML', 'policy_url': POLICY, 'source_sha256': row['sha256'],
        'reviewed_on': TODAY.isoformat(), 'allowed_use': 'noncommercial',
        'attribution': CREDIT, 'navigation_use': False,
        'for_profit_permission': 'required-not-obtained',
    }
    return row


def expected_terms(url):
    return {'source_id': 'sc53-synthetic', 'license': LICENSE, 'source_url': url,
            'policy_url': POLICY, 'attribution': CREDIT, 'notice': NOTICE,
            'commercial_use': 'permission-required', 'navigation_use': False,
            'reviewed_on': TODAY.isoformat()}


@pytest.mark.parametrize('prefix', PREFIXES, ids=['harold', 'ventresca'])
@pytest.mark.parametrize('path', ORDINARY_PATHS)
def test_ordinary_original_preserves_complete_restrictive_terms(prefix, path):
    row = source_row(prefix + path)
    before = deepcopy(row)
    assert rights.source_rights(row, today=TODAY) == expected_terms(row['url'])
    assert row == before


@pytest.mark.parametrize('prefix', PREFIXES, ids=['harold', 'ventresca'])
def test_rejects_literal_parent_traversal(prefix):
    row = source_row(prefix + '../another_cruise/original.tar.gz')
    before = deepcopy(row)
    with pytest.raises(ValueError, match=RIGHTS_ERROR):
        rights.source_rights(row, today=TODAY)
    assert row == before


@pytest.mark.parametrize('prefix', PREFIXES, ids=['harold', 'ventresca'])
@pytest.mark.parametrize('path', BAD_PATHS)
def test_rejects_malformed_archive_paths(prefix, path):
    row = source_row(prefix + path)
    before = deepcopy(row)
    with pytest.raises(ValueError, match=RIGHTS_ERROR):
        rights.source_rights(row, today=TODAY)
    assert row == before


@pytest.mark.parametrize('prefix', PREFIXES, ids=['harold', 'ventresca'])
@pytest.mark.parametrize('variant', [
    'http', 'userinfo', 'password', 'host-suffix', 'host-prefix', 'port',
    'uppercase-host', 'uppercase-scheme', 'leading-space', 'leading-control',
    'sibling', 'other-cruise', 'authority-backslash',
])
def test_rejects_authority_and_prefix_aliases(prefix, variant):
    url = prefix + 'original.tar.gz'
    host = 'data.ngdc.noaa.gov'
    url = {
        'http': url.replace('https:', 'http:'),
        'userinfo': url.replace(host, 'reader@' + host),
        'password': url.replace(host, 'reader:inert@' + host),
        'host-suffix': url.replace(host, host + '.evil.test'),
        'host-prefix': url.replace(host, 'evil.' + host),
        'port': url.replace(host, host + ':443'),
        'uppercase-host': url.replace(host, host.upper()),
        'uppercase-scheme': url.replace('https:', 'HTTPS:'),
        'leading-space': ' ' + url,
        'leading-control': '\n' + url,
        'sibling': prefix.rstrip('/') + '-other/original.tar.gz',
        'other-cruise': prefix.rsplit('/', 2)[0] + '/another_cruise/original.tar.gz',
        'authority-backslash': url.replace(host, host + '\\@evil.test'),
    }[variant]
    with pytest.raises(ValueError, match=RIGHTS_ERROR):
        rights.source_rights(source_row(url), today=TODAY)


@pytest.mark.parametrize('url', [None, 17, [], {}, b'https://inert.test/'])
def test_nontext_url_is_unqualified(url):
    with pytest.raises(ValueError, match=RIGHTS_ERROR):
        rights.source_rights(source_row(url), today=TODAY)


@pytest.mark.parametrize('url', EXACT_PRODUCTS)
def test_exact_products_and_frozen_constants(url):
    assert rights.CSUMB_ARCHIVES == PREFIXES
    assert rights.CSUMB_EXACT_ARCHIVES == frozenset(EXACT_PRODUCTS)
    assert rights.source_rights(source_row(url), today=TODAY) == expected_terms(url)


@pytest.mark.parametrize('url', EXACT_PRODUCTS)
@pytest.mark.parametrize('variant', [
    'other-survey', 'parent', 'escaped-parent', 'double-escaped-parent',
    'append-parent', 'query', 'fragment', 'filename', 'sibling', 'host', 'http',
])
def test_exact_product_lookalikes_remain_rejected(url, variant):
    survey = 'PointLobos' if '/PointLobos/' in url else 'MonasteryBeach'
    changed = {
        'other-survey': url.replace('/' + survey + '/', '/OtherSurvey/'),
        'parent': url.replace('/' + survey + '/', '/' + survey + '/../OtherSurvey/'),
        'escaped-parent': url.replace('/' + survey + '/', '/' + survey + '/%2e%2e/OtherSurvey/'),
        'double-escaped-parent': url.replace('/' + survey + '/', '/' + survey + '/%252e%252e/OtherSurvey/'),
        'append-parent': url + '/../OtherSurvey/original.tar.gz',
        'query': url + '?redirect=OtherSurvey', 'fragment': url + '#OtherSurvey',
        'filename': url.rsplit('/', 1)[0] + '/another.tar.gz',
        'sibling': url.replace('/' + survey + '/', '/' + survey + '-other/'),
        'host': url.replace('data.ngdc.noaa.gov/', 'data.ngdc.noaa.gov.evil.test/'),
        'http': url.replace('https:', 'http:'),
    }[variant]
    with pytest.raises(ValueError, match=RIGHTS_ERROR):
        rights.source_rights(source_row(changed), today=TODAY)


@pytest.mark.parametrize('url', [p + 'original.tar.gz' for p in PREFIXES] + list(EXACT_PRODUCTS))
@pytest.mark.parametrize('reviewed_on, message', [
    (None, 'actual dated producer review'), ('2026-99-99', 'actual dated producer review'),
    ('2026-09-29', 'cannot be dated in the future'),
])
def test_review_date_contract_is_unchanged(url, reviewed_on, message):
    row = source_row(url)
    row['rights_review']['reviewed_on'] = reviewed_on
    with pytest.raises(ValueError, match=message):
        rights.source_rights(row, today=TODAY)


@pytest.mark.parametrize('url', [p + 'original.tar.gz' for p in PREFIXES] + list(EXACT_PRODUCTS))
def test_for_profit_and_permission_claims_remain_refused(url):
    row = source_row(url)
    with pytest.raises(ValueError, match='^For-profit publication requires express producer permission$'):
        rights.source_rights(row, use='for-profit', today=TODAY)
    row['rights_review']['for_profit_permission'] = 'obtained'
    with pytest.raises(ValueError, match=RIGHTS_ERROR):
        rights.source_rights(row, today=TODAY)


def test_fixture_roundtrip_under_test_local_root(tmp_path):
    path = tmp_path / 'synthetic-row.json'
    row = source_row(PREFIXES[0] + 'original.tar.gz')
    path.write_text(json.dumps(row))
    raw = path.read_bytes()
    assert rights.source_rights(json.loads(raw), today=TODAY) == expected_terms(row['url'])
    assert path.read_bytes() == raw
