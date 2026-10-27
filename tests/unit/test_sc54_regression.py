"""Full-module, synthetic-only coverage of finite attribution iterables."""
from copy import deepcopy
import json
from unittest.mock import patch

import pytest
from skippercast.seafloor import rights


class SinglePass:
    """Record consumption and reject any attempt to iterate the input twice."""

    def __init__(self, values):
        self.values = iter(values)
        self.passes = 0
        self.consumed = []

    def __iter__(self):
        self.passes += 1
        if self.passes != 1:
            raise RuntimeError('original input iterated twice')
        return self

    def __next__(self):
        value = next(self.values)
        self.consumed.append(value)
        return value


def contributors():
    federal = {'id': 'usgs', 'license': 'public-domain-us-gov',
               'url': 'https://example.test/original-government',
               'publisher': 'Synthetic government producer',
               'adapter_review': {'rights_source_url': 'https://example.test/government-terms'}}
    restricted = {'id': 'csumb', 'license': rights.CSUMB_LICENSE,
                  'url': rights.POINT_LOBOS_ARCHIVE, 'sha256': 'a' * 64,
                  'publisher': 'CSUMB synthetic producer',
                  'rights_review': {'producer': 'CSUMB SFML', 'policy_url': rights.CSUMB_POLICY,
                      'source_sha256': 'a' * 64, 'reviewed_on': '2020-01-01',
                      'allowed_use': 'noncommercial', 'attribution': rights.CSUMB_CREDIT,
                      'navigation_use': False, 'for_profit_permission': 'required-not-obtained'}}
    return {'usgs': federal, 'csumb': restricted}


IDS = ['usgs', 'csumb', 'usgs', 'csumb']
KINDS = ['list', 'tuple', 'generator', 'single-pass']


def input_ids(kind, values):
    if kind == 'list':
        return list(values)
    if kind == 'tuple':
        return tuple(values)
    if kind == 'generator':
        return (value for value in values)
    return SinglePass(values)


def expected_terms(sources):
    return [
        {'source_id': 'csumb', 'license': rights.CSUMB_LICENSE,
         'source_url': rights.POINT_LOBOS_ARCHIVE, 'policy_url': rights.CSUMB_POLICY,
         'attribution': rights.CSUMB_CREDIT, 'notice': rights.CSUMB_NOTICE,
         'commercial_use': 'permission-required', 'navigation_use': False,
         'reviewed_on': '2020-01-01'},
        {'source_id': 'usgs', 'license': 'public-domain-us-gov',
         'source_url': sources['usgs']['url'],
         'policy_url': 'https://example.test/government-terms',
         'attribution': 'Synthetic government producer',
         'notice': 'Original US government data; retain source attribution and survey limitations.'},
    ]


def check_terms(ids):
    sources = contributors()
    before = deepcopy(sources)
    actual = rights.feature_rights(ids, sources)
    assert actual == expected_terms(sources), 'SC54 contributor terms lost or changed'
    assert sources == before


def test_list_positive():
    check_terms(list(IDS))


def test_generator_preservation():
    check_terms(value for value in IDS)


def test_tuple_preservation():
    check_terms(tuple(IDS))


def test_single_pass_preservation():
    ids = SinglePass(IDS)
    check_terms(ids)
    assert ids.passes == 1
    assert ids.consumed == IDS


@pytest.mark.parametrize('kind', KINDS)
def test_empty_rejected(kind):
    sources = contributors()
    before = deepcopy(sources)
    with patch.object(rights, 'source_rights', wraps=rights.source_rights) as terms:
        with pytest.raises(ValueError, match='^Feature source attribution is incomplete$'):
            rights.feature_rights(input_ids(kind, []), sources)
        terms.assert_not_called()
    assert sources == before


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('position', [0, 1, 2], ids=['first', 'middle', 'last'])
def test_unknown_rejected_before_partial_terms(kind, position):
    values = ['usgs', 'csumb']
    values.insert(position, 'missing')
    sources = contributors()
    before = deepcopy(sources)
    with patch.object(rights, 'source_rights', wraps=rights.source_rights) as terms:
        with pytest.raises(ValueError, match='^Feature source attribution is incomplete$'):
            rights.feature_rights(input_ids(kind, values), sources)
        terms.assert_not_called()
    assert sources == before


@pytest.mark.parametrize('kind', KINDS)
def test_restricted_for_profit_rejected(kind):
    sources = contributors()
    before = deepcopy(sources)
    with pytest.raises(ValueError, match='^For-profit publication requires express producer permission$'):
        rights.feature_rights(input_ids(kind, IDS), sources, use='for-profit')
    assert sources == before


@pytest.mark.parametrize('kind', KINDS)
def test_unknown_use_rejected(kind):
    sources = contributors()
    before = deepcopy(sources)
    with pytest.raises(ValueError, match='^Unknown deployment source-use profile$'):
        rights.feature_rights(input_ids(kind, IDS), sources, use='not-a-profile')
    assert sources == before


@pytest.mark.parametrize('kind', KINDS)
def test_government_for_profit_preserved(kind):
    sources = contributors()
    before = deepcopy(sources)
    assert rights.feature_rights(input_ids(kind, ['usgs', 'usgs']), sources, use='for-profit') == [
        expected_terms(sources)[1]]
    assert sources == before


def test_test_local_root_round_trip(tmp_path):
    """Exercise a fresh pytest root without host cache/data dependencies."""
    sources = contributors()
    path = tmp_path / 'synthetic-contributors.json'
    path.write_text(json.dumps(sources), encoding='utf-8')
    original = path.read_bytes()
    loaded = json.loads(original)
    assert rights.feature_rights(iter(IDS), loaded) == expected_terms(sources)
    assert loaded == sources
    assert path.read_bytes() == original
