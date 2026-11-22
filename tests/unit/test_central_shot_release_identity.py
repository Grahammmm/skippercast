"""Shots planning must bind package identity as well as its attested bytes."""
from argparse import Namespace

import pytest

from skippercast.relief import package, receipts, shots


REGION = 'synthetic-coast'
GENERATION = 'a' * 64


@pytest.fixture
def shot_request(tmp_path, monkeypatch):
    def no_capture(*args, **kwargs):
        pytest.fail('planning must not launch capture')

    monkeypatch.setattr(shots, 'capture', no_capture)

    def make_request(manifest_region, manifest_generation):
        region = receipts.Region(tmp_path, REGION)
        relative = f'release/{GENERATION}/release.json'
        release = region.dir / relative
        release.parent.mkdir(parents=True)
        for layer, data in ((package.DIGEST_ROOT, b'{}'), (package.ARCHIVE, b'synthetic relief')):
            path = region.dir / layer
            path.parent.mkdir(parents=True)
            path.write_bytes(data)
        layers = [package.layer_record(region.dir, layer) for layer in (package.DIGEST_ROOT, package.ARCHIVE)]
        raw = receipts.canonical(dict(
            schema=package.RELEASE_SCHEMA, region=manifest_region, generation=manifest_generation,
            private=False, disclaimer=package.DISCLAIMER, code_sha='b' * 40,
            bounds=[-124, 35, -122, 37], minzoom=8, maxzoom=8,
            sources=[dict(id='synthetic', label='measured', attribution='Synthetic survey', vertical_datum='NAVD88',
                          survey_dates=['2020'], rights_class='public',
                          rights={'public_display': 'allowed', 'license': 'synthetic'})],
            detail_summary={'mask': 'transparent-nodata', 'depth_bands': [
                {'source_id': 'synthetic', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 5},
            ]},
            native_support_by_zoom={'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
            layers=layers, digest_root_sha256=layers[0]['sha256'],
        ))
        release.write_bytes(raw)
        receipts.write_json_atomic(region.receipt_path('package'), dict(
            schema=receipts.SCHEMA, region=REGION, stage='package', scope=None, status='ok',
            generation=GENERATION, attempt=1, upstream=[],
            outputs=[{'path': relative, 'bytes': len(raw), 'sha256': receipts.sha256_bytes(raw)}],
        ))
        verdict = receipts.check(region, 'package')
        assert verdict.done and verdict.receipt is not None, verdict.reason
        basemap = tmp_path / 'basemap.pmtiles'
        basemap.write_bytes(b'synthetic basemap')
        ctx = receipts.StageContext(region, None, Namespace(basemap=basemap, lon=-123.0, lat=36.0),
                                    {'package': verdict.receipt})
        return ctx, release, basemap

    return make_request


def test_matching_release_keeps_normal_capture_plan(shot_request):
    # A fail-closed check comparing against the wrong ID could reject a good package or drop capture options.
    ctx, release, basemap = shot_request(REGION, GENERATION)

    assert shots.plan(ctx) == receipts.Plan(
        [receipts.Input(release, 'release'), receipts.Input(basemap, 'basemap')],
        {'camera': [-123.0, 36.0]},
    )


@pytest.mark.parametrize(('region', 'generation', 'field'), [
    # A byte-current receipt can name the selected region while packaging another region's manifest.
    ('other-synthetic-coast', GENERATION, 'region'),
    # An older manifest for the right region can be attested at the current generation's path.
    (REGION, 'c' * 64, 'generation'),
], ids=['wrong-region', 'wrong-generation'])
def test_attested_release_with_wrong_identity_is_refused_at_plan(shot_request, region, generation, field):
    ctx, _, _ = shot_request(region, generation)

    with pytest.raises(receipts.ReceiptError, match=rf'release\.json {field} does not match'):
        shots.plan(ctx)
