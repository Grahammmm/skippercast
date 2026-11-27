"""The survey_detail stage turns the zone stage's attested detail into the public survey detail the Chart loads.

Believable bugs: a detail that names selection-file ids the Chart does not know (Morro's zone names files, Big Sur's
names catalog ids) so the Chart drops the whole layer; a feature that quietly names an excluded or non-public file;
a surveyed area with two sources, which the Chart refuses; a zone file edited after its receipt; another region's
zone; a detail that only a scratch script could produce, so packaging and survey_gap have no receipted upstream.
"""
from hashlib import sha256
import json

import pytest

from scripts.relief import region as cli
from skippercast.relief import envelope, receipts, survey_delivery as sd
from tests.unit.test_relief_package import REGION, assembly, inputs  # noqa: F401  (fixture and producer chain)

SQUARE = [[[-121.0, 35.0], [-120.5, 35.0], [-120.5, 35.5], [-121.0, 35.0]]]
ZONE_DETAIL = 'layers/public/zone/detail.geojson'
FILES = [  # selection rows as the select stage writes them
    {'id': 'grid-a-1111', 'source_id': 'grid-a', 'decision': 'included', 'rights_class': 'public'},
    {'id': 'grid-a-2222', 'source_id': 'grid-a', 'decision': 'included', 'rights_class': 'public'},
    {'id': 'grid-b-3333', 'source_id': 'grid-b', 'decision': 'included', 'rights_class': 'public'},
    {'id': 'grid-c-4444', 'source_id': 'grid-c', 'decision': 'excluded', 'rights_class': 'public'},
    {'id': 'grid-d-5555', 'source_id': 'grid-d', 'decision': 'included', 'rights_class': 'private'},
]


def feature(tier, sources):
    props = {'tier': tier, 'sources': list(sources), 'date': None}
    if tier != 'none':
        props.update(grid_m=4.0, source=sources[0] if sources else 'x')
    return {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': SQUARE}, 'properties': props}


def zone_doc(*features, region=REGION):
    return {'type': 'FeatureCollection', 'region': region, 'navigation': 'NOT FOR NAVIGATION', 'features': list(features)}


def stand_in(region, stage, folder, files, scope=None):
    """A receipted upstream stage that writes ``files`` ({name: bytes}) into ``folder``."""
    def build(out):
        for name, data in files.items():
            (out / name).write_bytes(data)
    digest = sha256(json.dumps(sorted(files), sort_keys=True).encode() + b''.join(files.values())).hexdigest()
    result = receipts.run_stage(receipts.StageRun(region, stage, build, 'f' * 64, scope=scope, target=folder,
                                                  plan=lambda _: receipts.Plan(params={'content': digest})))
    assert result.state in ('ok', 'done'), result.line()


def upstream(region, doc, files=FILES, selection_region=REGION):
    selection = {'region': selection_region, 'scope': 'public', 'files': files}
    stand_in(region, 'select', 'select', {'selection.json': json.dumps(selection).encode()})
    stand_in(region, 'zone', 'layers/public/zone', {'detail.geojson': json.dumps(doc, indent=1).encode()}, scope='public')


def run(region, *args):
    return cli.main([*map(str, args), '--out', str(region.out_root), '--region', region.id])


def detail_of(region):
    verdict = receipts.check(region, 'survey_detail', 'public')
    assert verdict.done, verdict.reason
    assert [row['path'] for row in verdict.receipt['outputs']] == [sd.DECODED_PATH, sd.WIRE_PATH]
    raw = (region.dir / sd.DECODED_PATH).read_bytes()
    pins = {'decoded': {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}}
    assert sd.check_decoded(region.dir / sd.WIRE_PATH, pins) == raw  # the wire is this detail
    return verdict, raw


def test_stage_names_catalog_sources_and_keeps_everything_else(tmp_path, capsys):
    region = receipts.Region(tmp_path, REGION)
    doc = zone_doc(feature('estimated', ['grid-a-1111']), feature('estimated', ['grid-a-1111', 'grid-a-2222']),
                   feature('estimated', ['grid-b']), feature('none', []))
    upstream(region, doc)
    assert run(region, 'survey_detail', '--scope', 'public') == 0
    verdict, raw = detail_of(region)
    out = json.loads(raw)
    # Selection files become their catalog source (once); a catalog id stays; the no-survey area names nothing.
    assert [f['properties']['sources'] for f in out['features']] == [['grid-a'], ['grid-a'], ['grid-b'], []]
    expected = json.loads(json.dumps(doc))
    for f, sources in zip(expected['features'], [['grid-a'], ['grid-a'], ['grid-b'], []]):
        f['properties']['sources'] = sources
    assert out == expected
    assert raw == (json.dumps(expected, sort_keys=True, separators=(',', ':')) + '\n').encode()
    # Unchanged inputs: a no-op with the same generation.
    assert run(region, 'survey_detail', '--scope', 'public') == 0
    assert receipts.check(region, 'survey_detail', 'public').receipt['generation'] == verdict.receipt['generation']
    capsys.readouterr()


@pytest.mark.parametrize('case, message', [
    ('excluded-file', 'outside the public selection'),
    ('private-file', 'outside the public selection'),
    ('unknown-id', 'outside the public selection'),
    ('two-sources', 'exactly one catalog source'),
    ('no-source', 'exactly one catalog source'),
    ('none-with-source', 'cannot name a source'),
    ('other-region', 'not the morro-bay survey'),
])
def test_stage_holds_on_a_detail_the_chart_could_not_show_honestly(tmp_path, case, message, capsys):
    region = receipts.Region(tmp_path, REGION)
    bad = {'excluded-file': feature('estimated', ['grid-c-4444']), 'private-file': feature('estimated', ['grid-d-5555']),
           'unknown-id': feature('estimated', ['grid-z']), 'two-sources': feature('estimated', ['grid-a-1111', 'grid-b']),
           'no-source': feature('estimated', []), 'none-with-source': feature('none', ['grid-a']),
           'other-region': feature('estimated', ['grid-a'])}[case]
    doc = zone_doc(feature('estimated', ['grid-a']), bad, region='big-sur-coast' if case == 'other-region' else REGION)
    upstream(region, doc)
    assert run(region, 'survey_detail', '--scope', 'public') != 0
    assert message in capsys.readouterr().out
    assert not (region.dir / sd.DECODED_PATH).exists()
    assert not receipts.check(region, 'survey_detail', 'public').done


def test_stage_refuses_a_zone_detail_edited_after_its_receipt(tmp_path, capsys):
    region = receipts.Region(tmp_path, REGION)
    upstream(region, zone_doc(feature('estimated', ['grid-a']), feature('none', [])))
    (region.dir / ZONE_DETAIL).write_bytes(json.dumps(zone_doc(feature('estimated', ['grid-a']))).encode())
    assert run(region, 'survey_detail', '--scope', 'public') != 0
    capsys.readouterr()
    assert not (region.dir / sd.DECODED_PATH).exists()


def test_stage_refuses_another_regions_selection(tmp_path, capsys):
    region = receipts.Region(tmp_path, REGION)
    upstream(region, zone_doc(feature('estimated', ['grid-a'])), selection_region='big-sur-coast')
    assert run(region, 'survey_detail', '--scope', 'public') != 0
    assert 'public selection of this region' in capsys.readouterr().out


def test_new_zone_makes_the_detail_stale_until_it_is_rebuilt(tmp_path, capsys):
    region = receipts.Region(tmp_path, REGION)
    upstream(region, zone_doc(feature('estimated', ['grid-a']), feature('none', [])))
    assert run(region, 'survey_detail', '--scope', 'public') == 0
    upstream(region, zone_doc(feature('estimated', ['grid-b']), feature('none', [])))
    assert receipts.check(region, 'survey_detail', 'public').state == 'stale'
    assert run(region, 'survey_detail', '--scope', 'public') == 0
    _, raw = detail_of(region)
    assert [f['properties']['sources'] for f in json.loads(raw)['features']] == [['grid-b'], []]
    capsys.readouterr()


def package_with(region, manifest, *refs):
    doc = json.loads(manifest.read_bytes())
    doc['layer_paths'] = [p for p in doc['layer_paths'] if not sd.is_survey_path(p)] + [sd.DECODED_PATH, sd.WIRE_PATH]
    manifest.write_text(json.dumps(doc, sort_keys=True), encoding='utf-8')
    return run(region, 'package', '--manifest', manifest, '--upstream', 'tiles:public',
               *(arg for ref in refs for arg in ('--upstream', ref)))


def test_chain_zone_to_detail_to_gap_to_release(tmp_path, assembly, capsys):  # noqa: F811
    region, manifest = inputs(tmp_path)
    upstream(region, zone_doc(feature('estimated', ['grid-a-1111']), feature('none', [])))
    assert run(region, 'survey_detail', '--scope', 'public') == 0
    _, raw = detail_of(region)
    # survey_gap now has a receipted upstream and derives the no-survey companion from it.
    assert run(region, 'survey_gap', '--scope', 'public') == 0
    assert (region.dir / sd.GAP_DECODED_PATH).read_bytes() == sd.gap_document(raw)
    # A detail-only release (a region with no no-survey area, like Big Sur) packages from the receipted stage.
    assert package_with(region, manifest, 'survey_detail:public') == 0
    verdict = receipts.check(region, 'package')
    assert verdict.done, verdict.reason
    release = json.loads((region.dir / 'release' / verdict.receipt['generation'] / 'release.json').read_bytes())
    member = envelope.survey_pointer_member(release)
    wire = (region.dir / sd.WIRE_PATH).read_bytes()
    assert member == {'survey_detail': {'decoded': {'bytes': len(raw), 'sha256': sha256(raw).hexdigest()},
                                        'wire': {'bytes': len(wire), 'sha256': sha256(wire).hexdigest()}}}
    capsys.readouterr()


def test_all_estimated_detail_has_no_gap_companion(tmp_path, capsys):
    # Big Sur's case: every part of the zone is surveyed, so survey_gap holds and no hatch can be drawn.
    region = receipts.Region(tmp_path, REGION)
    upstream(region, zone_doc(feature('estimated', ['grid-a']), feature('estimated', ['grid-b'])))
    assert run(region, 'survey_detail', '--scope', 'public') == 0
    assert run(region, 'survey_gap', '--scope', 'public') != 0
    assert not (region.dir / sd.GAP_DECODED_PATH).exists()
    capsys.readouterr()
