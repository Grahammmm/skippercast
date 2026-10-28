"""PC-5b: a bounded Northern preview, not permission to fish."""
import json
from copy import deepcopy
from datetime import datetime

import pytest

from skippercast.pipeline.regulation_review import coverage
from skippercast.pipeline.regulations import content_hash, regional_source_ids, validate_region_binding
from tests._support import ROOT


REGIONS = ('crescent-city', 'humboldt-bay-cape-mendocino', 'trinidad-klamath')


def read(path):
    return json.loads((ROOT / path).read_text())


def test_final_decision_binds_all_species_sources_and_three_footprints():
    rules = read('dist/data/regulations-northern.json')
    jurisdiction = read('jurisdictions/california-northern.json')
    decision = read(rules['review_record'])
    assert rules['approved_rules_content_sha256'] == content_hash(rules) == decision['rules_content_sha256']
    assert set(decision['reviewed_species']) == set(rules['species'])
    assert set(decision['sources']) == set(rules['sources'])
    assert {r['id'] for r in rules['reviewed_regions']} == set(REGIONS)
    assert decision['reviewed_regions'] == rules['reviewed_regions']
    assert rules['review_required'] == []
    for ident, choice in decision['sources'].items():
        assert choice['decision'] == 'approve'
        assert choice['content_sha256'] == rules['sources'][ident]['approved_content_sha256']
    for rid in REGIONS:
        validate_region_binding(jurisdiction, rules, read(f'regions/{rid}/region.json'))


def test_preview_remains_unqualified_and_does_not_gain_fleet_coverage():
    region = read('regions/trinidad-klamath/region.json')
    assert region['status'] == 'preview'
    assert region['coverage']['regulations']['status'] == 'partial'
    for key in ('charters', 'ais_evidence', 'commercial_ais', 'daily_evidence'):
        assert region['assets'][key] is None
    atlas = read('dist/' + region['assets']['atlas'])
    assert all(atlas[key] == [] for key in ('targets', 'areas', 'drifts'))
    assert 'ready' not in {entry['status'] for entry in region['coverage'].values()}
    coast = next(c for c in read('catalog/coasts.json')['regions'] if c['id'] == 'northern')
    assert set(REGIONS) <= set(coast['packages'])


def test_northern_halibut_fillet_exception_cannot_be_imported_from_south():
    profile = read('dist/data/regulations-northern.json')['species']['halibut']
    text = ' '.join(profile['details'])
    assert 'Do not fillet, steak or cut' in text
    assert 'Point Arena' in text
    assert '16¾' not in text
    assert profile['bag'].startswith('2 ')
    assert profile['size'].startswith('22 in')


def test_reading_rock_and_klamath_notices_are_method_specific():
    rules = read('dist/data/regulations-northern.json')
    notices = {n['id']: n for n in rules['area_notices']}
    assert 'SMR prohibits' in notices['northern-mpas']['note']
    for phrase in ('trolling', 'dip net', 'hoop net', 'whole'):
        assert phrase in notices['northern-mpas']['note']
    notice = notices['klamath-salmon-closures']
    for phrase in ('year-round', 'August', 'Control Zone', '2026', 'not'):
        assert phrase in notice['note']
    assert set(notice['source_ids']) == {'rules-book', 'rules-salmon', 'rules-salmon-pdf', 'rules-inseason'}
    region = read('regions/trinidad-klamath/region.json')
    assert notice['id'] in region['map']['region_notice_ids']


@pytest.mark.parametrize('rid', REGIONS)
def test_shared_hold_stays_visible_in_new_and_existing_regions(rid):
    rules = read('dist/data/regulations-northern.json')
    jurisdiction = read('jurisdictions/california-northern.json')
    region = read(f'regions/{rid}/region.json')
    scope = regional_source_ids(jurisdiction, rules, region)
    sources = {
        ident: {'status': 'ok', 'url': spec['url'], 'data_retrieved_at': rules['reviewed_at'],
                'data': {'content_sha256': spec['approved_content_sha256'], 'normalization': spec['normalization']}}
        for ident, spec in rules['sources'].items()
    }
    held = deepcopy(rules)
    held['sources']['rules-proposals']['approved_content_sha256'] = None
    now = datetime.fromisoformat(rules['reviewed_at'].replace('Z', '+00:00'))
    health = coverage(held, sources, now, scope)
    assert 'rules-proposals' in health['review_required']
    assert all('rules-proposals' in p['issues'] for p in health['species'].values())
    assert health['checks']['rules-proposals']['status'] != 'unchanged'
