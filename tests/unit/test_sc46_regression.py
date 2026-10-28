"""SC46: decoded normalized tag shape boundary, with inert raster headers."""
from copy import deepcopy
import json

import pytest

from skippercast.coastal import vertical

SOURCE = 'a' * 64
MISSING = 'normalized_vertical_contract_missing'
INVALID = 'normalized_vertical_lineage_invalid'


class HeaderDataset:
    """Only metadata is available: no raster path, read method or GIS I/O."""

    driver = 'GTiff'
    crs = None
    dtypes = ('float64',)
    nodatavals = (None,)
    units = ('m',)
    scales = (1.0,)
    offsets = (0.0,)
    descriptions = ('depth',)

    def __init__(self, contract=None, *, raw=False, datum='MLLW'):
        self.metadata = {'vertical_sign': 'positive_up' if raw else 'positive_down',
                         'z_units': 'm', 'vertical_datum': datum,
                         'scale_offset_applied': 'false' if raw else 'true'}
        if contract is not None:
            self.metadata['vertical_contract'] = contract

    def tags(self, band=None):
        assert band in (None, 1)
        return dict(self.metadata) if band is None else {}


def normalized_block(datum='MLLW', lane=None):
    pytest.importorskip("pyproj")  # Core-only CI has no GIS packages; from_raster needs pyproj.
    observed = vertical.from_raster(HeaderDataset(raw=True, datum=datum), source_sha256=SOURCE)
    declared = dict(observed['facts'], evidence=[vertical.evidence_from_observation(observed)])
    if lane is not None:
        declared['depth_lane'] = lane
    return vertical.normalized(vertical.require_resolved(declared, observed))


def dataset(block):
    return HeaderDataset(json.dumps(block), datum=block.get('datum', 'MLLW'))


@pytest.fixture
def block():
    return normalized_block()


@pytest.fixture
def no_observation(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('from_raster called before decoded shape validation')
    monkeypatch.setattr(vertical, 'from_raster', forbidden)


def expect_hold(ds, reason):
    with pytest.raises(vertical.VerticalHold) as caught:
        vertical.normalized_from_raster(ds, source_sha256=SOURCE)
    assert type(caught.value) is vertical.VerticalHold
    assert caught.value.holds == [reason]
    assert str(caught.value) == reason


def test_valid_same_collaborators_and_resolution(block, monkeypatch):
    ds = dataset(block)
    before = deepcopy(block)
    observe = vertical.from_raster
    resolve = vertical.require_resolved
    observed = observe(ds, source_sha256=SOURCE)
    evidence = [vertical.evidence_from_observation(observed)]
    expected = resolve(block, observed, evidence)
    calls = []

    def observe_spy(actual, *, source_sha256):
        assert actual is ds and source_sha256 == SOURCE
        calls.append('from_raster')
        return observe(actual, source_sha256=source_sha256)

    def resolve_spy(actual_block, actual_observed, actual_evidence):
        assert actual_block == block
        assert actual_observed == observed
        assert actual_evidence == evidence
        calls.append('require_resolved')
        return resolve(actual_block, actual_observed, actual_evidence)

    monkeypatch.setattr(vertical, 'from_raster', observe_spy)
    monkeypatch.setattr(vertical, 'require_resolved', resolve_spy)
    result = vertical.normalized_from_raster(ds, source_sha256=SOURCE)
    assert result == expected == dict(block, evidence=evidence)
    assert calls == ['from_raster', 'require_resolved']
    assert block == before


@pytest.mark.parametrize('value', [None, [], [1], '', 'lineage', False, True, 0, 2, 1.5],
                         ids=['null', 'empty-list', 'list', 'empty-string', 'string',
                              'false', 'true', 'zero', 'integer', 'float'])
def test_malformed_lineage(block, no_observation, value):
    block['lineage'] = value
    expect_hold(dataset(block), INVALID)


def test_missing_lineage(block, no_observation):
    del block['lineage']
    expect_hold(dataset(block), MISSING)


@pytest.mark.parametrize('value', [None, [], [1], '', 'block', False, True, 0, 1.5],
                         ids=['null', 'empty-list', 'list', 'empty-string', 'string',
                              'false', 'true', 'zero', 'float'])
def test_wrong_block_root(value, no_observation):
    expect_hold(HeaderDataset(json.dumps(value)), MISSING)


@pytest.mark.parametrize('text', [None, '', '{', 'not-json', '{"lineage":'],
                         ids=['absent', 'empty', 'brace', 'text', 'truncated'])
def test_absent_or_undecodable(text, no_observation):
    expect_hold(HeaderDataset(text), MISSING)


@pytest.mark.parametrize('change', ['empty', 'digest', 'source', 'transform', 'units'])
def test_otherwise_invalid_lineage(block, no_observation, change):
    if change == 'empty':
        block['lineage'] = {}
    elif change == 'digest':
        block['lineage']['source_vertical_sha256'] = 'b' * 64
    elif change == 'source':
        block['lineage']['source_vertical'] = None
        block['lineage']['source_vertical_sha256'] = vertical.digest(None)
    elif change == 'transform':
        block['lineage']['datum_transform'] = True
    else:
        block['units'] = 'ft'
    expect_hold(dataset(block), INVALID)


@pytest.mark.parametrize('datum', ['EGM2008', 'instantaneous-sea-level', 'unstated'])
@pytest.mark.parametrize('lane', ['M', 'D'])
def test_deep_normalized_path_unchanged(datum, lane):
    block = normalized_block(datum, lane)
    result = vertical.normalized_from_raster(dataset(block), source_sha256=SOURCE)
    assert result['datum'] == datum
    assert result['depth_lane'] == lane
    assert result['deep_datum'] == vertical.deep_datum_record(datum, lane)
    assert result['lineage'] == block['lineage']
    assert vertical.validate(result) == []


@pytest.mark.parametrize('collaborator', ['from_raster', 'require_resolved'])
@pytest.mark.parametrize('error_class', [AttributeError, TypeError, RuntimeError])
def test_collaborator_failures_not_hidden(block, monkeypatch, collaborator, error_class):
    error = error_class('synthetic collaborator failure')

    def broken(*args, **kwargs):
        raise error

    monkeypatch.setattr(vertical, collaborator, broken)
    with pytest.raises(error_class) as caught:
        vertical.normalized_from_raster(dataset(block), source_sha256=SOURCE)
    assert caught.value is error
