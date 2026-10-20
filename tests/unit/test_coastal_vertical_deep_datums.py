"""PC-1 / G3: deep-band datum classes in coastal.vertical (no GIS stack needed).

EGM2008, instantaneous sea level and an unstated datum are refused in lane S
windows (no ``depth_lane``, or ``depth_lane: 'S'``) and admitted in lane M/D
windows with the fixed G3 uncertainty record: no bound required, not for
navigation.
"""
from copy import deepcopy

import pytest

from skippercast.coastal import vertical

SOURCE = 'a' * 64
STATEMENT = dict(kind='source_metadata', sha256='b' * 64, locator='FGDC metadata, Vertical_Datum_Name')


def observation(datum=None):
    header = dict(driver='GTiff', tags={} if datum is None else {'vertical_datum': datum})
    facts = dict(sign='positive_up', units='m', datum=datum, scale=1.0, offset=0.0,
                 scale_offset_applied=False, datum_realization='unknown')
    return dict(schema='vertical-observation-v1', source_sha256=SOURCE, header=header,
                header_sha256=vertical.digest(header), facts=facts, conflicts=[])


def declared(observed, datum, **extra):
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observed)])
    block.update(datum=datum, **extra)
    return block


# (header datum fact, declared class, extra declared keys)
CASES = [
    pytest.param(None, 'unstated', {}, id='unstated-header-silent'),
    pytest.param('EGM2008', 'EGM2008', {}, id='egm2008-in-header'),
    pytest.param('instantaneous-sea-level', 'instantaneous-sea-level', {}, id='isl-in-header'),
    pytest.param(None, 'EGM2008', {'datum_statement': STATEMENT}, id='egm2008-source-statement'),
    pytest.param(None, 'instantaneous-sea-level', {'datum_statement': STATEMENT}, id='isl-source-statement'),
]


@pytest.mark.parametrize('lane', [None, 'S'])
@pytest.mark.parametrize('fact,datum,extra', CASES)
def test_deep_classes_refused_in_lane_s_windows(fact, datum, extra, lane):
    observed = observation(fact)
    block = declared(observed, datum, **extra)
    if lane is not None:
        block['depth_lane'] = lane
    result = vertical.resolve(block, observed)
    assert result['block'] is None
    assert 'vertical_datum_deep_lane_only' in result['holds']
    with pytest.raises(vertical.VerticalHold):
        vertical.require_resolved(block, observed)


@pytest.mark.parametrize('lane,floor', [('M', 91.44), ('D', 182.88)])
@pytest.mark.parametrize('fact,datum,extra', CASES)
def test_deep_classes_admitted_with_uncertainty_metadata_in_lane_m_d(fact, datum, extra, lane, floor):
    observed = observation(fact)
    block = vertical.require_resolved(declared(observed, datum, depth_lane=lane, **extra), observed)
    record = block['deep_datum']
    assert record == vertical.deep_datum_record(datum, lane)
    assert record['datum_class'] == datum and record['depth_lane'] == lane
    assert record['lane_floor_m'] == floor
    assert record['uncertainty_bound_m'] is None and record['uncertainty_bound_required'] is False
    assert record['uncertainty_status'] == 'datum_offset_unbounded'
    assert record['navigation'] == 'not-for-navigation' and record['chart_datum'] is False
    assert record['datum_transform'] is False
    assert vertical.is_deep(block) and vertical.validate(block) == []
    stored = vertical.normalized(block)
    # The label travels with the normalized product, not only its lineage.
    assert stored['deep_datum'] == record and stored['depth_lane'] == lane
    assert stored['datum'] == datum
    assert stored['lineage']['operations'][-1] == 'drop_cells_shallower_than_lane_floor'
    assert stored['lineage']['datum_transform'] is False
    assert vertical.validate(stored) == []
    if 'datum_statement' in extra:
        assert stored['datum_statement'] == STATEMENT


def test_named_deep_class_needs_header_or_source_statement():
    observed = observation(None)
    for datum in ('EGM2008', 'instantaneous-sea-level'):
        result = vertical.resolve(declared(observed, datum, depth_lane='M'), observed)
        assert result['block'] is None
        assert result['holds'] == ['vertical_datum_statement_required']


@pytest.mark.parametrize('lane', ['M', 'D'])
@pytest.mark.parametrize('datum', ['EGM2008', 'instantaneous-sea-level'])
@pytest.mark.parametrize('statement', [None, {}], ids=['null', 'empty'])
def test_present_but_empty_statement_is_not_evidence(datum, lane, statement):
    # Review round 1: a JSON null statement must not count as the source's statement.
    observed = observation(None)
    block = declared(observed, datum, depth_lane=lane, datum_statement=statement)
    result = vertical.resolve(block, observed)
    assert result['block'] is None
    assert 'vertical_datum_statement_invalid' in result['holds']
    if statement is None:
        assert 'vertical_datum_statement_required' in result['holds']
    with pytest.raises(vertical.VerticalHold):
        vertical.require_resolved(block, observed)
    # The structural check alone (to_depth / normalized path) also refuses it.
    admitted = vertical.require_resolved(declared(observed, datum, depth_lane=lane, datum_statement=STATEMENT),
                                         observed)
    assert vertical.validate(dict(admitted, datum_statement=statement)) == ['vertical_datum_statement_invalid']


@pytest.mark.parametrize('statement', [
    dict(STATEMENT, kind='operator_declaration'), dict(STATEMENT, sha256='short'),
    dict(STATEMENT, locator=' '), dict(STATEMENT, extra=1), 'EGM2008', None, {}, []])
def test_malformed_source_statement_held(statement):
    observed = observation(None)
    result = vertical.resolve(declared(observed, 'EGM2008', depth_lane='M', datum_statement=statement), observed)
    assert 'vertical_datum_statement_invalid' in result['holds'] and result['block'] is None


def test_unstated_class_cannot_carry_a_statement():
    observed = observation(None)
    result = vertical.resolve(declared(observed, 'unstated', depth_lane='M', datum_statement=STATEMENT), observed)
    assert result['holds'] == ['vertical_datum_statement_invalid']


@pytest.mark.parametrize('fact,datum', [('MLLW', 'unstated'), ('EGM2008', 'instantaneous-sea-level'),
                                        ('NAVD88', 'EGM2008'), ('unknown', 'unstated')])
def test_a_header_that_names_a_datum_must_match(fact, datum):
    observed = observation(fact)
    result = vertical.resolve(declared(observed, datum, depth_lane='M', datum_statement=STATEMENT)
                              if datum != 'unstated' else declared(observed, datum, depth_lane='M'), observed)
    assert result['block'] is None
    assert {'vertical_datum_conflict', 'vertical_datum_unobserved'} & set(result['holds'])


@pytest.mark.parametrize('field,value', [('uncertainty_bound_required', True), ('navigation', 'navigation'),
                                         ('lane_floor_m', 0.0), ('chart_datum', True), ('depth_lane', 'D')])
def test_review_cannot_alter_the_g3_record(field, value):
    observed = observation(None)
    record = dict(vertical.deep_datum_record('unstated', 'M'), **{field: value})
    result = vertical.resolve(declared(observed, 'unstated', depth_lane='M', deep_datum=record), observed)
    assert result['holds'] == ['vertical_deep_datum_metadata_invalid']


def test_survey_grade_blocks_reject_deep_labels_and_unknown_lanes():
    observed = observation('MLLW')
    labelled = declared(observed, 'MLLW', deep_datum=vertical.deep_datum_record('unstated', 'M'))
    assert vertical.resolve(labelled, observed)['holds'] == ['vertical_deep_datum_metadata_invalid']
    stated = declared(observed, 'MLLW', datum_statement=STATEMENT)
    assert vertical.resolve(stated, observed)['holds'] == ['vertical_deep_datum_metadata_invalid']
    for lane in ('X', ['M'], None):
        assert 'vertical_depth_lane_unsupported' in vertical.resolve(
            declared(observed, 'MLLW', depth_lane=lane), observed)['holds']
    assert vertical.validate(declared(observed, ['unstated'], depth_lane='M'))  # unhashable: held, no crash


def test_lane_s_blocks_are_unchanged():
    """No new keys appear on survey-grade blocks, so existing facts digests hold."""
    observed = observation('MLLW')
    block = declared(observed, 'MLLW')
    resolved = vertical.require_resolved(block, observed)
    assert resolved == dict(block, datum_realization='unknown')
    stored = vertical.normalized(resolved)
    assert set(stored) == {'schema', 'sign', 'units', 'datum', 'datum_realization', 'scale', 'offset',
                           'scale_offset_applied', 'evidence', 'conflicts', 'storage', 'lineage'}
    assert stored['lineage']['operations'] == ['apply_unapplied_scale_offset', 'convert_units_to_m',
                                               'convert_sign_to_positive_down']
    # A survey-grade datum may run in a deep lane; it is not relabelled.
    deep_lane = vertical.require_resolved(declared(observed, 'MLLW', depth_lane='M'), observed)
    assert 'deep_datum' not in deep_lane and not vertical.is_deep(deep_lane)
    assert 'deep_datum' not in vertical.normalized(deep_lane)


def test_undeclared_header_silent_raster_still_held():
    """SC-3: with no declared contract the observation never self-admits as 'unstated'."""
    observed = observation(None)
    result = vertical.resolve(None, observed)
    assert result['block'] is None
    assert {'vertical_datum_unknown', 'vertical_datum_unobserved'} <= set(result['holds'])
    assert all(hold.startswith('vertical_') for hold in result['holds'])


def test_deep_datum_tag_aliases_are_canonical():
    assert vertical._datum_tag('EGM2008 height') == 'EGM2008'
    assert vertical._datum_tag('Instantaneous Sea Level') == 'instantaneous-sea-level'
    assert vertical._datum_tag('not stated') == 'unstated'
    assert vertical._datum_tag('MLLW') == 'MLLW' and vertical._datum_tag('mllw') == 'mllw'


def test_declared_block_is_not_mutated():
    observed = observation(None)
    block = declared(observed, 'unstated', depth_lane='D')
    before = deepcopy(block)
    vertical.require_resolved(block, observed)
    assert block == before
