"""M32: the survey gap companion is derived byte-exactly from the reviewed survey detail and travels with it.

Believable bugs: a companion that is not the detail's tier-none subset (another release, a hand-edited file, a
measured tier) reaching a pointer; a companion without its detail; a release with only half a pair; a companion
written outside any receipted producer, so packaging refuses it (review t_32c27f16); a companion left over from
an older detail; the publisher, stage transport or schema forgetting the second object; a companion big enough
to make the default view slow.
"""
from hashlib import sha256
import json

import pytest

from scripts.relief import region as cli
from skippercast.relief import envelope, package, receipts, stage_transport, survey_delivery as sd
from skippercast.relief.package import ReleaseError
from tests.unit.test_relief_package import assembly, inputs  # noqa: F401  (fixture and producer chain)

SQUARE = [[[-121.0, 35.0], [-120.5, 35.0], [-120.5, 35.5], [-121.0, 35.0]]]
SURVEY_PATHS = [sd.DECODED_PATH, sd.WIRE_PATH, sd.GAP_DECODED_PATH, sd.GAP_WIRE_PATH]


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


def write_pair(folder, name, raw):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(raw)
    (folder / f'{name}.br').write_bytes(sd.encode(raw))


@pytest.fixture
def root(tmp_path):
    """A region directory holding a verified detail pair and the companion derived from it."""
    raw = detail_bytes('estimated', 'none', 'estimated')
    write_pair(tmp_path / sd.PREFIX, 'detail.geojson', raw)
    write_pair(tmp_path / sd.GAP_PREFIX, 'gap.geojson', sd.gap_document(raw))
    return tmp_path


def rows_for(root, paths=SURVEY_PATHS):
    rows = []
    for path in paths:
        if (root / path).exists():
            data = (root / path).read_bytes()
            rows.append({'path': path, 'sha256': sha256(data).hexdigest(), 'bytes': len(data)})
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


def test_package_check_accepts_the_derived_pair(root):
    gap = (root / sd.GAP_DECODED_PATH).read_bytes()
    assert len((root / sd.GAP_WIRE_PATH).read_bytes()) < len((root / sd.WIRE_PATH).read_bytes())
    rows = rows_for(root)
    package.check_survey(root, rows)
    members = sd.pointer_members({r['path']: r for r in rows})
    assert members['survey_gap'] == pins(gap, (root / sd.GAP_WIRE_PATH).read_bytes())
    assert list(members) == ['survey_detail', 'survey_gap']


def test_package_check_refuses_mixed_or_partial_survey_pairs(root):
    # A companion produced from another detail, with matching inventory rows, is still not this detail's subset.
    other = sd.gap_document(detail_bytes('none', 'estimated', 'none', 'estimated'))
    write_pair(root / sd.GAP_PREFIX, 'gap.geojson', other)
    with pytest.raises(ReleaseError, match='not derived'):
        package.check_survey(root, rows_for(root))
    # A wire that does not decode to its own decoded pin.
    (root / sd.GAP_DECODED_PATH).write_bytes(sd.gap_document((root / sd.DECODED_PATH).read_bytes()))
    with pytest.raises(ReleaseError, match='does not match reviewed pins'):
        package.check_survey(root, rows_for(root))
    # Half a companion pair, or a companion without the detail pair.
    (root / sd.GAP_WIRE_PATH).unlink()
    with pytest.raises(ReleaseError, match='incomplete or unexpected'):
        package.check_survey(root, rows_for(root))
    (root / sd.GAP_WIRE_PATH).write_bytes(sd.encode((root / sd.GAP_DECODED_PATH).read_bytes()))
    with pytest.raises(ReleaseError, match='incomplete or unexpected'):
        package.check_survey(root, rows_for(root, [sd.GAP_DECODED_PATH, sd.GAP_WIRE_PATH]))


def test_original_and_detail_only_releases_are_unchanged(root):
    detail_only = rows_for(root, [sd.DECODED_PATH, sd.WIRE_PATH])
    package.check_survey(root, [])  # no survey layers at all
    package.check_survey(root, detail_only)  # the detail pair alone needs no decoder pass
    assert sd.pointer_members({}) == {}
    assert list(sd.pointer_members({r['path']: r for r in detail_only})) == ['survey_detail']


def test_pointer_members_bound_the_companion_and_refuse_a_copy_of_the_detail():
    def row(path, n, digest):
        return path, {'path': path, 'bytes': n, 'sha256': digest * 64}
    base = dict([row(sd.DECODED_PATH, 900, 'a'), row(sd.WIRE_PATH, 90, 'b')])
    with pytest.raises(ValueError, match='survey_gap exceeds'):
        sd.pointer_members(dict(base, **dict([row(sd.GAP_DECODED_PATH, 10, 'c'), row(sd.GAP_WIRE_PATH, sd.GAP_WIRE_LIMIT + 1, 'd')])))
    with pytest.raises(ValueError, match='repeats the survey detail'):
        sd.pointer_members(dict(base, **dict([row(sd.GAP_DECODED_PATH, 900, 'a'), row(sd.GAP_WIRE_PATH, 90, 'b')])))
    for extra in (sd.PREFIX + 'extra.geojson', sd.GAP_PREFIX + 'extra.geojson'):
        with pytest.raises(ValueError, match='incomplete or unexpected'):
            sd.pointer_members(dict(base, **dict([row(extra, 1, 'e')])))


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


def test_stage_transport_carries_and_checks_both_wires(root):
    files = {path: (root / path).read_bytes() for path in SURVEY_PATHS}
    pointer = {'region': 'fixture', 'envelope_sha256': 'e' * 64,
               'survey_detail': pins(files[sd.DECODED_PATH], files[sd.WIRE_PATH]),
               'survey_gap': pins(files[sd.GAP_DECODED_PATH], files[sd.GAP_WIRE_PATH])}
    objects = stage_transport._survey(pointer)
    assert [(o.key, o.limit) for o in objects] == [
        (sd.key('fixture', 'e' * 64, pointer['survey_detail']['wire']['sha256']), sd.WIRE_LIMIT),
        (sd.key('fixture', 'e' * 64, pointer['survey_gap']['wire']['sha256']), sd.GAP_WIRE_LIMIT)]
    paths = {o.sha: root / (sd.WIRE_PATH if o.limit == sd.WIRE_LIMIT else sd.GAP_WIRE_PATH) for o in objects}
    stage_transport._check_survey(pointer, paths)
    # A detail-only pointer stages one object, exactly as before.
    assert len(stage_transport._survey({k: v for k, v in pointer.items() if k != 'survey_gap'})) == 1
    # A companion swapped for another (validly pinned) release's companion fails the derivation check.
    other = sd.gap_document(detail_bytes('none', 'estimated', 'none', 'estimated'))
    write_pair(root / sd.GAP_PREFIX, 'gap.geojson', other)
    swapped = dict(pointer, survey_gap=pins(other, (root / sd.GAP_WIRE_PATH).read_bytes()))
    paths[swapped['survey_gap']['wire']['sha256']] = root / sd.GAP_WIRE_PATH
    with pytest.raises(ValueError, match='not derived'):
        stage_transport._check_survey(swapped, paths)


# --- The receipted producer path: survey_detail -> survey_gap -> package (review t_32c27f16 item 1). ---

def survey_detail_stage(region, raw):
    """Stand-in for the survey_detail producer: a receipted stage that writes the detail pair."""
    result = receipts.run_stage(receipts.StageRun(
        region, 'survey_detail', lambda out: write_pair(out, 'detail.geojson', raw), 'd' * 64, scope='public',
        plan=lambda _: receipts.Plan(params={'detail': sha256(raw).hexdigest()}), target=sd.PREFIX.rstrip('/')))
    assert result.state == 'ok', result.line()


def run(region, *args):
    return cli.main([*map(str, args), '--out', str(region.out_root), '--region', region.id])


def package_with(region, manifest, *upstream):
    doc = json.loads(manifest.read_bytes())
    doc['layer_paths'] = [p for p in doc['layer_paths'] if not sd.is_survey_path(p)] + SURVEY_PATHS
    manifest.write_text(json.dumps(doc, sort_keys=True), encoding='utf-8')
    return run(region, 'package', '--manifest', manifest, '--upstream', 'tiles:public',
               *(arg for ref in upstream for arg in ('--upstream', ref)))


def released_layers(region):
    verdict = receipts.check(region, 'package')
    assert verdict.done, verdict.reason
    release = json.loads((region.dir / 'release' / verdict.receipt['generation'] / 'release.json').read_bytes())
    return release, {row['path']: row for row in release['layers']}


def test_survey_gap_stage_output_is_packaged_as_a_receipted_layer(tmp_path, assembly, capsys):  # noqa: F811
    region, manifest = inputs(tmp_path)
    raw = detail_bytes('estimated', 'none', 'estimated')
    survey_detail_stage(region, raw)
    assert run(region, 'survey_gap', '--scope', 'public') == 0
    gap_receipt = receipts.check(region, 'survey_gap', 'public')
    assert gap_receipt.done, gap_receipt.reason
    assert [row['path'] for row in gap_receipt.receipt['outputs']] == [sd.GAP_DECODED_PATH, sd.GAP_WIRE_PATH]
    assert (region.dir / sd.GAP_DECODED_PATH).read_bytes() == sd.gap_document(raw)
    # Re-running is a no-op while the detail is unchanged.
    assert run(region, 'survey_gap', '--scope', 'public') == 0
    assert receipts.check(region, 'survey_gap', 'public').receipt['generation'] == gap_receipt.receipt['generation']

    # The producer chain packages: every survey row comes from a current receipt and the companion re-derives.
    assert package_with(region, manifest, 'survey_detail:public', 'survey_gap:public') == 0
    release, layers = released_layers(region)
    for row in gap_receipt.receipt['outputs']:
        assert {k: layers[row['path']][k] for k in ('sha256', 'bytes')} == {k: row[k] for k in ('sha256', 'bytes')}
    member = envelope.survey_pointer_member(release)
    assert member['survey_gap'] == pins(sd.gap_document(raw), (region.dir / sd.GAP_WIRE_PATH).read_bytes())
    capsys.readouterr()


def test_package_refuses_a_companion_without_its_producer_receipt(tmp_path, assembly, capsys):  # noqa: F811
    region, manifest = inputs(tmp_path)
    raw = detail_bytes('estimated', 'none', 'estimated')
    survey_detail_stage(region, raw)
    # Hand-written files next to the detail (the old write_gap path) are not current upstream outputs.
    write_pair(region.dir / sd.GAP_PREFIX, 'gap.geojson', sd.gap_document(raw))
    assert package_with(region, manifest, 'survey_detail:public') != 0
    assert 'not in the current upstream outputs' in capsys.readouterr().out
    assert not receipts.check(region, 'package').done


def test_a_new_detail_makes_the_old_companion_stale_until_it_is_rederived(tmp_path, assembly, capsys):  # noqa: F811
    region, manifest = inputs(tmp_path)
    survey_detail_stage(region, detail_bytes('estimated', 'none', 'estimated'))
    assert run(region, 'survey_gap', '--scope', 'public') == 0
    newer = detail_bytes('none', 'estimated', 'none', 'estimated')
    survey_detail_stage(region, newer)
    assert receipts.check(region, 'survey_gap', 'public').state == 'stale'
    assert package_with(region, manifest, 'survey_detail:public', 'survey_gap:public') != 0
    assert not receipts.check(region, 'package').done
    assert run(region, 'survey_gap', '--scope', 'public') == 0
    assert (region.dir / sd.GAP_DECODED_PATH).read_bytes() == sd.gap_document(newer)
    assert package_with(region, manifest, 'survey_detail:public', 'survey_gap:public') == 0
    capsys.readouterr()


@pytest.mark.parametrize('damage', ['changed-detail', 'wrong-wire', 'no-gap-area'])
def test_survey_gap_stage_holds_without_an_honest_attested_detail(tmp_path, damage, capsys):
    region = receipts.Region(tmp_path, 'morro-bay')
    raw = detail_bytes('estimated') if damage == 'no-gap-area' else detail_bytes('estimated', 'none')
    survey_detail_stage(region, raw)
    if damage == 'changed-detail':
        (region.dir / sd.DECODED_PATH).write_bytes(detail_bytes('none', 'estimated'))
    elif damage == 'wrong-wire':
        survey = region.dir / sd.PREFIX
        (survey / 'detail.geojson.br').write_bytes(sd.encode(detail_bytes('none', 'estimated')))
    assert run(region, 'survey_gap', '--scope', 'public') != 0
    assert not (region.dir / sd.GAP_DECODED_PATH).exists()
    assert not receipts.check(region, 'survey_gap', 'public').done
    capsys.readouterr()
