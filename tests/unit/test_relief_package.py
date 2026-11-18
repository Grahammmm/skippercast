"""Offline release → QA → review contract, with tiny synthetic layer bytes."""
import copy
import hashlib
import json

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.relief import region as cli
from skippercast.relief import envelope, package, receipts
from tests._support import ROOT

REGION = 'morro-bay'
SOURCE = 'synthetic-grid'
CHUNK = 'layers/public/relief.digests/8/2_1.json'
LAYERS = {
    package.ARCHIVE: b'synthetic relief archive',
    package.DIGEST_ROOT: b'{"synthetic": "root"}',
    CHUNK: b'{"synthetic": "chunk"}',
    'layers/public/zone.geojson': b'{"type":"FeatureCollection","features":[]}',
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def assembly(tmp_path, monkeypatch):
    config = tmp_path / 'repo-config'
    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    write_json(config / 'catalog/sources.json', {'sources': [{'id': SOURCE, 'rights': rights,
                                                            'review_status': 'approved'}]})
    write_json(config / f'regions/{REGION}/region.json', {'bounds': [-122, 34, -120, 36]})
    write_json(config / 'catalog/relief/pointer.schema.json', json.loads(
        (ROOT / 'catalog/relief/pointer.schema.json').read_bytes()))
    monkeypatch.setattr(package, 'repo_root', lambda: config)
    monkeypatch.setattr(envelope, 'repo_root', lambda: config)
    return config


def inputs(root, *, include_digests=True):
    region = receipts.Region(root, REGION)
    layers = {p: b for p, b in LAYERS.items() if include_digests or 'relief.digests' not in p}

    def tiles(output):
        for name, blob in layers.items():
            path = output / name.removeprefix('layers/public/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)

    assert receipts.run_stage(receipts.StageRun(region, 'tiles', tiles, 'a' * 64,
                                                scope='public', target='layers/public')).state == 'ok'
    manifest = root / 'layers.json'
    metadata = {
        'region': REGION, 'bounds': [-121.3, 35.1, -121, 35.5], 'minzoom': 8, 'maxzoom': 8,
        'layer_paths': list(reversed(layers)),
        'sources': [{
            'id': SOURCE, 'attribution': 'Synthetic survey', 'rights_class': 'public', 'label': 'estimated',
            'vertical_datum': 'NAVD88', 'survey_dates': ['2020'],
            'rights': {'public_display': 'allowed', 'license': 'public-domain'},
        }],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [{
            'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2,
        }]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
    }
    write_json(manifest, metadata)
    return region, manifest


def run(region, stage, *args):
    return cli.main([stage, '--out', str(region.out_root), '--region', region.id, *map(str, args)])


def run_package(region, manifest):
    return run(region, 'package', '--manifest', manifest, '--upstream', 'tiles:public')


def release_and_qa(region, manifest, *, status='PASS', digest=None):
    assert run_package(region, manifest) == 0
    receipt = receipts.check(region, 'package')
    assert receipt.done and receipt.receipt is not None
    gen = receipt.receipt['generation']
    release = region.dir / 'release' / gen / 'release.json'
    report = {'status': status, 'release_sha256': digest or sha(release), 'synthetic': True}
    assert receipts.run_stage(receipts.StageRun(region, 'qa', lambda p: write_json(p / 'qa.json', report),
                                                'b' * 64, upstream=[receipts.Ref('package')],
                                                target=f'qa/{gen}')).state == 'ok'
    return gen, release, region.dir / 'qa' / gen / 'qa.json'


def approved(root, *, include_digests=True):
    region, manifest = inputs(root, include_digests=include_digests)
    gen, release, qa = release_and_qa(region, manifest)
    assert run(region, 'envelope', '--generation', gen) == 0
    review = region.dir / 'review' / gen / 'envelope.json'
    approval = review.with_name('approval.json')
    write_json(approval, {'envelope_sha256': sha(review), 'verdict': f'APPROVED release {REGION} envelope={sha(review)}',
                          'card_id': 'fixture', 'reviewer': 'fixture', 'time': '2000-01-01T00:00:00Z'})
    return region, release, qa, review, approval


def test_deterministic_acyclic_chain_and_receipts(tmp_path, assembly, capsys):
    region, release, qa, review, approval = approved(tmp_path / 'first')
    _, release2, qa2, review2, _ = approved(tmp_path / 'second')
    assert [sha(p) for p in (release, qa, review)] == [sha(p) for p in (release2, qa2, review2)]
    release_doc = json.loads(release.read_bytes())
    assert release_doc['disclaimer'] == 'NOT FOR NAVIGATION'
    assert b'qa.json' not in release.read_bytes() and sha(qa) not in release.read_text()
    assert release_doc['generation'] == release.parent.name
    assert json.loads(review.read_bytes())['layers'] == release_doc['layers']
    assert json.loads(qa.read_bytes())['release_sha256'] == sha(release)
    assert release_doc['layers'] == [{'path': p, 'sha256': hashlib.sha256(LAYERS[p]).hexdigest(), 'bytes': len(LAYERS[p])}
                                     for p in sorted(LAYERS)]
    verified = envelope.verify_chain(approval, review)
    assert verified.release_sha256 == sha(release) and verified.envelope_sha256 == sha(review)
    assert run_package(region, region.out_root / 'layers.json') == 0
    assert run(region, 'envelope', '--generation', review.parent.name) == 0
    assert capsys.readouterr().out.count('DONE generation') == 2
    (region.dir / CHUNK).write_bytes(b'changed')
    assert receipts.check(region, 'package').state == 'stale'
    assert receipts.check(region, 'envelope').state == 'stale'


def test_pointer_schema_round_trip_and_previous(tmp_path, assembly):
    _, release, _, review, approval = approved(tmp_path / 'first')
    schema = package.pointer_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    pointer = envelope.build_pointer(approval, review)
    validator.validate(json.loads(receipts.canonical(pointer)))
    assert json.loads(receipts.canonical(pointer)) == pointer
    assert pointer['previous'] is None
    assert pointer['sha256'] == hashlib.sha256(LAYERS[package.ARCHIVE]).hexdigest()
    assert pointer['bytes'] == len(LAYERS[package.ARCHIVE])
    assert pointer['digest_root_sha256'] == hashlib.sha256(LAYERS[package.DIGEST_ROOT]).hexdigest()
    assert pointer['release_sha256'] == sha(release) and pointer['envelope_sha256'] == sha(review)
    previous = dict(pointer, generation='c' * 64, sha256='d' * 64)
    replacement = envelope.build_pointer(approval, review, previous=previous)
    validator.validate(replacement)
    assert replacement['previous'] == {key: previous[key] for key in ('generation', 'release_sha256', 'envelope_sha256', 'sha256')}
    for change in ({'private': True}, {'maxzoom': 18}, {'envelope_sha256': 'no'}, {'digest_root_sha256': None}):
        with pytest.raises(ValidationError):
            validator.validate(pointer | change)
    bad = copy.deepcopy(pointer)
    bad['sources'][0]['rights']['public_display'] = 'private'
    with pytest.raises(ValidationError):
        validator.validate(bad)
    with pytest.raises(package.ReleaseError, match='another region'):
        envelope.build_pointer(approval, review, previous=previous | {'region': 'elsewhere'})


@pytest.mark.parametrize('change', ['private-source', 'held-catalog-row', 'unknown-source', 'excluded-mbari',
                                    'out-of-region', 'unlisted-digest', 'unreceipted-layer', 'uncertified-z16'])
def test_package_refuses_ineligible_inputs(tmp_path, assembly, change, capsys):
    region, manifest = inputs(tmp_path / 'out')
    doc = json.loads(manifest.read_bytes())
    catalog = assembly / 'catalog/sources.json'
    rows = json.loads(catalog.read_bytes())
    reason = 'source'
    if change == 'private-source':
        doc['sources'][0]['rights_class'] = 'private'
    elif change == 'held-catalog-row':
        rows['sources'][0]['provider'] = 'CSUMB Seafloor Mapping Lab'
        rows['sources'][0]['rights']['public_display'] = 'private'
    elif change == 'unknown-source':
        rows['sources'].clear()
    elif change == 'excluded-mbari':
        rows['sources'][0]['provider'] = 'MBARI'
    elif change == 'out-of-region':
        doc['bounds'][0] = -125
        reason = 'clipped to the region'
    elif change == 'unlisted-digest':
        doc['layer_paths'].remove(CHUNK)
        reason = 'entire relief digest index'
    elif change == 'unreceipted-layer':
        added = 'layers/public/unreceipted.geojson'
        (region.dir / added).write_bytes(b'not a stage output')
        doc['layer_paths'].append(added)
        reason = 'not in the current upstream outputs'
    else:
        doc.update(minzoom=16, maxzoom=16, native_support_by_zoom={'16': {'tiles': 1, 'limit_m': 20,
                                    'sources': [{'id': SOURCE, 'tiles': 1, 'resolution_m': 1}]}})
        reason = 'evidence at z16'
    write_json(catalog, rows)
    write_json(manifest, doc)
    assert run_package(region, manifest) == 1
    assert reason in capsys.readouterr().out
    assert receipts.check(region, 'package').state == 'failed'
    assert not list(region.dir.glob('release/*/release.json'))


def test_package_refuses_qa_as_a_layer(tmp_path, assembly, capsys):
    region, manifest = inputs(tmp_path / 'out')
    doc = json.loads(manifest.read_bytes())
    doc['layer_paths'].append('layers/public/qa.json')
    write_json(manifest, doc)
    with pytest.raises(SystemExit) as exc:
        run_package(region, manifest)
    assert exc.value.code == 2
    assert 'not a public layer path' in capsys.readouterr().err


@pytest.mark.parametrize('qa_args', [{'status': 'FAIL'}, {'digest': '0' * 64}])
def test_envelope_requires_passing_qa_for_current_release(tmp_path, assembly, qa_args, capsys):
    region, manifest = inputs(tmp_path / 'out')
    gen, _, _ = release_and_qa(region, manifest, **qa_args)
    assert run(region, 'envelope', '--generation', gen) == 1
    assert 'QA must PASS and quote the current release sha256' in capsys.readouterr().out
    assert not (region.dir / 'review' / gen / 'envelope.json').exists()


def test_package_requires_digest_root(tmp_path, assembly, capsys):
    region, manifest = inputs(tmp_path / 'out', include_digests=False)
    assert run_package(region, manifest) == 1
    assert 'digest root' in capsys.readouterr().out
    assert receipts.check(region, 'package').state == 'failed'
    assert not list(region.dir.glob('release/*/release.json'))


def test_verify_chain_rejects_consistently_approved_release_without_digest_root(tmp_path, assembly):
    _, release, qa, review, approval = approved(tmp_path / 'out')
    doc = json.loads(release.read_bytes())
    doc['layers'] = [row for row in doc['layers'] if not row['path'].startswith('layers/public/relief.digests/')]
    doc['digest_root_sha256'] = None
    write_json(release, doc)
    write_json(qa, json.loads(qa.read_bytes()) | {'release_sha256': sha(release)})
    review_doc = json.loads(review.read_bytes())
    review_doc['release']['sha256'] = sha(release)
    review_doc['qa']['sha256'] = sha(qa)
    review_doc['layers'] = doc['layers']
    write_json(review, review_doc)
    write_json(approval, {'envelope_sha256': sha(review), 'verdict': f'APPROVED release {REGION} envelope={sha(review)}'})
    with pytest.raises(package.ReleaseError, match='digest root'):
        envelope.verify_chain(approval, review)


@pytest.mark.parametrize(('mutation', 'reason'), [
    ('layer-byte', 'layer hash or size changed'), ('digest-chunk', 'layer hash or size changed'),
    ('qa-edit', 'qa.json does not match'), ('release-edit', 'release.json does not match'),
    ('added-layer', 'release.json does not match'), ('swapped-envelope', 'envelope sha256 does not match'),
    ('wrong-verdict', 'exact release verdict'), ('layer-symlink', 'symlink in artifact path'),
])
def test_verify_chain_rejects_changes_after_approval(tmp_path, assembly, mutation, reason):
    region, release, qa, review, approval = approved(tmp_path / 'out')
    if mutation in {'layer-byte', 'digest-chunk'}:
        layer = region.dir / (package.ARCHIVE if mutation == 'layer-byte' else CHUNK)
        original = layer.read_bytes()
        layer.write_bytes(bytes([original[0] ^ 1]) + original[1:])  # same size, one byte changed
    elif mutation == 'qa-edit':
        qa.write_bytes(qa.read_bytes() + b'\n')
    elif mutation == 'release-edit':
        release.write_bytes(release.read_bytes() + b'\n')
    elif mutation == 'added-layer':
        doc = json.loads(release.read_bytes())
        doc['layers'].append({'path': 'layers/public/extra.json', 'sha256': '0' * 64, 'bytes': 1})
        write_json(release, doc)
    elif mutation == 'swapped-envelope':
        # Build a different valid generation (same region, different inventory).
        other, manifest = inputs(tmp_path / 'other')
        doc = json.loads(manifest.read_bytes())
        doc['bounds'][0] = -121.2
        write_json(manifest, doc)
        gen, _, _ = release_and_qa(other, manifest)
        assert run(other, 'envelope', '--generation', gen) == 0
        review.write_bytes((other.dir / 'review' / gen / 'envelope.json').read_bytes())
    elif mutation == 'wrong-verdict':
        write_json(approval, json.loads(approval.read_bytes()) | {'verdict': 'APPROVED release elsewhere'})
    else:
        layer = region.dir / package.ARCHIVE
        target = tmp_path / 'outside'
        target.write_bytes(layer.read_bytes())
        layer.unlink()
        layer.symlink_to(target)
    with pytest.raises(package.ReleaseError, match=reason):
        envelope.verify_chain(approval, review)


def test_verify_chain_requires_exact_envelope_layer_list(tmp_path, assembly):
    _, _, _, review, approval = approved(tmp_path / 'out')
    # Even a newly approved malformed envelope is not sufficient if it leaves a layer out.
    doc = json.loads(review.read_bytes())
    doc['layers'].pop()
    write_json(review, doc)
    write_json(approval, {'envelope_sha256': sha(review), 'verdict': f'APPROVED release {REGION} envelope={sha(review)}'})
    with pytest.raises(package.ReleaseError, match='layer list does not match release'):
        envelope.verify_chain(approval, review)
