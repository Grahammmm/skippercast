"""Review and derived-byte gates run before any terrain-only lease or worker."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import rasterio
from rasterio.transform import from_origin

from skippercast.coastal import vertical
from skippercast.coastal.coordinator import store as module
from skippercast.coastal.coordinator.store import Store
from skippercast.coastal.handoff.common import ref, write
from skippercast.coastal.render import terrain_only

NOW = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)


def approve(root, document, **changes):
    review = dict(schema=terrain_only.REVIEW, scope='internal-terrain-only-scientific-review',
        facts_digest=terrain_only.context(document), independent=True,
        reviewer_id='independent-synthetic-reviewer', decision='accept',
        checked_at=(NOW-timedelta(minutes=1)).isoformat(),
        valid_until=(NOW+timedelta(hours=1)).isoformat(), holds_added=[], synthetic=True)
    review.update(changes)
    write(root/'science.json', review)
    document['scientific_review'] = ref(root, root/'science.json', terrain_only.REVIEW)


def gate(root, document, *, now=NOW, params=None, duration=60):
    """Exercise the real admission API with only a read-only segment lookup."""
    write(root/'input.json', document)
    st=Store.__new__(Store); st.root=root; st.clock=lambda:now.timestamp()
    st.db=MagicMock()
    st.db.execute.return_value.fetchone.return_value=[json.dumps(dict(segment_id=document['segment_id'],synthetic=document.get('synthetic',False)))]
    settings=dict(terrain_root=str(root),terrain_context_digest=terrain_only.context(document))
    settings.update(params or {})
    job=dict(stage='render',segment_id=document['segment_id'],input_manifest=ref(root,root/'input.json',terrain_only.INPUT),
             params=settings,budget=dict(wall_s=duration),code_sha='a'*64,deps_sha='b'*64)
    with (patch('rasterio.open',side_effect=AssertionError('admission opened raster')),
         patch('h5py.File',side_effect=AssertionError('admission opened source')),
         patch('socket.create_connection',side_effect=AssertionError('admission used network')),
         patch.object(Store,'_enqueue',side_effect=AssertionError('admission enqueued job')),
         patch.object(terrain_only,'preview',side_effect=AssertionError('admission rendered terrain')),
         patch.object(terrain_only,'build_terrain',side_effect=AssertionError('admission built mesh'))):
        return st._evidence_gate(job)


class TerrainAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        for name,dtype in [('terrain','float32'),('mask','uint8'),('uncertainty','float32')]:
            with rasterio.open(self.root/(name+'.tif'),'w',driver='GTiff',width=2,height=2,count=1,
                    dtype=dtype,crs='EPSG:26911',transform=from_origin(100,100,1,1)) as ds:
                ds.write(np.ones((2,2),dtype=dtype),1)
        raw=dict(sign='positive_up',units='m',datum='MLLW',datum_realization='unknown',
                 scale=1.,offset=0.,scale_offset_applied=False)
        block=dict(schema='vertical-v1',**raw,conflicts=[],evidence=[dict(kind='raster_header',
                   source_sha256='a'*64,header_sha256='b'*64,facts=raw)])
        self.doc=dict(schema=terrain_only.INPUT,creator_id='synthetic-fixture-builder',
            segment_id='synthetic-only',terrain=ref(self.root,self.root/'terrain.tif','coastal-normalized-terrain-v1'),
            mask=ref(self.root,self.root/'mask.tif','coastal-native-support-v2'),
            uncertainty=ref(self.root,self.root/'uncertainty.tif','coastal-derived-uncertainty-m-v1'),
            uncertainty_kind='producer_uncertainty_m',vertical=vertical.normalized(block),crs='EPSG:26911',
            affine=list(from_origin(100,100,1,1)),provenance=dict(source_sha256s=['a'*64],upstream_receipt_sha256='c'*64),
            support_kind='derived_valid_sample_support',limitations=['Synthetic fixture only.'],synthetic=True,
            source_accessed=False,imagery_used=False,internal_diagnostic=True,publication_prohibited=True,
            website='held',habitat='unassessed')
        approve(self.root,self.doc)

    def test_accepted_packet_admitted_without_reader_network_or_job(self):
        self.assertEqual(gate(self.root,self.doc),(True,[]))

    def test_invalid_review_rejected_before_lease(self):
        variants=[dict(valid_until=(NOW-timedelta(seconds=1)).isoformat()),
            dict(checked_at=(NOW+timedelta(seconds=1)).isoformat()),dict(facts_digest='f'*64),
            dict(reviewer_id=self.doc['creator_id']),dict(independent=False),dict(synthetic=False),
            dict(scope='website-display'),dict(holds_added=['science_hold'])]
        for change in variants:
            with self.subTest(change=change):
                approve(self.root,self.doc,**change)
                self.assertFalse(gate(self.root,self.doc)[0])

    def test_missing_or_hash_mutated_review_rejected(self):
        d=deepcopy(self.doc);d.pop('scientific_review')
        self.assertFalse(gate(self.root,d)[0])
        with (self.root/'science.json').open('a') as stream:stream.write(' ')
        self.assertFalse(gate(self.root,self.doc)[0])

    def test_review_must_outlast_job_horizon(self):
        approve(self.root,self.doc,valid_until=(NOW+timedelta(seconds=60)).isoformat())
        self.assertFalse(gate(self.root,self.doc,duration=60)[0])
        self.assertTrue(gate(self.root,self.doc,duration=59)[0])

    def test_context_and_root_mismatch_rejected(self):
        self.assertFalse(gate(self.root,self.doc,params=dict(terrain_context_digest='f'*64))[0])
        (self.root/'sub').mkdir()
        self.assertFalse(gate(self.root,self.doc,params=dict(terrain_root=str(self.root/'sub')))[0])

    def test_derived_asset_tampering_rejected(self):
        for key in ['terrain','mask','uncertainty']:
            path=self.root/self.doc[key]['path'];original=path.read_bytes()
            path.write_bytes(original+b'changed')
            with self.subTest(key=key):self.assertFalse(gate(self.root,self.doc)[0])
            path.write_bytes(original)

    def test_reviewed_unsafe_derived_reference_rejected(self):
        d=deepcopy(self.doc);d['terrain']['path']='../escape.tif';approve(self.root,d)
        self.assertFalse(gate(self.root,d)[0])
        path=self.root/'fake.tif';path.write_text('<VRTDataset/>')
        d=deepcopy(self.doc);d['terrain']=ref(self.root,path,'coastal-normalized-terrain-v1');approve(self.root,d)
        self.assertFalse(gate(self.root,d)[0])

    def test_nonterrain_render_uses_existing_gate(self):
        doc=dict(schema='render-handoff-v2',segment_id='synthetic-only',synthetic=True)
        with patch.object(module,'readiness',return_value=(False,['existing_hold'])) as existing:
            self.assertEqual(gate(self.root,doc),(False,['existing_hold']))
            existing.assert_called_once()


if __name__=='__main__':unittest.main()
