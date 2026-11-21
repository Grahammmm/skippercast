"""Offline release → QA → review contract, with tiny synthetic layer bytes."""
import copy
import hashlib
import json
import re

from jsonschema import Draft202012Validator, ValidationError
import pytest

from scripts.relief import region as cli
from skippercast.platform.contracts import OWNER_DISPLAY_BASIS
from skippercast.relief import envelope, package, receipts
from tests._support import FIXTURES, ROOT

REGION = 'morro-bay'
SOURCE = 'synthetic-grid'
CHUNK = 'layers/public/relief.digests/8/2_1.json'
OWNER_DISPLAY = {'decision': 'allowed', 'basis': OWNER_DISPLAY_BASIS}
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


def inputs(root, *, include_digests=True, style=None):
    region = receipts.Region(root, REGION)
    layers = {p: b for p, b in LAYERS.items() if include_digests or 'relief.digests' not in p}

    def tiles(output):
        for name, blob in layers.items():
            path = output / name.removeprefix('layers/public/')
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        if style is not None:
            return {'style': {'built_with': style['built_with']}}

    assert receipts.run_stage(receipts.StageRun(region, 'tiles', tiles, 'a' * 64,
                                                plan=lambda _: receipts.Plan(params={} if style is None else
                                                    dict(engine='nearshore', baked=style['baked'])),
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
    contours = ('--upstream', 'contours') if region.receipt_path('contours').exists() else ()
    return run(region, 'package', '--manifest', manifest, '--upstream', 'tiles:public', *contours)


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


def approved(root, *, include_digests=True, style=None):
    region, manifest = inputs(root, include_digests=include_digests, style=style)
    if style is not None and style['contours'] is not None:
        def contours(out):
            (out / 'native.geojson').write_bytes(b'{"type":"FeatureCollection","features":[]}')

        assert receipts.run_stage(receipts.StageRun(region, 'contours', contours, 'c' * 64,
            plan=lambda _: receipts.Plan(params={'set': 'ft-v3', 'contours': style['contours']}),
            target='layers/contours')).state == 'ok'
    gen, release, qa = release_and_qa(region, manifest)
    assert run(region, 'envelope', '--generation', gen) == 0
    review = region.dir / 'review' / gen / 'envelope.json'
    approval = review.with_name('approval.json')
    write_json(approval, {'envelope_sha256': sha(review), 'verdict': f'APPROVED release {REGION} envelope={sha(review)}',
                          'card_id': 'fixture', 'reviewer': 'fixture', 'time': '2000-01-01T00:00:00Z'})
    return region, release, qa, review, approval


def kit_style():
    versions = json.loads((ROOT / 'style/index.json').read_bytes())['versions']
    version = versions['nearshore-v1.0.0']
    return dict(baked=version['digests']['baked'], contours=version['digests']['contours'],
                built_with='nearshore-v1.0.0', habitat=None)


def test_e_frozen_style_schema_at_both_levels(tmp_path, assembly):
    # An additive pointer member must be optional but cannot accept rev-2 provenance or malformed keys.
    _, _, _, review, approval = approved(tmp_path)
    pointer = envelope.build_pointer(approval, review)
    prior = {key: pointer[key] for key in ('generation', 'release_sha256', 'envelope_sha256', 'sha256')}
    kit = kit_style() | {'contours': None}
    assert package.validate_schema(pointer, package.pointer_schema()) is None
    for wrap in (lambda s: pointer | {'style': s}, lambda s: pointer | {'previous': prior | {'style': s}}):
        package.validate_schema(wrap(kit), package.pointer_schema())
        for bad in (kit | {'baked': 'z' * 64}, kit | {'contours': '0' * 63}, kit | {'habitat': {}},
                    kit | {'extra': 1}, kit | {'built_with': {'tiles': kit['built_with']}},
                    kit | {'built_with': 'ok\n'}, {k: v for k, v in kit.items() if k != 'habitat'}):
            with pytest.raises(package.ReleaseError):
                package.validate_schema(wrap(bad), package.pointer_schema())


def style_fixture_data():
    from scripts.style.gen_style import group_digests, look_table

    kit = kit_style()
    tokens = json.loads((ROOT / 'style/nearshore-v1.0.0.json').read_bytes())
    rules = json.loads((ROOT / 'style/groups.json').read_bytes())
    next_tokens = copy.deepcopy(tokens)
    next_tokens['depth_ramp']['stops_ft'][0][1] = '#E0F8F4'
    next_tokens['version'] = '1.1.0'
    digests = group_digests(next_tokens, rules)
    bumped = kit | {'built_with': 'nearshore-v1.1.0',
                    'baked': digests['baked']}
    index = json.loads((ROOT / 'style/index.json').read_bytes())
    index['versions'][bumped['built_with']] = {'status': 'rolling', 'digests': digests}
    web, _, coast = look_table(index, {kit['built_with']: tokens, bumped['built_with']: next_tokens})
    return kit, bumped, {'web': web, 'coast': coast}


def composed_pointers(tmp_path):
    kit, bumped, _ = style_fixture_data()
    pointers = {}
    for name, style, previous in (('legacy', None, None), ('v1', kit, None),
                                  ('v1-no-contours', kit | {'contours': None}, None),
                                  ('v1_1-prev-v1', bumped, 'v1')):
        _, _, _, review, approval = approved(tmp_path / name, style=style)
        assert envelope.verify_chain(approval, review).release.get('style') == style
        pointer = envelope.build_pointer(approval, review, previous=pointers.get(previous))
        assert pointer.get('style') == style
        if previous is not None:
            assert pointer['previous']['style'] == kit
        pointers[name] = pointer
    return pointers


def test_f_composed_pointer_fixtures(tmp_path, assembly):
    # Cross-language consumers read committed producer bytes; only identity hashes may drift.
    def masked(pointer):
        pointer = copy.deepcopy(pointer)
        for block in (pointer, pointer['previous']):
            if block is not None:
                for key in ('generation', 'release_sha256', 'envelope_sha256'):
                    assert re.fullmatch('[0-9a-f]{64}', block[key])
                    block[key] = '0' * 64
        return receipts.canonical(pointer)

    for name, pointer in composed_pointers(tmp_path).items():
        raw = (FIXTURES / 'relief/pointer-style' / f'{name}.json').read_bytes()
        committed = json.loads(raw)
        assert receipts.canonical(committed) == raw
        assert masked(pointer) == masked(committed)
    assert (FIXTURES / 'relief/pointer-style/looks.json').read_bytes() == receipts.canonical(style_fixture_data()[2])


def test_h_verify_chain_refuses_malformed_style_even_when_resealed(tmp_path, assembly):
    # Make all transport identities agree so only the malformed style can cause rejection.
    _, release, qa, review, approval = approved(tmp_path, style=kit_style())
    doc = json.loads(release.read_bytes())
    doc['style']['built_with'] = {'tiles': 'nearshore-v1.0.0'}
    write_json(release, doc)
    write_json(qa, json.loads(qa.read_bytes()) | {'release_sha256': sha(release)})
    env = json.loads(review.read_bytes())
    for name, path in (('release', release), ('qa', qa)):
        env[name]['sha256'] = sha(path)
    write_json(review, env)
    digest = sha(review)
    write_json(approval, json.loads(approval.read_bytes()) | {'envelope_sha256': digest,
                                  'verdict': f'APPROVED release {REGION} envelope={digest}'})
    with pytest.raises(package.ReleaseError, match='invalid relief style block'):
        envelope.verify_chain(approval, review)


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


def test_package_releases_owner_cleared_candidate(tmp_path, assembly):
    # Contract (DATA-LIVE-ROUTING §2): a relief release is derived display, so a candidate row with the owner's G
    # display decision releases even with an unresolved licence and a raw-redistribution denial, and the catalogue
    # row is not promoted. Bug caught: the Morro ROLL-A package refusing every owner-cleared relief source.
    catalog = assembly / 'catalog/sources.json'
    rows = json.loads(catalog.read_bytes())
    rows['sources'][0].update(review_status='candidate', publication_allowed=False)
    rows['sources'][0]['rights'].update(license='unresolved', owner_public_display=OWNER_DISPLAY)
    write_json(catalog, rows)
    region, manifest = inputs(tmp_path / 'out')
    doc = json.loads(manifest.read_bytes())
    doc['sources'][0]['rights']['license'] = 'unresolved'
    write_json(manifest, doc)
    assert run_package(region, manifest) == 0
    assert list(region.dir.glob('release/*/release.json'))


@pytest.mark.parametrize('change', ['private-source', 'held-catalog-row', 'publication-denied', 'owner-marker-wrong-basis',
                                    'owner-cleared-display-held',
                                    'unknown-source',
                                    'excluded-mbari', 'out-of-region', 'unlisted-digest', 'unreceipted-layer', 'uncertified-z16'])
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
    elif change == 'publication-denied':
        # Contract: an approved, display-allowed row with an explicit publication denial and no owner display
        # decision is not releasable. Bug caught: the SCA-126 display decision dropping that veto from the relief gate.
        rows['sources'][0]['publication_allowed'] = False
    elif change == 'owner-marker-wrong-basis':
        # Contract: only the recorded G basis clears a candidate row. Bug caught: any owner marker releasing.
        rows['sources'][0].update(review_status='candidate', publication_allowed=False)
        rows['sources'][0]['rights']['owner_public_display'] = {'decision': 'allowed', 'basis': 'unrecorded'}
    elif change == 'owner-cleared-display-held':
        # Contract: the owner decision never overrides a display hold. Bug caught: owner marker skipping display.
        rows['sources'][0]['rights'].update(public_display='private', owner_public_display=OWNER_DISPLAY)
    elif change == 'unknown-source':
        rows['sources'].clear()
    elif change == 'excluded-mbari':
        # The owner decision never clears MBARI lineage.
        rows['sources'][0]['provider'] = 'MBARI'
        rows['sources'][0]['rights']['owner_public_display'] = OWNER_DISPLAY
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


@pytest.mark.parametrize('private_ref', [True, False], ids=['private-upstream', 'private-layer-path'])
def test_package_rejects_private_vector_input(tmp_path, assembly, capsys, private_ref):
    # A private ref is refused before receipt lookup; a private path before layer binding.
    region, manifest = inputs(tmp_path / 'out')
    args = []
    if private_ref:
        args = ['--upstream', 'nearshore_vectors:private']
        reason = 'package needs unique upstream refs from public layer stages'
    else:
        doc = json.loads(manifest.read_bytes())
        doc['layer_paths'].append('layers/private/nearshore/piles.geojson')
        write_json(manifest, doc)
        reason = 'not a public layer path'
    with pytest.raises(SystemExit) as exc:
        run(region, 'package', '--manifest', manifest, '--upstream', 'tiles:public', *args)
    assert exc.value.code == 2 and reason in capsys.readouterr().err
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
