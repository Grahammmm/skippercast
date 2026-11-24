"""Offline R8 attachment checks: no stages, rendering, or approval."""

from base64 import b64decode
from hashlib import sha256
import json
from shutil import copyfile

import pytest

from scripts.relief import central_camera_evidence, central_preview_attachment
from skippercast.relief import envelope, package
from tests._support import ROOT

REGION = 'big-sur-coast'


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def _digest(path):
    return sha256(path.read_bytes()).hexdigest()


def _synthetic_envelope(tmp_path, region, *, generation='a' * 64):
    root = tmp_path / 'artifacts' / region
    layers = []
    for relative in (package.DIGEST_ROOT, package.ARCHIVE):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic layer ' + path.name.encode())
        layers.append({'path': relative, 'sha256': _digest(path), 'bytes': path.stat().st_size})

    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    release = _write(root / 'release' / generation / 'release.json', {
        'schema': package.RELEASE_SCHEMA, 'region': region, 'generation': generation,
        'private': False, 'disclaimer': package.DISCLAIMER, 'code_sha': '0' * 40,
        'bounds': [-122, 35, -121, 36], 'minzoom': 8, 'maxzoom': 8,
        'sources': [{'id': 'fixture', 'label': 'estimated', 'attribution': 'Synthetic survey',
                     'vertical_datum': 'NAVD88', 'survey_dates': ['2000'],
                     'rights_class': 'public', 'rights': rights}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': 'fixture', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2}]},
        'native_support_by_zoom': {'8': {'limit_m': 91.44, 'tiles': 1, 'sources': []}},
        'layers': layers, 'digest_root_sha256': layers[0]['sha256'],
    })
    qa = _write(root / 'qa' / generation / 'qa.json', {
        'status': 'PASS', 'release_sha256': _digest(release), 'synthetic': True,
    })
    return _write(root / 'review' / generation / 'envelope.json', {
        'schema': envelope.ENVELOPE_SCHEMA, 'region': region, 'generation': generation, 'layers': layers,
        'release': {'path': release.relative_to(root).as_posix(), 'sha256': _digest(release)},
        'qa': {'path': qa.relative_to(root).as_posix(), 'sha256': _digest(qa)},
    })


@pytest.fixture
def inputs(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(tmp_path))
    for relative in ('schemas/sc-render-v1.schema.json', 'catalog/relief/pointer.schema.json',
                     'style/index.json', 'style/groups.json', 'style/nearshore-v1.0.0.json'):
        dest = tmp_path / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        copyfile(ROOT / relative, dest)
    _write(tmp_path / 'catalog/sources.json', {'sources': [{
        'id': 'fixture', 'review_status': 'approved',
        'rights': {'public_display': 'allowed', 'license': 'public-domain'},
    }]})
    recipe = _write(tmp_path / 'regions' / REGION / 'render.json', {
        'schema': 'sc-render/1', 'region': REGION, 'style': 'nearshore-v1.0.0', 'piers': [],
        'previews': [{'id': 'synthetic-window', 'center': [-121.4, 35.4], 'size_m': 1200, 'zoom': 15}],
    })
    selected = _synthetic_envelope(tmp_path, REGION)
    assert envelope.verify_artifacts(selected).envelope_sha256 == _digest(selected)
    assert central_camera_evidence.main([REGION]) == 0
    evidence = tmp_path / 'evidence.json'
    evidence.write_bytes(capsys.readouterr().out.encode('utf-8'))
    return selected, evidence, recipe


def _args(selected, evidence, expected, *, scratch_root=None):
    return [REGION, '--scratch-root', str(scratch_root or evidence.parent),
            '--envelope', str(selected), '--evidence', str(evidence),
            '--expected-evidence-sha256', expected]


def _refuses(args, capsys, reason):
    with pytest.raises(SystemExit) as exc:
        central_preview_attachment.main(args)
    assert exc.value.code == 2
    output = capsys.readouterr()
    assert output.out == ''
    assert reason in output.err


def test_binds_exact_selected_bytes(inputs, capsys):
    # Reserializing evidence or hashing the parsed envelope would lose byte identity.
    selected, evidence, _ = inputs
    evidence.write_bytes(evidence.read_bytes().replace(b'\n', b'\r\n') + b' \t')
    assert central_preview_attachment.main(_args(selected, evidence, _digest(evidence))) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['region'] == REGION
    assert output['envelope_sha256'] == _digest(selected)
    assert output['evidence_sha256'] == _digest(evidence)
    assert b64decode(output['evidence_base64'], validate=True) == evidence.read_bytes()
    assert 'not historical capture provenance' in output['scope']


def test_envelope_pin_distinguishes_releases_with_the_same_current_recipe(inputs, capsys, monkeypatch):
    # Checking only the recipe pin and region silently accepts a different release.
    selected, evidence, _ = inputs
    other = _synthetic_envelope(evidence.parent, REGION, generation='b' * 64)
    selected_pin, other_pin = _digest(selected), _digest(other)
    assert selected_pin != other_pin
    raw = evidence.read_bytes() + b' \t'
    evidence.write_bytes(raw)
    evidence_pin = _digest(evidence)

    for path, pin in ((selected, selected_pin), (other, other_pin)):
        args = _args(path, evidence, evidence_pin) + ['--expected-envelope-sha256', pin]
        assert central_preview_attachment.main(args) == 0
        output = json.loads(capsys.readouterr().out)
        assert output['envelope_sha256'] == pin
        assert output['evidence_sha256'] == evidence_pin
        assert b64decode(output['evidence_base64'], validate=True) == raw

    def unexpected_producer(*args, **kwargs):
        pytest.fail('rejected envelope pins must not run the recipe producer')

    monkeypatch.setattr(central_preview_attachment.subprocess, 'run', unexpected_producer)
    args = _args(other, evidence, evidence_pin) + ['--expected-envelope-sha256']
    _refuses(args + [selected_pin], capsys, 'envelope SHA-256 does not match the explicit pin')
    for malformed in ('', other_pin.upper(), other_pin[:-1], other_pin + '\n', 'g' * 64):
        _refuses(args + [malformed], capsys, 'expected envelope SHA-256 must be 64 lowercase hex digits')


def test_rejects_stale_recipe_after_one_byte_config_change(inputs, capsys):
    # Checking only the supplied digest or unchanged labels admits a superseded crop.
    selected, evidence, recipe = inputs
    recipe.write_bytes(recipe.read_bytes().replace(b'1200', b'1201'))
    assert central_camera_evidence.main([REGION]) == 0
    current = capsys.readouterr().out.encode('utf-8')
    assert json.loads(current)['sha256'] != json.loads(evidence.read_bytes())['sha256']
    _refuses(_args(selected, evidence, _digest(evidence)), capsys, 'stale camera evidence')


def test_requires_expected_full_file_digest(inputs, capsys):
    # A canonical-only comparison accepts the right recipe with the wrong file bytes.
    selected, evidence, _ = inputs
    previous_digest = _digest(evidence)
    evidence.write_bytes(evidence.read_bytes() + b'\n')
    _refuses(_args(selected, evidence, previous_digest), capsys,
             'evidence file SHA-256 does not match the explicit pin')
    _refuses(_args(selected, evidence, previous_digest)[:-2], capsys, '--expected-evidence-sha256')


@pytest.mark.parametrize('escape', ['evidence-symlink', 'envelope-dependencies'])
def test_rejects_inputs_outside_explicit_scratch_root(inputs, tmp_path, capsys, escape):
    # A lexical-only check follows an evidence symlink; checking only the two
    # nominated files allows the verifier to read release/QA/layers outside scratch.
    selected, evidence, _ = inputs
    if escape == 'evidence-symlink':
        scratch = tmp_path / 'artifacts'
        alias = scratch / 'evidence.json'
        alias.symlink_to(evidence)
    else:
        scratch = selected.parent
        alias = scratch / 'evidence.json'
        copyfile(evidence, alias)
    _refuses(_args(selected, alias, _digest(evidence), scratch_root=scratch), capsys,
             'must be inside the scratch directory')


@pytest.mark.parametrize(('mutation', 'reason'), [
    ('extra', 'unknown camera evidence schema'),
    ('region', 'camera evidence belongs to another region'),
    ('recipe', 'stale camera evidence'),
])
def test_rejects_invalid_evidence_even_when_bytes_are_pinned(inputs, capsys, mutation, reason):
    # An open schema, missing region check, or trust in the copied inner SHA would
    # respectively admit a provenance claim, a wrong region, or tampered cameras.
    selected, evidence, _ = inputs
    doc = json.loads(evidence.read_bytes())
    if mutation == 'extra':
        doc['capture_used_these_cameras'] = True
    elif mutation == 'region':
        doc['region'] = 'monterey-point-sur'
    else:
        doc['cameras'][0][3] += 1
    _write(evidence, doc)
    _refuses(_args(selected, evidence, _digest(evidence)), capsys, reason)


@pytest.mark.parametrize(('mutation', 'reason'), [
    ('region', 'selected envelope belongs to another region'),
    ('schema', 'envelope identity does not match'),
    ('layer', 'layer hash or size changed'),
])
def test_requires_verified_envelope_for_requested_region(inputs, tmp_path, capsys, mutation, reason):
    # Hashing the envelope without verifying it could bind the wrong region,
    # an unsupported format, or an envelope whose pinned layer has changed.
    selected, evidence, _ = inputs
    if mutation == 'region':
        selected = _synthetic_envelope(tmp_path, 'monterey-point-sur')
        assert envelope.verify_artifacts(selected).release['region'] == 'monterey-point-sur'
    elif mutation == 'schema':
        _write(selected, json.loads(selected.read_bytes()) | {'schema': 'sc-relief-envelope/999'})
    else:
        (selected.parents[2] / package.ARCHIVE).write_bytes(b'changed synthetic layer')
    _refuses(_args(selected, evidence, _digest(evidence)), capsys, reason)
