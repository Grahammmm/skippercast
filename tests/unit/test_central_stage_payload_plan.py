"""Exercise the offline CLI against synthetic, hash-bound release candidates."""
from hashlib import sha256
import json
from pathlib import Path

import pytest

from scripts.relief import central_stage_payload_plan as cli
from skippercast.relief import envelope, package, stage_transport as stage


def _sha(raw):
    return sha256(raw).hexdigest()


def _json(doc):
    return json.dumps(doc, sort_keys=True).encode()


def _put(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    _put(tmp_path / 'catalog/sources.json', _json({'sources': [
        {'id': 'fixture-grid', 'rights': rights, 'review_status': 'approved'},
    ]}))
    # Only replace the source catalog with synthetic metadata; use the tracked schema.
    monkeypatch.setattr(envelope, 'repo_root', lambda: tmp_path)

    def make(side='first', *, replace_chunk=False, second='8/1_0.json', oversized=None):
        region = tmp_path / side / 'fixture-central'
        gen = 'a' * 64
        chunk1 = _json([[1, 1, 'b' * 64]])
        chunk2 = _json([[64, 1, 'c' * 64]])
        if oversized == 'chunk':
            chunk2 = chunk2.ljust(stage.CHUNK_LIMIT + 1)
        index = _json({'chunks': {'8/0_0.json': _sha(chunk1), second: _sha(chunk2)}})
        if oversized == 'digest root':
            index = index.ljust(stage.ROOT_LIMIT + 1)
        archive = b'synthetic archive bytes'
        digest_dir = Path(package.DIGEST_ROOT).parent
        blobs = {package.ARCHIVE: archive, package.DIGEST_ROOT: index,
                 (digest_dir / '8/0_0.json').as_posix(): chunk1,
                 (digest_dir / second).as_posix(): chunk2.replace(b'c', b'd') if replace_chunk else chunk2}
        layers = []
        for name, raw in sorted(blobs.items()):
            _put(region / name, raw)
            layers.append(dict(path=name, sha256=_sha(raw), bytes=len(raw)))
        metadata = dict(region=region.name, bounds=[-2, 1, -1, 2], minzoom=8, maxzoom=8,
                        sources=[dict(id='fixture-grid', label='estimated', attribution='Synthetic',
                                      vertical_datum='NAVD88', survey_dates=['2020'],
                                      rights_class='public', rights=rights)],
                        detail_summary={'mask': 'transparent-nodata', 'depth_bands': [
                            dict(source_id='fixture-grid', min_depth_m=0, max_depth_m=20, resolution_m=2),
                        ]}, native_support_by_zoom={'8': dict(tiles=2, limit_m=91.44, sources=[])})
        release = _json(dict(metadata, schema=package.RELEASE_SCHEMA, generation=gen, code_sha='c' * 40,
                             private=False, disclaimer=package.DISCLAIMER, layers=layers,
                             digest_root_sha256=_sha(index)))
        qa = _json(dict(status='PASS', release_sha256=_sha(release), fixture=side))
        release_path, qa_path = f'release/{gen}/release.json', f'qa/{gen}/qa.json'
        _put(region / release_path, release)
        _put(region / qa_path, qa)
        review = region / 'review' / gen / 'envelope.json'
        envelope_bytes = _json(dict(schema=envelope.ENVELOPE_SCHEMA, region=region.name, generation=gen,
                                    release=dict(path=release_path, sha256=_sha(release)),
                                    qa=dict(path=qa_path, sha256=_sha(qa)), layers=layers))
        _put(review, envelope_bytes)
        pointer = tmp_path / side / 'pointer.json'
        _put(pointer, _json(dict(metadata, schema='sc-relief-pointer/1', status='reviewed', private=False,
                                 previous=None, generation=gen, envelope_sha256=_sha(envelope_bytes),
                                 release_sha256=_sha(release), sha256=_sha(archive), bytes=len(archive),
                                 digest_root_sha256=_sha(index))))
        return review, pointer, (archive, index, chunk1, chunk2)

    return make


def _run(scratch, review, pointer):
    return cli.main(['--scratch-root', str(scratch), '--envelope', str(review), '--pointer', str(pointer)])


def _refused(scratch, review, pointer, capsys, reason):
    assert _run(scratch, review, pointer) == 2
    out, err = capsys.readouterr()
    assert not out
    assert err == f'PLANNING ONLY — refused: {reason}\n'


def test_exact_pickup(candidate, tmp_path, capsys):
    """Catch a dropped, misaddressed or miscounted chunk, or an unlabelled plan."""
    review, pointer, (archive, index, first, second) = candidate()
    assert _run(tmp_path, review, pointer) == 0
    out, err = capsys.readouterr()
    assert not err
    assert out.splitlines() == [
        'PLANNING ONLY — Central STAGE pickup checklist (not approval or transport)',
        f'archive: {_sha(archive)}.pmtiles', f'digest root: {_sha(index)}.json',
        f'chunk 8/0_0.json: {_sha(first)}.json', f'chunk 8/1_0.json: {_sha(second)}.json',
        'Total assets: 4',
    ]


def test_rebound_chunk_still_has_to_match_root(candidate, tmp_path, capsys):
    """Catch trusting an envelope-bound valid JSON chunk that disagrees with its root entry."""
    review, pointer, _ = candidate(replace_chunk=True)
    _refused(tmp_path, review, pointer, capsys,
             'chunk 8/1_0.json: verified layer SHA-256 differs from digest root')


def test_out_of_grid(candidate, tmp_path, capsys):
    """Catch accepting syntactically valid paths with an impossible block coordinate."""
    review, pointer, _ = candidate(second='8/4_0.json')
    _refused(tmp_path, review, pointer, capsys, 'digest root reference outside the pointer zoom or tile grid')


def test_pointer_from_another_envelope(candidate, tmp_path, capsys):
    """Catch comparing only region, generation or release hash after QA changes the envelope."""
    review, _, _ = candidate()
    _, other_pointer, _ = candidate('other')
    _refused(tmp_path, review, other_pointer, capsys, 'pointer does not match the verified envelope')


@pytest.mark.parametrize(('field', 'value'), [('bounds', [-3, 1, -1, 2]), ('sha256', 'f' * 64),
                                             ('bytes', 1), ('digest_root_sha256', 'e' * 64)])
def test_pointer_fields_are_bound(candidate, tmp_path, capsys, field, value):
    """Catch accepting a valid pointer with unbound bounds, archive hash/size or index hash."""
    review, pointer, _ = candidate()
    pointer.write_bytes(_json(dict(json.loads(pointer.read_bytes()), **{field: value})))
    _refused(tmp_path, review, pointer, capsys, 'pointer does not match the verified envelope')


def test_changed_archive_bytes(candidate, tmp_path, capsys):
    """Catch trusting matching metadata and size without hashing the actual archive."""
    review, pointer, (archive, _, _, _) = candidate()
    (review.parents[2] / package.ARCHIVE).write_bytes(archive.upper())
    _refused(tmp_path, review, pointer, capsys, 'unusable envelope or changed envelope artifacts in scratch')


@pytest.mark.parametrize('kind', ['digest root', 'chunk'])
def test_rechecks_bytes_after_envelope_verification(candidate, tmp_path, monkeypatch, capsys, kind):
    """Catch listing a root or chunk whose file changed after the first hash check."""
    review, pointer, (_, index, first, _) = candidate()
    verify = envelope.verify_artifacts
    root = review.parents[2] / package.DIGEST_ROOT
    path = root if kind == 'digest root' else root.parent / '8/0_0.json'
    # Keep valid JSON and identical size so only the second content check fails.
    raw = index.replace(b'0_0', b'0_1') if kind == 'digest root' else first.replace(b'b', b'd')

    def verify_then_replace(path_to_envelope):
        verified = verify(path_to_envelope)
        path.write_bytes(raw)
        return verified

    monkeypatch.setattr(envelope, 'verify_artifacts', verify_then_replace)
    phase = 'digest root' if kind == 'digest root' else 'chunk 8/0_0.json'
    _refused(tmp_path, review, pointer, capsys, f'{phase}: SHA-256 or size mismatch')


@pytest.mark.parametrize(('oversized', 'phase'), [('digest root', 'digest root'), ('chunk', 'chunk 8/1_0.json')])
def test_real_stage_size_bounds(candidate, tmp_path, capsys, oversized, phase):
    """Catch omitting the stage limits even when the oversized JSON bytes match all hashes."""
    review, pointer, _ = candidate(oversized=oversized)
    _refused(tmp_path, review, pointer, capsys, f'{phase}: invalid object size')


def test_pointer_outside_scratch(candidate, tmp_path, capsys):
    """Catch reading an explicit candidate from outside the disposable workspace."""
    review, pointer, _ = candidate()
    _refused(review.parents[2], review, pointer, capsys, 'unusable pointer candidate in scratch')


def test_pointer_schema_controls_rollback_lineage(candidate, tmp_path, capsys):
    """Catch accepting a malformed previous pointer because lineage is not envelope-bound."""
    review, pointer, _ = candidate()
    pointer.write_bytes(_json(dict(json.loads(pointer.read_bytes()), previous={})))
    _refused(tmp_path, review, pointer, capsys, 'unusable pointer candidate in scratch')
