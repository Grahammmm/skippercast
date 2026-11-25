"""M32: the survey gap companion is derived byte-exactly from the reviewed survey detail and travels with it.

Believable bugs: a companion that is not the detail's tier-none subset (another release, a hand-edited file, a
measured tier) reaching a pointer; a companion without its detail; a release with only half a pair; the publisher,
stage transport or schema forgetting the second object; a companion big enough to make the default view slow.
"""
from hashlib import sha256
import json

import pytest

from skippercast.relief import envelope, package, stage_transport, survey_delivery as sd
from skippercast.relief.package import ReleaseError

SQUARE = [[[-121.0, 35.0], [-120.5, 35.0], [-120.5, 35.5], [-121.0, 35.0]]]


def feature(tier, sources=()):
    props = {'tier': tier, 'sources': list(sources), 'date': None}
    if tier != 'none':
        props.update(grid_m=10, source='Synthetic survey')
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': SQUARE}, 'properties': props}


def canonical(doc):
    return (json.dumps(doc, sort_keys=True, separators=(',', ':')) + '\n').encode()


def detail_bytes(*tiers):
    return canonical({'type': 'FeatureCollection', 'region': 'fixture', 'navigation': 'NOT FOR NAVIGATION',
                      'features': [feature(t, [] if t == 'none' else ['src']) for t in tiers]})


def pins(raw, wire):
    return {'decoded': {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()},
            'wire': {'bytes': len(wire), 'sha256': sha256(wire).hexdigest()}}


@pytest.fixture
def leaf(tmp_path):
    """A survey-detail producer leaf holding a verified detail pair."""
    out = tmp_path / 'layers/public/survey-detail'
    out.mkdir(parents=True)
    raw = detail_bytes('estimated', 'none', 'estimated')
    (out / 'detail.geojson').write_bytes(raw)
    (out / 'detail.geojson.br').write_bytes(sd.encode(raw))
    return out


def rows_for(root):
    rows = []
    for path in sorted((root / 'layers/public/survey-detail').iterdir()):
        data = path.read_bytes()
        rows.append({'path': path.relative_to(root).as_posix(), 'sha256': sha256(data).hexdigest(), 'bytes': len(data)})
    return rows


def test_gap_document_keeps_only_no_survey_areas_in_canonical_form():
    raw = detail_bytes('estimated', 'none', 'estimated')
    gap = json.loads(sd.gap_document(raw))
    assert [f['properties']['tier'] for f in gap['features']] == ['none']
    assert {k: v for k, v in gap.items() if k != 'features'} == {
        'type': 'FeatureCollection', 'region': 'fixture', 'navigation': 'NOT FOR NAVIGATION'}
    assert sd.gap_document(raw) == canonical(gap)
    sd.check_gap(raw, sd.gap_document(raw))


@pytest.mark.parametrize('raw, message', [
    (detail_bytes('estimated'), 'no tier-none area'),
    (detail_bytes('none', 'none'), 'all no-survey'),
    (detail_bytes('estimated', 'none').replace(b',"navigation"', b', "navigation"'), 'canonical'),
    (b'not json', 'not JSON'),
    (canonical({'type': 'FeatureCollection', 'features': [dict(feature('none'), properties={'tier': 'none', 'sources': ['x']})]}),
     'cannot name a source'),
])
def test_gap_document_refuses_detail_it_cannot_derive_honestly(raw, message):
    with pytest.raises(ValueError, match=message):
        sd.gap_document(raw)


def test_check_gap_refuses_a_companion_from_other_bytes():
    raw = detail_bytes('estimated', 'none')
    other = sd.gap_document(detail_bytes('none', 'estimated', 'none', 'estimated'))
    with pytest.raises(ValueError, match='not derived'):
        sd.check_gap(raw, other)
    hand_edited = sd.gap_document(raw).replace(b'-120.5', b'-120.4')
    with pytest.raises(ValueError, match='not derived'):
        sd.check_gap(raw, hand_edited)


def test_write_gap_and_package_check_accept_the_derived_pair(leaf):
    receipt = sd.write_gap(leaf)
    gap = (leaf / 'gap.geojson').read_bytes()
    assert receipt['gap.geojson'] == {'bytes': len(gap), 'sha256': sha256(gap).hexdigest()}
    assert len((leaf / 'gap.geojson.br').read_bytes()) < len((leaf / 'detail.geojson.br').read_bytes())
    root = leaf.parents[2]
    rows = rows_for(root)
    package.check_survey(root, rows)
    members = sd.pointer_members({r['path']: r for r in rows})
    assert members['survey_gap'] == pins(gap, (leaf / 'gap.geojson.br').read_bytes())
    assert list(members) == ['survey_detail', 'survey_gap']


def test_package_check_refuses_mixed_or_partial_survey_pairs(leaf, tmp_path):
    sd.write_gap(leaf)
    root = leaf.parents[2]
    # A companion produced from another detail, with matching inventory rows, is still not this detail's subset.
    other = sd.gap_document(detail_bytes('none', 'estimated', 'none', 'estimated'))
    (leaf / 'gap.geojson').write_bytes(other)
    (leaf / 'gap.geojson.br').write_bytes(sd.encode(other))
    with pytest.raises(ReleaseError, match='not derived'):
        package.check_survey(root, rows_for(root))
    # A wire that does not decode to its own decoded pin.
    (leaf / 'gap.geojson').write_bytes(sd.gap_document((leaf / 'detail.geojson').read_bytes()))
    with pytest.raises(ReleaseError, match='does not match reviewed pins'):
        package.check_survey(root, rows_for(root))
    # Half a companion pair, or a companion without the detail pair.
    (leaf / 'gap.geojson.br').unlink()
    with pytest.raises(ReleaseError, match='incomplete or unexpected'):
        package.check_survey(root, rows_for(root))
    for name in ('detail.geojson', 'detail.geojson.br'):
        (leaf / name).unlink()
    (leaf / 'gap.geojson.br').write_bytes(sd.encode((leaf / 'gap.geojson').read_bytes()))
    with pytest.raises(ReleaseError, match='incomplete or unexpected'):
        package.check_survey(root, rows_for(root))


def test_original_and_detail_only_releases_are_unchanged(leaf):
    root = leaf.parents[2]
    package.check_survey(root, [])  # no survey layers at all
    package.check_survey(root, rows_for(root))  # the detail pair alone needs no decoder pass
    assert sd.pointer_members({}) == {}
    assert list(sd.pointer_members({r['path']: r for r in rows_for(root)})) == ['survey_detail']


def test_pointer_members_bound_the_companion_and_refuse_a_copy_of_the_detail():
    def row(path, n, digest):
        return path, {'path': path, 'bytes': n, 'sha256': digest * 64}
    base = dict([row(sd.DECODED_PATH, 900, 'a'), row(sd.WIRE_PATH, 90, 'b')])
    with pytest.raises(ValueError, match='survey_gap exceeds'):
        sd.pointer_members(dict(base, **dict([row(sd.GAP_DECODED_PATH, 10, 'c'), row(sd.GAP_WIRE_PATH, sd.GAP_WIRE_LIMIT + 1, 'd')])))
    with pytest.raises(ValueError, match='repeats the survey detail'):
        sd.pointer_members(dict(base, **dict([row(sd.GAP_DECODED_PATH, 900, 'a'), row(sd.GAP_WIRE_PATH, 90, 'b')])))
    with pytest.raises(ValueError, match='incomplete or unexpected'):
        sd.pointer_members(dict(base, **dict([row(sd.PREFIX + 'extra.geojson', 1, 'e')])))


def test_envelope_member_maps_both_pairs_from_release_layers():
    def row(path, n, digest):
        return {'path': path, 'sha256': digest * 64, 'bytes': n}
    layers = sorted([row(package.ARCHIVE, 1000, '1'), row(package.DIGEST_ROOT, 10, '2'),
                     row(sd.DECODED_PATH, 900, 'a'), row(sd.WIRE_PATH, 90, 'b'),
                     row(sd.GAP_DECODED_PATH, 30, 'c'), row(sd.GAP_WIRE_PATH, 9, 'd')], key=lambda r: r['path'])
    release = {'layers': layers, 'digest_root_sha256': '2' * 64}
    assert envelope.survey_pointer_member(release) == {
        'survey_detail': {'decoded': {'bytes': 900, 'sha256': 'a' * 64}, 'wire': {'bytes': 90, 'sha256': 'b' * 64}},
        'survey_gap': {'decoded': {'bytes': 30, 'sha256': 'c' * 64}, 'wire': {'bytes': 9, 'sha256': 'd' * 64}}}
    release['layers'] = [r for r in layers if r['path'] != sd.DECODED_PATH]
    with pytest.raises(ReleaseError, match='incomplete or unexpected'):
        envelope.survey_pointer_member(release)


def test_pointer_schema_needs_the_detail_next_to_its_companion():
    schema = package.pointer_schema()
    gap = {'decoded': {'bytes': 30, 'sha256': 'c' * 64}, 'wire': {'bytes': 9, 'sha256': 'd' * 64}}
    detail = {'decoded': {'bytes': 900, 'sha256': 'a' * 64}, 'wire': {'bytes': 90, 'sha256': 'b' * 64}}
    sub = {'$defs': schema['$defs'], 'anyOf': schema['anyOf'],
           'properties': {'survey_detail': {'$ref': '#/$defs/survey_detail'}, 'survey_gap': {'$ref': '#/$defs/survey_gap'}}}
    package.validate_schema({'survey_detail': detail, 'survey_gap': gap}, sub)
    package.validate_schema({'survey_detail': detail}, sub)
    package.validate_schema({}, sub)
    with pytest.raises(ReleaseError):
        package.validate_schema({'survey_gap': gap}, sub)
    with pytest.raises(ReleaseError):
        package.validate_schema({'survey_detail': detail, 'survey_gap': dict(gap, wire={'bytes': 262145, 'sha256': 'd' * 64})}, sub)


def test_stage_transport_carries_and_checks_both_wires(leaf):
    sd.write_gap(leaf)
    files = {name: (leaf / name).read_bytes() for name in ('detail.geojson', 'detail.geojson.br', 'gap.geojson', 'gap.geojson.br')}
    pointer = {'region': 'fixture', 'envelope_sha256': 'e' * 64,
               'survey_detail': pins(files['detail.geojson'], files['detail.geojson.br']),
               'survey_gap': pins(files['gap.geojson'], files['gap.geojson.br'])}
    objects = stage_transport._survey(pointer)
    assert [(o.key, o.limit) for o in objects] == [
        (sd.key('fixture', 'e' * 64, pointer['survey_detail']['wire']['sha256']), sd.WIRE_LIMIT),
        (sd.key('fixture', 'e' * 64, pointer['survey_gap']['wire']['sha256']), sd.GAP_WIRE_LIMIT)]
    paths = {o.sha: leaf / ('detail.geojson.br' if o.limit == sd.WIRE_LIMIT else 'gap.geojson.br') for o in objects}
    stage_transport._check_survey(pointer, paths)
    # A detail-only pointer stages one object, exactly as before.
    assert len(stage_transport._survey({k: v for k, v in pointer.items() if k != 'survey_gap'})) == 1
    # A companion swapped for another (validly pinned) release's companion fails the derivation check.
    other = sd.gap_document(detail_bytes('none', 'estimated', 'none', 'estimated'))
    (leaf / 'gap.geojson.br').write_bytes(sd.encode(other))
    swapped = dict(pointer, survey_gap=pins(other, (leaf / 'gap.geojson.br').read_bytes()))
    paths[swapped['survey_gap']['wire']['sha256']] = leaf / 'gap.geojson.br'
    with pytest.raises(ValueError, match='not derived'):
        stage_transport._check_survey(swapped, paths)
