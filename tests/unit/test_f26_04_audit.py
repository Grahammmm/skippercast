"""F26-04: Central 300 ft completion must reconcile with the Central review (offline)."""
import hashlib
import json

import pytest

from research.scripts import audit_central_nbs_300 as central

SECTORS = ('monterey-sur', 'big-sur', 'sur-san-simeon')


def _review(scheme, *, coast='central', sectors=SECTORS, tiles_per=1, requested=None):
    digest = hashlib.sha256(scheme.read_bytes()).hexdigest()
    rows, n = [], 0
    for sid in sectors:
        tiles = []
        for _ in range(tiles_per):
            tiles.append({'tile': f'T{n}', 'source_audit': {'raster_sha256': f'r{n}', 'rat_sha256': f'a{n}'}})
            n += 1
        rows.append({'sector_id': sid, 'reviewed_tiles': tiles})
    total = n if requested is None else requested
    return {'scope': 'coast-nbs-multiple-rocky-camera-tile-source-review', 'coast': coast,
            'scheme_sha256': digest, 'failed_tiles': {}, 'sectors': rows,
            'requested_unique_tiles': total, 'audited_unique_tiles': total}


@pytest.fixture
def scheme(tmp_path):
    path = tmp_path / 'scheme.gpkg'
    path.write_bytes(b'synthetic scheme')
    return path


@pytest.fixture
def fake_audit(monkeypatch):
    def audit(scheme, tile, cache, *, fetch=False, limit_ft=300):
        n = tile[1:]
        if tile in fake_audit.failing:
            raise OSError('synthetic failure')
        return {'tile': tile, 'raster_sha256': f'r{n}', 'rat_sha256': f'a{n}'}
    fake_audit.failing = set()
    monkeypatch.setattr(central, 'audit', audit)
    return fake_audit


def test_matching_review_is_complete(scheme, tmp_path, fake_audit):
    result = central.build(_review(scheme), scheme, tmp_path)
    assert result['status'] == 'complete-source-screen'
    assert result['screened_unique_tiles'] == result['requested_unique_tiles'] == 3


def test_northern_review_is_rejected(scheme, tmp_path, fake_audit):
    with pytest.raises(ValueError, match='central coast'):
        central.build(_review(scheme, coast='north', sectors=('north-a',)), scheme, tmp_path)


def test_empty_inventory_is_rejected(scheme, tmp_path, fake_audit):
    review = _review(scheme, tiles_per=0, requested=1)
    with pytest.raises(ValueError):
        central.build(review, scheme, tmp_path)
    review['sectors'] = []
    with pytest.raises(ValueError):
        central.build(review, scheme, tmp_path)


def test_declared_total_must_match_inventory(scheme, tmp_path, fake_audit):
    with pytest.raises(ValueError, match='requested_unique_tiles'):
        central.build(_review(scheme, requested=5), scheme, tmp_path)


def test_partial_failure_is_incomplete(scheme, tmp_path, fake_audit):
    fake_audit.failing = {'T1'}
    result = central.build(_review(scheme), scheme, tmp_path)
    assert result['status'] == 'incomplete-source-screen'
    assert result['screened_unique_tiles'] == 2


def test_exit_codes_distinguish_complete_and_incomplete(scheme, tmp_path, fake_audit):
    review = tmp_path / 'review.json'
    review.write_text(json.dumps(_review(scheme)))
    args = ['--review', str(review), '--scheme', str(scheme), '--cache', str(tmp_path),
            '--output', str(tmp_path / 'out.json')]
    assert central.main(args) == 0
    fake_audit.failing = {'T0'}
    assert central.main(args) == central.EXIT_INCOMPLETE
