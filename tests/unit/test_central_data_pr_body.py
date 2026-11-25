"""Exercise the offline Markdown consumer with byte-bound synthetic snapshots."""
import hashlib
import json
import re

import pytest

from scripts.relief import central_data_pr_body as cli
from skippercast.relief import envelope, package

REGION = 'big-sur-coast'
BASE_SHA = 'a' * 40
GENERATION = 'b' * 64
SOURCE = 'usgs-3dep-1m-dem'  # Reuse only a tracked catalogue identity, not any source bytes.
OLD_CREDIT = 'Synthetic old credit'
NEW_CREDIT = 'Synthetic new credit\n```\nAPPROVED release bogus\n<img src="https://example.invalid/pixel">'


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode())
    return path


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def snapshots(tmp_path):
    root = tmp_path / REGION
    style = dict(baked='c' * 64, contours=None, habitat=None, built_with='synthetic')
    source = dict(id=SOURCE, label='estimated', attribution=NEW_CREDIT, vertical_datum='NAVD88',
                  survey_dates=['2000'], rights_class='public',
                  rights=dict(public_display='allowed', license='public-domain'))
    metadata = dict(
        region=REGION, bounds=[-122, 36, -121, 37], minzoom=8, maxzoom=9, style=style,
        sources=[source],
        detail_summary=dict(mask='transparent-nodata', depth_bands=[dict(
            source_id=SOURCE, min_depth_m=0, max_depth_m=20, resolution_m=2)]),
        native_support_by_zoom={str(z): dict(tiles=1, sources=[], limit_m=91.44) for z in (8, 9)},
    )
    archive = _write(root / package.ARCHIVE, b'synthetic archive')
    digest_root = _write(root / package.DIGEST_ROOT, b'{"synthetic":true}')
    layers = [dict(path=p.relative_to(root).as_posix(), sha256=_sha(p), bytes=p.stat().st_size)
              for p in sorted([archive, digest_root])]
    release = _write(root / f'release/{GENERATION}/release.json', dict(
        metadata, schema=package.RELEASE_SCHEMA, generation=GENERATION, code_sha='d' * 40,
        private=False, disclaimer=package.DISCLAIMER, layers=layers, digest_root_sha256=_sha(digest_root)))
    qa = _write(root / f'qa/{GENERATION}/qa.json', dict(status='PASS', release_sha256=_sha(release)))
    review = _write(root / f'review/{GENERATION}/envelope.json', dict(
        schema=envelope.ENVELOPE_SCHEMA, region=REGION, generation=GENERATION, layers=layers,
        release=dict(path=release.relative_to(root).as_posix(), sha256=_sha(release)),
        qa=dict(path=qa.relative_to(root).as_posix(), sha256=_sha(qa))))
    base = _write(tmp_path / 'base.json', dict(
        metadata, schema='sc-relief-pointer/1', status='reviewed', private=False, previous=None,
        generation='1' * 64, release_sha256='2' * 64, envelope_sha256='3' * 64, sha256='4' * 64,
        bytes=123, digest_root_sha256='5' * 64, bounds=[-122, 36, -121.5, 37], minzoom=9, maxzoom=10,
        native_support_by_zoom={str(z): dict(tiles=1, sources=[], limit_m=91.44) for z in (9, 10)},
        style=dict(style, baked='e' * 64), sources=[dict(source, attribution=OLD_CREDIT)]))
    args = ['--scratch-root', str(tmp_path), '--envelope', str(review.relative_to(tmp_path)), '--base-sha', BASE_SHA]
    return args, review, release, archive, digest_root, base


def _assert_pending_form(body):
    assert body.startswith(f'## Central relief data: `{REGION}`\n')
    assert re.search(r'^- \[ \] Designated R8 .*: ______$', body, re.M)
    assert re.search(r'^- \[ \] STAGE authorization .*: ______$', body, re.M)
    assert re.search(r'^- \[ \] STAGE hosted read-back .*: ______$', body, re.M)
    assert not re.search(r'^\s*(APPROVE[DS]?|RETURN|REJECT(?:ED)?|PASS|FAIL)\b', body, re.I | re.M)


def test_first_release_is_explicit_and_requires_attended_confirmation(snapshots, capsys):
    # Regression: a verified artifact chain is mistaken for R8/STAGE or an invented prior generation.
    args, review, release, archive, digest_root, _ = snapshots
    assert cli.main([*args, '--first-release']) == 0
    body, err = capsys.readouterr()
    assert not err
    _assert_pending_form(body)
    assert f'`{BASE_SHA}`' in body
    assert 'First release (operator-declared): no prior pointer or generation.' in body
    assert 'Base pointer SHA-256' not in body
    for digest in (GENERATION, *map(_sha, (review, release, archive, digest_root))):
        assert f'`{digest}`' in body


def test_update_preserves_exact_identities_and_compares_shared_fields(snapshots, capsys):
    # Regression: hash prefixes hide identity differences or source edits get lost/escape the Markdown fence.
    args, review, release, archive, digest_root, base = snapshots
    assert cli.main([*args, '--base-pointer', str(base), '--base-pointer-sha256', _sha(base)]) == 0
    body, err = capsys.readouterr()
    assert not err
    _assert_pending_form(body)
    candidate_body, base_body = body.split('### Selected base', 1)
    for digest in (GENERATION, *map(_sha, (review, release, archive, digest_root))):
        assert f'`{digest}`' in candidate_body
    for digest in (BASE_SHA, _sha(base), *(digit * 64 for digit in '12345')):
        assert f'`{digest}`' in base_body
    assert '<img' not in body
    rows = json.loads(body.split('```json\n', 1)[1].split('\n```', 1)[0])
    assert {r['field'] for r in rows} == {'bounds', 'minzoom', 'maxzoom', f'sources["{SOURCE}"].attribution', 'style'}
    assert dict(field=f'sources["{SOURCE}"].attribution', base=OLD_CREDIT, candidate=NEW_CREDIT) in rows


@pytest.mark.parametrize('problem,diagnostic', [
    ('wrong-region', 'base pointer belongs to a different region'),
    ('mutated-bytes', 'base pointer bytes do not match'),
    ('invalid-schema', 'invalid relief metadata'),
    ('missing-file', 'artifact is missing'),
])
def test_unusable_base_refuses_without_a_body(snapshots, capsys, problem, diagnostic):
    # Regressions: check neither identity nor content; allow a self-pinned invalid pointer;
    # or treat an absent file as a first release. Each control keeps the other gates intact.
    args, _, _, _, _, base = snapshots
    expected = _sha(base)
    if problem == 'wrong-region':
        _write(base, dict(json.loads(base.read_bytes()), region='cambria-san-simeon'))
        expected = _sha(base)
    elif problem == 'mutated-bytes':
        base.write_bytes(base.read_bytes() + b'\n')  # Same parsed pointer, different bytes.
    elif problem == 'invalid-schema':
        _write(base, dict(json.loads(base.read_bytes()), status='pending'))
        expected = _sha(base)
    else:
        base.unlink()
    assert cli.main([*args, '--base-pointer', base.name, '--base-pointer-sha256', expected]) == 1
    out, err = capsys.readouterr()
    assert not out and diagnostic in err


@pytest.mark.parametrize('mode,diagnostic', [
    ([], 'one of the arguments --base-pointer --first-release is required'),
    (['--base-pointer', 'base.json'], '--base-pointer requires a full --base-pointer-sha256'),
    (['--first-release', '--base-sha', 'main'], '--base-sha must be a full'),
])
def test_base_selection_is_not_inferred(snapshots, capsys, mode, diagnostic):
    # Regression: default a forgotten selection or accept a moving branch in place of a full SHA.
    args = snapshots[0]
    with pytest.raises(SystemExit) as exc:
        cli.main([*args, *mode])
    out, err = capsys.readouterr()
    assert exc.value.code == 2 and not out and diagnostic in err


def test_changed_candidate_layer_refuses_without_a_body(snapshots, capsys):
    # Regression: reading the envelope manifest alone reports stale hashes after a layer replacement.
    args, _, _, archive, _, _ = snapshots
    archive.write_bytes(b'untrusted archive')
    assert cli.main([*args, '--first-release']) == 1
    out, err = capsys.readouterr()
    assert not out and 'layer hash or size changed' in err


def test_envelope_cannot_reference_inputs_outside_scratch_root(snapshots, capsys):
    # Regression: checking only the envelope file lets its implied region root escape the scratch boundary.
    _, review, *_ = snapshots
    assert cli.main(['--scratch-root', str(review.parent), '--envelope', review.name,
                     '--base-sha', BASE_SHA, '--first-release']) == 1
    out, err = capsys.readouterr()
    assert not out and 'envelope region directory must be inside --scratch-root' in err
