"""Offline controls for F11-06: a planning square is not the measured reference footprint.

Synthetic EPSG:3310 geometry only. The affected control drives the native
paired-reference path, classified_habitat.source_context(), over a synthetic
baseline folder whose cells.json comes from coverage.classify_cells(): a Tier 1
cell qualifying at exactly 25% reference coverage. The detector then reads the
production support geometry and reference identity it returns. It separates two
evidence roles: planning-cell context (cell membership) and measured overlap
with the verified valid reference geometry.

The regression exercises the native planning-cell contract: the independently
supported patch in the disjoint quarter may be retained, but must never claim
measured overlap with the reference survey.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from shapely.geometry import box

from skippercast.platform.contracts import atomic_json
from skippercast.seafloor import classified_habitat as ch
from skippercast.seafloor import coverage
from skippercast.seafloor.io import sha256

CELL = {'id': '3310:0:0'}  # the 250 m square (0,0)-(250,250)
# Reference survey covers only the left quarter strip (25% of the square).
REFERENCE = box(0, 0, 62.5, 250)
# Candidate patches (>= 1000 m2). One sits on the reference; one lies in the
# disjoint right-hand quarter of the same cell, with no reference overlap.
ON_REFERENCE = box(10, 10, 50, 50)
OFF_REFERENCE = box(150, 50, 200, 100)
EXISTING = box(-20, -20, -10, -10)
REFERENCE_ID = 'ref'


def measured_overlap_m2(patch, reference):
    return patch.intersection(reference).area


def unsupported_patches(patches, reference):
    """Patches asserted as reference-supported but with no measured overlap."""
    return [p for p in patches if measured_overlap_m2(p, reference) <= 1e-6]


def support_gaps(support, identity, reference):
    """Gaps between the claimed reference support and verified measured geometry."""
    claim = identity['reference_support']
    gaps = []
    if support.difference(reference).area > 1e-6 and 'planning' not in claim['meaning'].lower():
        gaps.append('whole-square-called-measured-footprint')
    if REFERENCE_ID not in claim['source_ids']:
        gaps.append('reference-identity-missing')
    return gaps


def paired_context(cells):
    """Run production source_context() in paired-reference mode on synthetic inputs."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        folder = root/'var/seafloor/reaches/fixture'
        folder.mkdir(parents=True)
        depth = {'id': 'native', 'sha256': 'a'*64, 'status': 'usable', 'kind': 'bathymetry',
                 'resolution_m': 2., 'vertical_datum': 'unknown', 'license': 'public-domain-us-gov',
                 'url': 'https://example.test/original-depth', 'publisher': 'Original publisher',
                 'adapter_review': {'requested_bounds_wgs84': [-122, 35, -121, 36]}}
        ref = dict(depth, id=REFERENCE_ID, sha256='f'*64)
        bind = {'row': {'id': 'classes', 'sha256': 'b'*64, 'status': 'candidate', 'kind': 'substrate',
                        'format': 'usgs-geotiff', 'license': 'public-domain-us-gov',
                        'url': 'https://example.test/original-class', 'publisher': 'Original publisher'},
                'binding': {'source_id': 'classes', 'source_sha256': 'b'*64, 'depth_source_ids': ['native'],
                            'review_status': 'reviewed', 'metadata_url': 'https://example.test/original-metadata',
                            'metadata_sha256': 'c'*64, 'same_survey_as_depth': True,
                            'classes': {'1': {'normalized_code': 1}, '2': {'normalized_code': 2},
                                        '3': {'normalized_code': 3}, '13': {'normalized_code': 3}}}}
        policy = {'id': 'fixture-rugose-v1', 'reviewed_on': '2026-09-01',
                  'depth_source_id': 'native', 'depth_source_sha256': 'a'*64,
                  'classification_source_id': 'classes', 'classification_source_sha256': 'b'*64,
                  'metadata_url': 'https://example.test/original-metadata', 'metadata_sha256': 'c'*64,
                  'rugose_raw_codes': [3, 13], 'credit': 'Original publisher and mapping lab',
                  'release_license': 'public-domain-us-gov', 'notice': 'Not for navigation.',
                  'review_basis': 'Synthetic explicitly reviewed class3; mixed excluded.',
                  'support_mode': ch.PAIRED_REFERENCE_SUPPORT, 'reach_ids': ['fixture']}
        atomic_json(root/'catalog/habitat-rules.json', {'substrate_bindings': [bind['binding']]})
        atomic_json(root/'catalog/reaches.json', {'reaches': [{'id': 'fixture'}]})
        atomic_json(folder/'cells.json', {'cells': cells})
        atomic_json(folder/'candidates.geojson', {'features': []})
        names = ('cells.json', 'candidates.geojson')
        atomic_json(folder/'physical.json', {'input_hash': 'baseline',
                                             'outputs': {n: sha256(folder/n) for n in names}})
        atomic_json(folder/'run.json', {'physical_input_hash': 'baseline',
            'inputs': {'reach_id': 'fixture', 'sources': [depth, ref],
                       'substrate_bindings': {'native': bind}},
            'outputs': {n: sha256(folder/n) for n in names + ('physical.json',)}})
        receipts = {}
        for src in (depth, ref):
            cache = root/'var/seafloor/cache'/src['sha256']
            cache.mkdir(parents=True)
            cog = cache/(src['id'].ljust(64, 'd') + '.tif')
            cog.write_bytes(('synthetic normalized bytes ' + src['id']).encode())
            receipts[src['id']] = {'cog_sha256': sha256(cog)}
            atomic_json(cog.with_suffix('.json'), receipts[src['id']])
        manifest = {'surveys': [depth, bind['row'], ref]}
        with patch.object(ch, 'load_manifest', return_value=manifest), patch.object(ch, 'verify_sources'), \
             patch.object(ch, 'ingest', side_effect=lambda src, *a, **kw: (receipts[src['id']], None, None)), \
             patch.object(ch, 'verify_review'):
            context = ch.source_context(root, 'fixture', policy)
    return context[0], context[4]  # identity, support


class ReferenceFootprintControls(unittest.TestCase):
    def setUp(self):
        self.cells = coverage.classify_cells(
            [CELL], [{'row': {'id': REFERENCE_ID, 'resolution_m': 2, 'year': 2014},
                      'geometry': REFERENCE}])

    def test_fixture_is_tier1_at_exactly_quarter_coverage(self):
        self.assertEqual(self.cells[0]['tier'], 1)
        self.assertAlmostEqual(self.cells[0]['valid_fraction'], .25)
        self.assertEqual(self.cells[0]['source_id'], REFERENCE_ID)

    def test_valid_control_measured_intersection_keeps_identity_and_measured_patches(self):
        # Contract shape: production identity (reference ids) intersected with
        # verified reference geometry. Passes the detector with no gap.
        identity, support = paired_context(self.cells)
        measured = support.intersection(REFERENCE)
        self.assertEqual(support_gaps(measured, identity, REFERENCE), [])
        patches, _ = ch.additional_patches([ON_REFERENCE, OFF_REFERENCE], measured, EXISTING)
        self.assertEqual(len(patches), 1)
        self.assertEqual(unsupported_patches(patches, REFERENCE), [])
        self.assertAlmostEqual(patches[0].area, ON_REFERENCE.area)

    def test_valid_control_planning_label_is_not_measured_overlap(self):
        # If only cell membership is intended, an explicit planning-cell label
        # is the other acceptable outcome; it never claims measured overlap.
        identity, support = paired_context(self.cells)
        labeled = {'reference_support': dict(identity['reference_support'],
                                             meaning='Planning-cell context only; not measured overlap.')}
        self.assertEqual(support_gaps(support, labeled, REFERENCE), [])

    def test_native_paired_support_is_planning_context_not_measured_overlap(self):
        # A quarter-coverage winner qualifies the cell for planning, not the
        # disjoint patch for measured overlap. Do not discard the pair's own
        # qualifying patch just to avoid overstating the reference evidence.
        identity, support = paired_context(self.cells)
        claim = identity['reference_support']
        self.assertEqual(identity['support_mode'], ch.PAIRED_REFERENCE_SUPPORT)
        self.assertEqual(claim['source_ids'], [REFERENCE_ID])
        self.assertTrue(support.equals(coverage.cell_geometry(CELL)))
        self.assertEqual(support_gaps(support, identity, REFERENCE), [])
        self.assertIn('planning-cell context', claim['meaning'].lower())
        self.assertIn('not evidence of measured overlap', claim['meaning'].lower())
        patches, _ = ch.additional_patches([ON_REFERENCE, OFF_REFERENCE], support, EXISTING)
        self.assertEqual({p.bounds for p in patches}, {ON_REFERENCE.bounds, OFF_REFERENCE.bounds})
        flagged = unsupported_patches(patches, REFERENCE)
        self.assertEqual(len(flagged), 1)
        self.assertEqual(flagged[0].bounds, OFF_REFERENCE.bounds)
        self.assertEqual(measured_overlap_m2(flagged[0], REFERENCE), 0)


if __name__ == '__main__':
    unittest.main()
