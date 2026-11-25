"""Exercise the six-envelope manifest boundary with real, tiny artifact files."""
import json

import pytest

from scripts.relief import central_preview_identities as cli
from skippercast.relief import package
from tests.unit.test_r8_packet_compare import _candidate
from tests.unit.test_relief_package import assembly, sha, write_json  # noqa: F401 (assembly fixture)


@pytest.fixture
def inputs(tmp_path, assembly):
    # Reuse the existing verifier fixture. Add the receipt joins that the
    # single-envelope tests cannot cover: QA, contour pair and rights catalogue.
    rights = assembly / 'catalog/sources.json'
    root = tmp_path / 'six'
    pins = {}
    def ref(path, region):
        return {'path': path.relative_to(region).as_posix(), 'sha256': sha(path), 'bytes': path.stat().st_size}

    for i, name in enumerate(sorted(cli.REGIONS), 1):
        region, gen = root / name, str(i) * 64
        review = _candidate(region, gen)
        doc = json.loads(review.read_bytes())
        qa = region / doc['qa']['path']
        has_contours = name not in cli.TERRAIN_ONLY
        qa_doc = json.loads(qa.read_bytes())
        qa_doc['metrics']['contour_count_by_interval_ft'] = {'30': 1} if has_contours else {}
        write_json(qa, qa_doc)
        doc['qa']['sha256'] = sha(qa)
        write_json(review, doc)

        contour_gen = 'd' * 64
        contour_rows = []
        for relative in cli.CONTOUR_PAIR:
            path = region / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            write_json(path, {'type': 'FeatureCollection', 'provenance': {'region_id': name},
                              'features': [{'id': name}] if has_contours else []})
            contour_rows.append(ref(path, region))
        def receipt(stage, generation, outputs, upstream=(), inputs=()):
            write_json(region / 'stages' / f'{stage}.json', dict(
                schema='sc-stage-receipt/1', region=name, stage=stage, scope=None, generation=generation,
                status='ok', outputs=outputs, inputs=inputs, upstream=upstream, attempt=1))

        (region / 'stages').mkdir()
        contour_ref = {'stage': 'contours', 'generation': contour_gen}
        receipt('contours', contour_gen, contour_rows)
        receipt('package', gen, [ref(region / doc['release']['path'], region)], [contour_ref],
                [{'role': 'rights', 'sha256': sha(rights)}])
        receipt('qa', 'e' * 64, [ref(qa, region)], [contour_ref, {'stage': 'package', 'generation': gen}],
                [{'role': 'contours', **{k: contour_rows[0][k] for k in ('path', 'sha256')}}])
        pins[name] = dict(envelope_sha256=sha(review), release_sha256=doc['release']['sha256'],
                          qa_sha256=sha(qa), archive_sha256=sha(region / package.ARCHIVE), layers_rehashed=3,
                          candidate_kind='terrain+contours' if has_contours else 'terrain-only',
                          rights_catalogue_sha256=sha(rights), publication_signature=None)
    pinned = tmp_path / 'readback.json'
    write_json(pinned, {'scope': 'fixture readback', 'regions': pins})
    return root, pinned, sha(pinned)


def run(inputs):
    root, pinned, digest = inputs
    return cli.main(['--out', str(root), '--readback', str(pinned), '--readback-sha256', digest])


def test_preview_manifest_preserves_exact_six_and_separate_contour_pairs(inputs, capsys):
    # Dropping a region, signing a pointer, or passing empty contour pairs to staging is wrong.
    assert run(inputs) == 0
    first = capsys.readouterr().out
    assert run(inputs) == 0 and capsys.readouterr().out == first
    manifest = json.loads(first)
    assert manifest['schema'] == 'sc-central-preview-identities/1'
    assert manifest['purpose'] == 'offline-preview-only'
    assert str(inputs[0]) not in first and 'sc-relief-pointer' not in first
    rows = manifest['regions']
    assert len({row['preview_id'] for row in rows.values()}) == 6
    assert len([row for row in rows.values() if len(row['contours']) == 2]) == 4
    assert all(rows[name]['contours'] == [] for name in cli.TERRAIN_ONLY)
    pins = json.loads(inputs[1].read_bytes())['regions']
    for name, row in rows.items():
        assert row['envelope_sha256'] == pins[name]['envelope_sha256']
        for layer in row['layers'] + row['contours']:
            assert layer['sha256'] == sha(inputs[0] / name / layer['path'])


@pytest.mark.parametrize(('mutation', 'reason'), [
    ('swap', 'envelope differs from pinned readback'),
    ('pointer', 'envelope differs from pinned readback'),
    ('missing-layer', 'artifact is missing'),
    ('changed-layer', 'layer hash or size changed'),
    ('wrong-overview', 'output bytes changed'),
    ('rebound-overview', 'overview is not a subset'),
    ('stale-contour-generation', 'current contours does not match'),
    ('changed-readback', 'readback sha256 mismatch'),
    ('wrong-rights', 'rights catalogue does not match'),
])
def test_batch_refuses_without_partial_identity(inputs, capsys, mutation, reason):
    # One bad candidate must never yield a partial six-region manifest, even if the other five pass.
    root, pinned, _ = inputs
    region = root / 'south-big-sur-san-simeon'
    envelope_path = next(region.glob('review/*/envelope.json'))
    if mutation == 'swap':
        envelope_path.write_bytes(next((root / 'big-sur-coast').glob('review/*/envelope.json')).read_bytes())
    elif mutation == 'pointer':
        write_json(envelope_path, {'schema': 'sc-relief-pointer/1', 'region': region.name, 'status': 'reviewed'})
    elif mutation == 'missing-layer':
        (region / package.ARCHIVE).unlink()
    elif mutation == 'changed-layer':
        (region / package.ARCHIVE).write_bytes(b'changed layer')
    elif mutation in ('wrong-overview', 'rebound-overview'):
        overview = region / cli.CONTOUR_PAIR[1]
        other = root / 'big-sur-coast' / cli.CONTOUR_PAIR[1]
        overview.write_bytes(other.read_bytes())
        if mutation == 'rebound-overview':
            doc = json.loads(overview.read_bytes())
            doc['provenance']['region_id'] = region.name
            write_json(overview, doc)
            stage_path = region / 'stages/contours.json'
            stage = json.loads(stage_path.read_bytes())
            stage['outputs'][1].update(sha256=sha(overview), bytes=overview.stat().st_size)
            write_json(stage_path, stage)
    elif mutation in ('stale-contour-generation', 'wrong-rights'):
        path = region / 'stages/package.json'
        stage = json.loads(path.read_bytes())
        if mutation == 'stale-contour-generation':
            stage['upstream'][0]['generation'] = 'f' * 64
        else:
            stage['inputs'][0]['sha256'] = 'f' * 64
        write_json(path, stage)
    else:
        pinned.write_bytes(pinned.read_bytes() + b'\n')
    assert run(inputs) == 2
    captured = capsys.readouterr()
    assert captured.out == '' and reason in captured.err
