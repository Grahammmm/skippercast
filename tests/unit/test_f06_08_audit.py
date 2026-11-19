"""F06-08: completed mapping verification uses one freshly checked observation."""
from unittest.mock import patch

import pytest


pytestmark = pytest.mark.gis
NOW = '2000-01-02T00:00:00Z'
EXPIRES = '2000-01-03T00:00:00Z'


@pytest.fixture
def completed(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from skippercast.coastal import mapping, vertical
    from skippercast.coastal.handoff import mapping_input
    from skippercast.coastal.handoff.common import ref, write

    source = tmp_path / 'native.tif'
    raw = -np.arange(1, 17, dtype='float32').reshape(4, 4)
    raw[1, 2] = np.nan
    with rasterio.open(source, 'w', driver='GTiff', width=4, height=4, count=1,
                       dtype='float32', crs='EPSG:3310', transform=from_origin(10, 20, 2, 2),
                       nodata=np.nan) as ds:
        ds.write(raw, 1)
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_sign='positive_up', vertical_datum='MLLW', scale_offset_applied='false')
    source_ref = ref(tmp_path, source, 'native-raster-v1')
    with rasterio.open(source) as ds:
        observed = vertical.from_raster(ds, source_sha256=source_ref['sha256'])
    block = dict(schema='vertical-v1', **observed['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observed)])
    segment_id = 'seg:3310:0:0:5000'
    segment = tmp_path / 'segment.json'
    write(segment, dict(schema='coastal-segment-v1', segment_id=segment_id,
                        crs='EPSG:3310', bbox=[0, 0, 5000, 5000], region='synthetic'))
    evidence = tmp_path / 'rights.json'
    write(evidence, {'synthetic': True})
    manifest = mapping_input.produce(tmp_path, source_ref, segment_id=segment_id,
        segment=ref(tmp_path, segment, 'coastal-segment-v1'), window=[0, 0, 4, 4],
        vertical=block, rights=dict(private_use=True, evidence=[ref(tmp_path, evidence, 'fixture-rights')]),
        output_dir='input', synthetic=True)
    review = tmp_path / 'review.json'
    schema = 'coastal-private-input-review-v2'
    write(review, dict(schema=schema, independent=True, reviewer_id='synthetic-test-reviewer',
                       facts_digest=manifest['facts_digest'], checked_at=NOW, valid_until=EXPIRES,
                       decision='accept', holds_added=[]))
    manifest['review'] = ref(tmp_path, review, schema)
    run = mapping.run(tmp_path, manifest, output_dir='mapped', now=NOW)
    assert run['state'] == 'done'
    return tmp_path, run


def test_each_verify_observes_native_once(completed):
    from skippercast.coastal import mapping
    from skippercast.coastal.handoff import mapping_input

    root, run = completed
    with patch.object(mapping_input, 'observe', wraps=mapping_input.observe) as observe:
        for count in (1, 2):
            checked = mapping.verify(root, run, now=NOW)
            assert checked['ready'] and checked['holds'] == []
            assert checked['facts'] == run['mapping_input']['native_facts']
            # The old verifier re-observed after authentication; a cross-call cache
            # would instead fail to take a fresh observation on the second call.
            assert observe.call_count == count


@pytest.mark.parametrize(('artifact', 'error'), [
    ('native', 'artifact bytes/hash changed'),
    ('input_support', 'native support artifact differs from source cells'),
    ('output_support', 'mapping support differs from native cells'),
    ('summary', 'mapping support summary changed'),
])
def test_verify_still_rejects_changed_artifacts(completed, artifact, error):
    import rasterio

    from skippercast.coastal import mapping
    from skippercast.coastal.handoff.common import load, ref, write

    root, run = completed
    assert mapping.verify(root, run, now=NOW)['ready']
    if artifact == 'native':
        with rasterio.open(root / run['source']['path'], 'r+') as ds:
            data = ds.read(1)
            data[0, 0] -= 1
            ds.write(data, 1)
    else:
        # Rebind derived bytes so semantic checks, not just hash checks, must fail.
        owner, key = {
            'input_support': (run['mapping_input'], 'valid_support'),
            'output_support': (run['outputs'], 'mask'),
            'summary': (run['outputs'], 'cells'),
        }[artifact]
        old = owner[key]
        path = root / old['path']
        if artifact == 'summary':
            cells = load(root, old, contract=old['contract'])
            cells['native_valid_count'] += 1
            write(path, cells)
        else:
            with rasterio.open(path, 'r+') as ds:
                data = ds.read(1)
                data[1, 2] = 1
                ds.write(data, 1)
        owner[key] = ref(root, path, old['contract'])
    with pytest.raises(ValueError, match=error):
        mapping.verify(root, run, now=NOW)


def test_verify_still_holds_a_previously_valid_run_at_review_expiry(completed):
    from skippercast.coastal import mapping

    root, run = completed
    assert mapping.verify(root, run, now=NOW)['ready']
    checked = mapping.verify(root, run, now=EXPIRES)
    assert not checked['ready']
    assert checked['holds'] == ['review_expired_or_future']
