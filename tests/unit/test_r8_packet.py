"""Offline acceptance at the packet CLI boundary, using the relief producers."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.relief import r8_packet
from skippercast.relief import envelope, package, receipts
from tests._support import ROOT
from tests.unit import test_relief_package as fixture
from tests.unit.test_relief_package import assembly  # noqa: F401 (pytest fixture)


@pytest.fixture
def build(tmp_path, assembly, monkeypatch):  # noqa: F811
    out = tmp_path / 'out'
    contract = (assembly / 'regions' / fixture.REGION / 'region.json').read_bytes()
    inputs = {}

    def make(name, *, west=-121.3, review=True, extra_layer=False, qa_fields=None, shots=()):
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
        if qa_fields is not None or shots:
            report = json.loads(qa.read_bytes()) | (qa_fields or {})

            def write_qa(target):
                for row, data in shots:
                    path = target / row['path']
                    path.parent.mkdir(exist_ok=True)
                    path.write_bytes(data)
                if shots:
                    report['shots'] = {'renderer': 'mb08-chart', 'center': [-121.2, 35.2], 'cameras': [8, 13],
                                       'entries': [row | {'sha256': fixture.sha(target / row['path'])}
                                                   for row, _ in shots]}
                fixture.write_json(target / 'qa.json', report)

            assert receipts.run_stage(receipts.StageRun(region, 'qa', write_qa, 'c' * 64,
                upstream=[receipts.Ref('package')], target=f'qa/{gen}')).state == 'ok'
        if review:
            assert fixture.run(region, 'envelope', '--generation', gen) == 0
        return region, release, qa, region.dir / 'review' / gen / 'envelope.json'

    return out, make


def _snapshot(root):
    return {p.relative_to(root): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in root.rglob('*')}


_ABSENT = (
    '  status: PASS\n'
    '  z16plus_uncertified_pixels: absent\n'
    '  measured_label_uncertified_cells: absent\n'
    '  land_leak_pct: absent\n'
    '  contour_count_by_interval_ft: absent\n'
)


def _ready(built, count=4, summary=_ABSENT):
    region, release, qa, review = built
    return (
        f'READY {region.id}\n'
        f'  generation: {release.parent.name}\n'
        f'  envelope.json sha256: {fixture.sha(review)}\n'
        f'  release.json sha256: {fixture.sha(release)}\n'
        f'  qa.json sha256: {fixture.sha(qa)}\n'
        f'  layers: {count}\n'
        f'{summary}APPROVED release {region.id} envelope={fixture.sha(review)}\n'
    )


def test_C1_prints_current_exact_bindings_for_three_regions(build, capsys):
    """C1: Catch stale bindings, mixed metrics, and reporting an omitted key as zero."""
    out, make = build
    old = make('fixture-west')
    current = make('fixture-west', west=-121.2, qa_fields={'metrics': {
        'z16plus_uncertified_pixels': 0, 'measured_label_uncertified_cells': 0,
        'land_leak_pct': 0.0, 'contour_count_by_interval_ft': {'60': 2, '5': 9},
        'painted_pixels': 12,
    }})
    assert old[3].is_file() and old[3] != current[3]
    middle = make('fixture-middle')
    east = make('fixture-east', extra_layer=True, qa_fields={'metrics': {'contour_count_by_interval_ft': {}}})
    capsys.readouterr()
    before = _snapshot(out)

    assert r8_packet.main(['--out', str(out), 'fixture-east', 'fixture-west', 'fixture-middle']) == 0
    west_summary = (
        '  status: PASS\n'
        '  z16plus_uncertified_pixels: 0\n'
        '  measured_label_uncertified_cells: 0\n'
        '  land_leak_pct: 0.0\n'
        '  contour_count_by_interval_ft: {"5": 9, "60": 2}\n'
    )
    east_summary = _ABSENT.replace('contour_count_by_interval_ft: absent', 'contour_count_by_interval_ft: {}')
    assert capsys.readouterr() == (_ready(east, 5, east_summary) + _ready(current, summary=west_summary)
                                  + _ready(middle), '')
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


_SHOTS = (
    (dict(theme='dark', device='desktop', zoom=8, path='shots/dark-desktop-z8.png'), b'desktop PNG bytes'),
    (dict(theme='light', device='phone', zoom=13, path='shots/light-phone-z13.png'), b'phone PNG bytes'),
)


@pytest.mark.parametrize('problem', [None, 'changed', 'missing', 'invalid-path', 'not-png'])
def test_C2_binds_every_listed_shot_before_output(build, capsys, problem):
    """C2: Catch printing QA metadata before rechecking even the last shot's bytes."""
    out, make = build
    built = make('fixture-west', shots=_SHOTS)
    region, _, qa, review = built
    desktop = qa.parent / 'shots/dark-desktop-z8.png'
    file = 'shots/light-phone-z13.png'
    phone = qa.parent / file
    if problem == 'changed':
        phone.write_bytes(desktop.read_bytes())
    elif problem == 'missing':
        phone.rename(phone.with_suffix('.moved'))
    elif problem in ('invalid-path', 'not-png'):
        file = 'shots/../light-phone-z13.png' if problem == 'invalid-path' else 'shots/light-phone-z13.txt'
        (qa.parent / file).write_bytes(phone.read_bytes())
        report = json.loads(qa.read_bytes())
        report['shots']['entries'][1]['path'] = file
        _reseal_qa(qa, review, report)
    capsys.readouterr()
    before = _snapshot(out)

    code = r8_packet.main(['--out', str(out), region.id])
    if problem is None:
        summary = _ABSENT + (
            f'  shot: theme=dark device=desktop zoom=8 path=shots/dark-desktop-z8.png sha256={fixture.sha(desktop)}\n'
            f'  shot: theme=light device=phone zoom=13 path={file} sha256={fixture.sha(phone)}\n'
        )
        assert (code, *capsys.readouterr()) == (0, _ready(built, summary=summary), '')
    else:
        assert (code, *capsys.readouterr()) == (1, f'NOT READY {region.id}: shot {file} differs\n', '')
    assert _snapshot(out) == before


def _reseal_qa(qa, review, report):
    fixture.write_json(qa, report)
    doc = json.loads(review.read_bytes())
    doc['qa']['sha256'] = fixture.sha(qa)
    fixture.write_json(review, doc)


@pytest.mark.parametrize(('fields', 'reason'), [
    ({'metrics': []}, 'invalid QA metrics'),
    ({'shots': []}, 'invalid QA shot inventory'),
    ({'shots': {'entries': None}}, 'invalid QA shot inventory'),
    ({'shots': {'entries': [{}]}}, 'invalid QA shot entry'),
])
def test_C2_refuses_unusable_qa_fields(build, capsys, fields, reason):
    """C2: Catch accepting a malformed inventory as empty or crashing before the batch can continue."""
    out, make = build
    region, *_ = make('fixture-west', qa_fields=fields)
    capsys.readouterr()
    assert r8_packet.main(['--out', str(out), region.id]) == 1
    assert capsys.readouterr() == (f'NOT READY {region.id}: {reason}\n', '')


def test_C1_refuses_qa_drift_between_verification_and_display(build, capsys, monkeypatch):
    """C1: Catch displaying unbound metrics under the verified QA hash."""
    out, make = build
    region, _, qa, _ = make('fixture-west')
    verify = envelope.verify_artifacts

    def verify_then_replace(review):
        verified = verify(review)
        qa.write_bytes(qa.read_bytes() + b'\n')
        return verified

    monkeypatch.setattr(envelope, 'verify_artifacts', verify_then_replace)
    capsys.readouterr()
    assert r8_packet.main(['--out', str(out), region.id]) == 1
    assert capsys.readouterr() == (f'NOT READY {region.id}: qa.json does not match envelope\n', '')


@pytest.mark.parametrize('markdown', [False, True])
def test_C3_mixed_batch_finishes_read_only_with_exit_one(build, capsys, markdown):
    """C3: Catch early exit, losing the failure status, or writing to OUT in either case."""
    out, make = build
    ready = make('fixture-east', qa_fields={'metrics': {'land_leak_pct': 0.0}}, shots=_SHOTS[:1])
    region, release, qa, review = ready
    capsys.readouterr()
    before = _snapshot(out)

    flag = ['--markdown'] if markdown else []
    assert r8_packet.main([*flag, '--out', str(out), 'fixture-west', region.id]) == 1
    missing = "NOT READY fixture-west: artifact is missing or not a file: 'stages/package.json'"
    shot = ('theme=dark device=desktop zoom=8 path=shots/dark-desktop-z8.png '
            f'sha256={fixture.sha(qa.parent / "shots/dark-desktop-z8.png")}')
    if markdown:
        table = '| Field | Value |\n| --- | --- |\n'
        ready_table = (
            f'{table}| READY {region.id} |  |\n'
            f'| generation | {release.parent.name} |\n'
            f'| envelope.json sha256 | {fixture.sha(review)} |\n'
            f'| release.json sha256 | {fixture.sha(release)} |\n'
            f'| qa.json sha256 | {fixture.sha(qa)} |\n'
            '| layers | 4 |\n'
            '| status | PASS |\n'
            '| z16plus_uncertified_pixels | absent |\n'
            '| measured_label_uncertified_cells | absent |\n'
            '| land_leak_pct | 0.0 |\n'
            '| contour_count_by_interval_ft | absent |\n'
            f'| shot | {shot} |\n'
            f'| verdict | APPROVED release {region.id} envelope={fixture.sha(review)} |\n\n'
        )
        assert capsys.readouterr() == (f'{table}| {missing} |  |\n\n{ready_table}', '')
        assert r8_packet.main([*flag, '--out', str(out), region.id]) == 0
        assert capsys.readouterr() == (ready_table, '')
    else:
        summary = _ABSENT.replace('land_leak_pct: absent', 'land_leak_pct: 0.0') + f'  shot: {shot}\n'
        assert capsys.readouterr() == (f'{missing}\n' + _ready(ready, summary=summary), '')
    assert _snapshot(out) == before


@pytest.mark.parametrize('args', [[], ['--out', 'out'], ['fixture-west'],
                                  ['--out', 'out', 'a', 'b', 'c', 'd'],
                                  ['--out', 'out', '../west'],
                                  ['--markdown', '--out', 'out', 'a', 'b', 'c', 'd']])
def test_C3_bad_usage_exits_two(tmp_path, args):
    """C3: Catch a missing argument, oversized batch, or unsafe region reaching verification."""
    proc = subprocess.run([sys.executable, str(ROOT / 'scripts/relief/r8_packet.py'), *args],
                          cwd=tmp_path, capture_output=True, text=True, check=False)
    assert (proc.returncode, proc.stdout, list(tmp_path.iterdir())) == (2, '', [])
