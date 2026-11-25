"""Exercise the comparator CLI with real envelope, release, QA and layer bytes."""
import json
from shutil import copytree

import pytest

from scripts.relief import r8_packet_compare
from skippercast.relief import envelope, package
from tests.unit.test_relief_package import SOURCE, assembly, sha, write_json  # noqa: F401 (assembly fixture)


def _candidate(root, generation='a' * 64, sidecar='zone'):
    # Assemble only the bytes consumed by verify_artifacts: no stages, receipts or approvals.
    def ref(path):
        return {'path': path.relative_to(root).as_posix(), 'sha256': sha(path)}

    layers = []
    for name in sorted((package.ARCHIVE, package.DIGEST_ROOT, f'layers/public/{sidecar}.geojson')):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture layer')
        layers.append(ref(path) | {'bytes': path.stat().st_size})
    release = root / 'release' / generation / 'release.json'
    write_json(release, {
        'schema': package.RELEASE_SCHEMA, 'region': root.name, 'generation': generation,
        'code_sha': 'c' * 40, 'private': False, 'disclaimer': package.DISCLAIMER,
        'bounds': [-2, 1, -1, 2], 'minzoom': 8, 'maxzoom': 8,
        'sources': [{
            'id': SOURCE, 'attribution': 'Synthetic survey', 'rights_class': 'public', 'label': 'estimated',
            'vertical_datum': 'NAVD88', 'survey_dates': ['2020'],
            'rights': {'public_display': 'allowed', 'license': 'public-domain'},
        }],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [{
            'source_id': SOURCE, 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2,
        }]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
        'layers': layers, 'digest_root_sha256': sha(root / package.DIGEST_ROOT),
    })
    qa = root / 'qa' / generation / 'qa.json'
    write_json(qa, {'status': 'PASS', 'release_sha256': sha(release), 'metrics': {'land_leak_pct': 0.0}})
    review = root / 'review' / generation / 'envelope.json'
    write_json(review, {'schema': envelope.ENVELOPE_SCHEMA, 'region': root.name, 'generation': generation,
                        'release': ref(release), 'qa': ref(qa), 'layers': layers})
    return review


@pytest.fixture
def copies(tmp_path, assembly):
    left_root, right_root = (tmp_path / side / 'fixture-west' for side in ('left', 'right'))
    left = _candidate(left_root)
    copytree(left_root, right_root)
    return left, right_root / left.relative_to(left_root)


def _compare(left, right):
    return r8_packet_compare.main([str(left), str(right)])


def _changes(capsys):
    out, err = capsys.readouterr()
    heading, *rows = out.splitlines()
    assert heading.startswith('Different R8 candidates') and not err
    return dict(row.split(': ', 1) for row in rows)


def test_exact_copy_matches_read_only_without_approval(copies, tmp_path, capsys):
    """Match bytes across roots; catch path identity, approval/pointer lookup or writes."""
    def snapshot():
        return {path: (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
                for path in tmp_path.rglob('*')}

    before = snapshot()
    assert _compare(*copies) == 0
    assert capsys.readouterr() == ('Exact R8 candidate match for fixture-west.\n', '')
    assert snapshot() == before


def test_same_generation_rebound_qa_is_different(copies, capsys):
    """Catch generation-only comparison after a valid QA rerun of the same release."""
    left, right = copies
    document = json.loads(right.read_bytes())
    qa = right.parents[2] / document['qa']['path']
    report = json.loads(qa.read_bytes())
    report['metrics']['land_leak_pct'] = 0.125
    write_json(qa, report)
    document['qa']['sha256'] = sha(qa)
    write_json(right, document)

    assert _compare(left, right) == 1
    assert _changes(capsys) == {
        'envelope_sha256': f'{sha(left)} -> {sha(right)}',
        'qa_sha256': f"{sha(left.parents[2] / document['qa']['path'])} -> {sha(qa)}",
    }


def test_different_generations_report_digests_and_renamed_layer(tmp_path, assembly, capsys):
    """Catch masking individual differences or comparing layer counts instead of names."""
    left = _candidate(tmp_path / 'left' / 'fixture-west')
    right = _candidate(tmp_path / 'right' / 'fixture-west', generation='b' * 64, sidecar='other')

    assert _compare(left, right) == 1
    left_doc, right_doc = (json.loads(path.read_bytes()) for path in (left, right))
    assert _changes(capsys) == {
        'generation': f'{left.parent.name} -> {right.parent.name}',
        'envelope_sha256': f'{sha(left)} -> {sha(right)}',
        'release_sha256': f"{left_doc['release']['sha256']} -> {right_doc['release']['sha256']}",
        'qa_sha256': f"{left_doc['qa']['sha256']} -> {right_doc['qa']['sha256']}",
        'layer_names': (f'{package.DIGEST_ROOT}, {package.ARCHIVE}, layers/public/zone.geojson -> '
                        f'layers/public/other.geojson, {package.DIGEST_ROOT}, {package.ARCHIVE}'),
    }


@pytest.mark.parametrize('side', ['left', 'right'])
def test_unchanged_envelope_cannot_hide_corrupted_layer(copies, capsys, side):
    """Identical manifests cannot short-circuit verification of either package."""
    left, right = copies
    corrupt = left if side == 'left' else right
    (corrupt.parents[2] / package.ARCHIVE).write_bytes(b'changed layer')

    assert _compare(left, right) == 2
    out, err = capsys.readouterr()
    assert not out and f'Unusable {side} envelope: layer hash or size changed' in err


@pytest.mark.parametrize(('bad_bytes', 'reason'), [(None, 'artifact is missing'), (b'{', 'Expecting property name')])
def test_missing_or_malformed_envelope_is_unusable(copies, capsys, bad_bytes, reason):
    """An absent or unreadable document is not an ordinary candidate difference."""
    left, right = copies
    if bad_bytes is None:
        right.rename(right.with_suffix('.moved'))
    else:
        right.write_bytes(bad_bytes)

    assert _compare(left, right) == 2
    out, err = capsys.readouterr()
    assert not out and err.startswith(f'Unusable right envelope: {reason}')


def test_cross_region_candidates_are_not_comparable(tmp_path, assembly, capsys):
    """Even two valid candidates with the same generation may belong to different regions."""
    left = _candidate(tmp_path / 'fixture-west')
    right = _candidate(tmp_path / 'fixture-east')
    assert envelope.verify_artifacts(left).generation == envelope.verify_artifacts(right).generation

    assert _compare(left, right) == 2
    assert capsys.readouterr() == ('', 'Cannot compare candidates from different regions: fixture-west vs fixture-east\n')
