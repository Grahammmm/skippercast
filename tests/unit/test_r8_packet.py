"""Offline acceptance at the packet CLI boundary, using the relief producers."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.relief import r8_packet
from skippercast.relief import envelope, package
from tests._support import ROOT
from tests.unit import test_relief_package as fixture
from tests.unit.test_relief_package import assembly  # noqa: F401 (pytest fixture)


@pytest.fixture
def build(tmp_path, assembly, monkeypatch):  # noqa: F811
    out = tmp_path / 'out'
    contract = (assembly / 'regions' / fixture.REGION / 'region.json').read_bytes()
    inputs = {}

    def make(name, *, west=-121.3, review=True, extra_layer=False):
        if name not in inputs:
            path = assembly / 'regions' / name / 'region.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(contract)
            with monkeypatch.context() as patch:
                patch.setattr(fixture, 'REGION', name)
                if extra_layer:
                    patch.setitem(fixture.LAYERS, 'layers/public/extra.geojson', b'{"type":"FeatureCollection","features":[]}')
                region, shared_manifest = fixture.inputs(out)
            manifest = shared_manifest.with_name(f'{name}-layers.json')
            shared_manifest.rename(manifest)
            inputs[name] = region, manifest
        region, manifest = inputs[name]
        doc = json.loads(manifest.read_bytes())
        doc['bounds'][0] = west
        fixture.write_json(manifest, doc)
        gen, release, qa = fixture.release_and_qa(region, manifest)
        if review:
            assert fixture.run(region, 'envelope', '--generation', gen) == 0
        return region, release, qa, region.dir / 'review' / gen / 'envelope.json'

    return out, make


def _snapshot(root):
    return {p.relative_to(root): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in root.rglob('*')}


def _ready(built, count=4):
    region, release, qa, review = built
    return (
        f'READY {region.id}\n'
        f'  generation: {release.parent.name}\n'
        f'  envelope.json sha256: {fixture.sha(review)}\n'
        f'  release.json sha256: {fixture.sha(release)}\n'
        f'  qa.json sha256: {fixture.sha(qa)}\n'
        f'  layers: {count}\n'
        f'APPROVED release {region.id} envelope={fixture.sha(review)}\n'
    )


def test_C1_prints_current_exact_bindings_for_three_regions(build, capsys):
    """C1: Catch selecting a historical generation, mixing hashes, or dropping a region."""
    out, make = build
    old = make('fixture-west')
    current = make('fixture-west', west=-121.2)
    assert old[3].is_file() and old[3] != current[3]
    middle = make('fixture-middle')
    east = make('fixture-east', extra_layer=True)
    capsys.readouterr()
    before = _snapshot(out)

    assert r8_packet.main(['--out', str(out), 'fixture-east', 'fixture-west', 'fixture-middle']) == 0
    assert capsys.readouterr() == (_ready(east, 5) + _ready(current) + _ready(middle), '')
    assert _snapshot(out) == before  # C3: successful pre-approval review writes nothing.


@pytest.mark.parametrize(('artifact', 'reason'), [
    ('envelope', 'envelope identity does not match its region and generation'),
    ('invalid-json', 'Expecting property name enclosed in double quotes: line 1 column 2 (char 1)'),
    ('release', 'release.json does not match envelope'),
    ('qa', 'qa.json does not match envelope'),
    ('layer', f'layer hash or size changed: {package.ARCHIVE}'),
])
def test_C2_withholds_verdict_when_binding_fails(build, capsys, artifact, reason):
    """C2: Catch trusting an envelope without checking all of its bound files."""
    out, make = build
    region, release, qa, review = make('fixture-west')
    if artifact == 'envelope':
        fixture.write_json(review, json.loads(review.read_bytes()) | {'region': 'other'})
    elif artifact == 'invalid-json':
        review.write_bytes(b'{')
    else:
        path = {'release': release, 'qa': qa, 'layer': region.dir / package.ARCHIVE}[artifact]
        path.write_bytes(path.read_bytes() + b'\n')
    capsys.readouterr()

    assert r8_packet.main(['--out', str(out), region.id]) == 1
    assert capsys.readouterr() == (f'NOT READY {region.id}: {reason}\n', '')


def test_C2_never_falls_back_to_a_previous_envelope(build, capsys):
    """C2: A new package without an envelope must not make the old one reviewable."""
    out, make = build
    name = 'fixture-west'
    old = make(name)
    _, _, _, review = make(name, west=-121.2, review=False)
    assert old[3].is_file() and old[3] != review
    capsys.readouterr()

    assert r8_packet.main(['--out', str(out), name]) == 1
    relative = f'review/{review.parent.name}/envelope.json'
    assert capsys.readouterr() == (f'NOT READY {name}: artifact is missing or not a file: {relative!r}\n', '')


@pytest.mark.parametrize(('problem', 'reason'), [
    ('missing', "artifact is missing or not a file: 'stages/package.json'"),
    ('invalid', 'invalid package receipt: generation is not 64 hex'),
    ('failed', 'package receipt status is failed'),
])
def test_C2_refuses_without_a_current_package_receipt(build, capsys, problem, reason):
    """C2: Catch guessing a generation from the directory or accepting an unusable receipt."""
    out, make = build
    name = 'fixture-west'
    if problem != 'missing':
        region, *_ = make(name)
        path = region.receipt_path('package')
        change = {'generation': 'latest'} if problem == 'invalid' else {'status': 'failed'}
        fixture.write_json(path, json.loads(path.read_bytes()) | change)
    capsys.readouterr()

    assert r8_packet.main(['--out', str(out), name]) == 1
    assert capsys.readouterr() == (f'NOT READY {name}: {reason}\n', '')


def test_C2_publish_verifier_still_requires_approval(build):
    """C2: Sharing artifact verification must not make approval optional for publishing."""
    _, make = build
    _, _, _, review = make('fixture-west')
    approval = review.with_name('approval.json')
    with pytest.raises(package.ReleaseError) as exc:
        envelope.verify_chain(approval, review)
    assert type(exc.value) is package.ReleaseError
    assert type(exc.value.__cause__) is FileNotFoundError
    assert Path(exc.value.__cause__.filename) == approval


def test_C3_mixed_batch_finishes_read_only_with_exit_one(build, capsys):
    """C3: Catch early exit, losing the failure status, or writing to OUT in either case."""
    out, make = build
    ready = make('fixture-east')
    capsys.readouterr()
    before = _snapshot(out)

    assert r8_packet.main(['--out', str(out), 'fixture-west', 'fixture-east']) == 1
    missing = "NOT READY fixture-west: artifact is missing or not a file: 'stages/package.json'\n"
    assert capsys.readouterr() == (missing + _ready(ready), '')
    assert _snapshot(out) == before


@pytest.mark.parametrize('args', [[], ['--out', 'out'], ['fixture-west'],
                                  ['--out', 'out', 'a', 'b', 'c', 'd'],
                                  ['--out', 'out', '../west']])
def test_C3_bad_usage_exits_two(tmp_path, args):
    """C3: Catch a missing argument, oversized batch, or unsafe region reaching verification."""
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts/relief/r8_packet.py'), *args],
                          cwd=tmp_path, capture_output=True, text=True, check=False)
    assert (proc.returncode, proc.stdout, list(tmp_path.iterdir())) == (2, '', [])
