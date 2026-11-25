"""Guard joins between the independent local region evidence producers."""
from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from scripts.relief import central_region_packet_compare as comparator

GEN = '8' * 64


def write(root, path, doc):
    raw = json.dumps(doc, sort_keys=True).encode()
    file = root / path
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(raw)
    return {'path': path, 'bytes': len(raw), 'sha256': sha256(raw).hexdigest()}


def stage(root, name, generation, parents=(), outputs=(), scope=None, inputs=()):
    leaf = f'{name}.{scope}' if scope else name
    write(root, f'stages/{leaf}.json', {'schema': 'sc-stage-receipt/1', 'region': root.name,
                                       'stage': name, 'scope': scope, 'status': 'ok', 'generation': generation,
                                       'upstream': parents, 'outputs': outputs, 'inputs': inputs})
    result = {'stage': name, 'generation': generation}
    if scope:
        result['scope'] = scope
    return result


def make_packet(tmp_path, monkeypatch, *, empty=False, wrong_rights=False, swapped=False, contours=False,
                stale_contours=False, missing_contours=False):
    region = 'big-sur-coast'
    root = tmp_path / region
    rights = 'a' * 64
    selection = write(root, 'select/selection.json', {'region': region, 'scope': 'public',
                                                       'files': [{'decision': 'included'}]})
    select_stage = stage(root, 'select', '1' * 64, outputs=[selection])
    mosaic = write(root, 'mosaic/public/manifest.json', {'stats': {'valid_cells': 12},
                    'band_0_300ft': {'contributor_cells': {'1': 0 if empty else 3}}})
    mosaic_stage = stage(root, 'mosaic', '2' * 64, [select_stage], [mosaic], scope='public')
    contour_stage = stage(root, 'contours', '5' * 64)
    package_stage = stage(root, 'package', GEN, [contour_stage],
                          inputs=[{'role': 'rights', 'sha256': 'b' * 64 if wrong_rights else rights}])
    shots = []
    # End cameras are selected from this release's zoom range; the deeper build must include z15.
    for theme in ('dark', 'light'):
        for zoom in (8, 10, 13, 15):
            relative = f'shots/{theme}-phone-z{zoom}.png'
            shot = root / 'qa' / GEN / relative
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(relative.encode())  # envelope/QA owns PNG validation; this check binds the bytes
            shots.append({'device': 'phone', 'theme': theme, 'zoom': zoom, 'viewport': [390, 844],
                          'path': relative, 'sha256': sha256(shot.read_bytes()).hexdigest()})
    qa = write(root, f'qa/{GEN}/qa.json', {'region': region,
               'shots': {'cameras': [8, 10, 13, 15], 'entries': shots},
               'metrics': {'contour_count_by_interval_ft': {'10': 2} if contours else {}}})
    qa_stage = stage(root, 'qa', '3' * 64, [package_stage, mosaic_stage, contour_stage], [qa])
    if stale_contours:
        stage(root, 'contours', '6' * 64)  # contours rebuilt after package and QA pinned the old receipt
    if missing_contours:
        (root / 'stages/contours.json').unlink()
    doc = {'schema': 'sc-relief-envelope/1', 'region': 'monterey-point-sur' if swapped else region,
           'generation': GEN, 'release': {}, 'qa': {}, 'layers': []}
    env = write(root, f'review/{GEN}/envelope.json', doc)
    stage(root, 'envelope', '4' * 64, [qa_stage, package_stage], [env])
    if not swapped:
        # The existing envelope owner validates release metadata, QA and all layer bytes;
        # the comparator must not accept some other QA, source rights or selection beside it.
        monkeypatch.setattr(comparator.envelope, 'verify_artifacts', lambda p: SimpleNamespace(
            generation=GEN, envelope_sha256=env['sha256'], qa_sha256=qa['sha256'], release_sha256=GEN,
            release={'region': region, 'minzoom': 8, 'maxzoom': 15}))
    return root, rights


@pytest.mark.parametrize(('contours', 'state'), [(False, 'local-terrain-only'), (True, 'local-ready')])
def test_local_terrain_does_not_stand_in_for_contour_qa(tmp_path, monkeypatch, contours, state):
    root, rights = make_packet(tmp_path, monkeypatch, contours=contours)
    actual = comparator._packet(root, rights)
    assert (actual['status'], actual['included_files'], actual['phone_views']) == (state, 1, 8)


@pytest.mark.parametrize(('problem', 'reason'), [
    ('empty', 'empty public selection or 0–300 ft coverage'),
    ('wrong_rights', 'rights catalogue digest'),
    ('swapped', 'envelope identity does not match'),
])
def test_region_rejects_empty_coverage_wrong_rights_or_swapped_envelope(tmp_path, monkeypatch, problem, reason):
    # Each input is correctly rehashed in its stage receipt, so a mere byte check cannot catch the mismatch.
    root, rights = make_packet(tmp_path, monkeypatch, **{problem: True})
    with pytest.raises(ValueError, match=reason):
        comparator._packet(root, rights)


def test_contours_rebuilt_after_qa_make_the_packet_stale(tmp_path, monkeypatch):
    # Contract: QA and package pin the contours receipt, so a later contours rebuild invalidates them.
    # Bug caught: only select/mosaic/package links were checked, so stale contour evidence stayed local-ready.
    root, rights = make_packet(tmp_path, monkeypatch, contours=True, stale_contours=True)
    with pytest.raises(ValueError, match='current contours does not match its pinned input'):
        comparator._packet(root, rights)


def test_missing_contours_receipt_is_incomplete(tmp_path, monkeypatch):
    root, rights = make_packet(tmp_path, monkeypatch, contours=True, missing_contours=True)
    result = comparator.compare(tmp_path)  # compare() reads the big-sur-coast packet; others are absent
    assert result['regions']['big-sur-coast']['status'] == 'incomplete'
    with pytest.raises(FileNotFoundError):
        comparator._packet(root, rights)


def test_missing_envelopes_are_incomplete_without_claiming_six_region_coverage(tmp_path):
    result = comparator.compare(tmp_path)
    assert set(result['regions']) == set(comparator.REGIONS) and len(result['regions']) == 6
    assert {row['status'] for row in result['regions'].values()} == {'incomplete'}
    assert result['status'] == 'incomplete'
