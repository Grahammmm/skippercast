"""Habitat extraction must preserve gaps, provenance, and the publication hold."""
from copy import deepcopy
import json
import unittest

import numpy as np
from rasterio.transform import from_origin
from shapely.geometry import box, shape, mapping
from shapely.ops import transform
from pyproj import Transformer

from skippercast.seafloor.habitat import (
    thresholds, rough_mask, species_fit, extract_grid, compare_atlas, patch_metrics, validate_rules)
from skippercast.seafloor.substrate import classify, resolve_bindings
from skippercast.seafloor.terrain import derivatives
from tests._support import ROOT


RULES = json.loads((ROOT/'catalog/habitat-rules.json').read_text())


def fixture():
    yy, xx = np.indices((400, 400))
    depth = (50-8*np.exp(-((xx-200)**2+(yy-200)**2)/600)).astype('float32')
    valid = np.ones(depth.shape, bool)
    return {'depth': depth, 'valid': valid, 'inside': valid.copy(),
            'terrain': derivatives(depth, valid, 2), 'classes': np.full(depth.shape, 3, 'uint8'),
            'affine': from_origin(0, 800, 2, 2), 'support': box(0, 0, 800, 800),
            'source': {'row': {'id': 'original', 'resolution_m': 2, 'year': 2008, 'vertical_datum': 'unknown'}},
            'binding': None}


class HabitatTests(unittest.TestCase):
    def test_reviewed_rules_require_cited_bands_and_planning_ceiling(self):
        self.assertEqual(validate_rules(RULES),RULES)
        rules=deepcopy(RULES); rules['depth_m'][1]=100
        with self.assertRaisesRegex(ValueError,'rule bounds'):
            validate_rules(rules)
        rules=deepcopy(RULES); rules['species']['lingcod']['evidence']=''
        with self.assertRaisesRegex(ValueError,'cited evidence'):
            validate_rules(rules)

    def test_flat_sources_at_different_depths_do_not_create_a_seam_reef(self):
        grids=[]
        for depth in (30, 80):
            grid=fixture(); grid['depth'][:]=depth
            grid['terrain']=derivatives(grid['depth'],grid['valid'],2)
            grids.append(grid)
        limits=thresholds(grids,RULES)
        for grid in grids:
            self.assertEqual(extract_grid(grid,limits,RULES,{'id':'fixture','region':'fixture'}),[])

    def test_soft_nodata_and_300ft_pixels_never_become_rough_after_closing(self):
        grid=fixture()
        grid['terrain']['vrm'][:]=.2
        grid['classes'][:,180:183]=1
        grid['valid'][190:193,:]=False
        grid['depth'][200:203,:]=92
        rough=rough_mask(grid['depth'],grid['valid'],grid['inside'],grid['terrain'],
                         grid['classes'],{'vrm':.1,'bpi_fine_m':1},RULES)
        self.assertFalse(rough[:,180:183].any())
        self.assertFalse(rough[190:193,:].any())
        self.assertFalse(rough[200:203,:].any())
        self.assertTrue(rough[150,150])

    def test_unknown_substrate_is_distinct_from_reviewed_soft(self):
        binding=RULES['substrate_bindings'][0]
        values=np.array([[1,2,3,255]])
        result=classify(values,np.array([[True,True,True,False]]),binding)
        np.testing.assert_array_equal(result,[[1,2,3,0]])
        with self.assertRaisesRegex(ValueError,'Unreviewed substrate'):
            classify(np.array([[4]]),np.array([[True]]),binding)

    def test_substrate_withdrawal_and_source_hash_change(self):
        manifest=json.loads((ROOT/'catalog/surveys.json').read_text())
        result=resolve_bindings(RULES,manifest)
        self.assertEqual(len(result),2)
        row=next(r for r in manifest['surveys'] if r['id']==RULES['substrate_bindings'][0]['source_id'])
        row['sha256']='a'*64
        with self.assertRaisesRegex(ValueError,'matching original-source'):
            resolve_bindings(RULES,manifest)
        row['status']='withdrawn'
        self.assertEqual(len(resolve_bindings(RULES,manifest)),1)

    def test_depth_fit_does_not_award_outside_band_grade_c(self):
        species={'planning_depth_m':[10,40]}
        self.assertEqual(species_fit(15,30,'A',species),3)
        self.assertEqual(species_fit(15,30,'C',species),2)
        self.assertEqual(species_fit(35,60,'B',species),2)
        self.assertEqual(species_fit(45,60,'C',species),1)

    def test_real_patch_is_graded_but_not_exportable_or_tier_two(self):
        grid=fixture(); limits=thresholds([grid],RULES)
        features=extract_grid(grid,limits,RULES,{'id':'fixture','region':'fixture'})
        self.assertTrue(features)
        for feature in features:
            props=feature['properties']
            self.assertFalse(props['exportable'])
            self.assertEqual(props['tier'],1)
            self.assertEqual(props['status'],'held')
            self.assertIn('legal-screen-pending',props['hold_reasons'])
            self.assertEqual(props['source_ids'],['original'])
            self.assertLessEqual(props['depth_max_ft'],300)
            self.assertTrue(shape(feature['geometry']).is_valid)
            self.assertIn(props['terrain']['grade'],'ABC')
        again=extract_grid(grid,limits,RULES,{'id':'fixture','region':'fixture'})
        self.assertEqual(features,again)

    def test_metric_support_gap_never_becomes_a_low_grade(self):
        grid=fixture(); grid['valid'][:,:200]=False
        point=box(390,390,410,410).centroid
        metrics,support=patch_metrics(grid,point,np.ones(grid['depth'].shape,bool),RULES)
        self.assertIsNone(metrics)
        self.assertLess(support,.8)

    def test_atlas_comparison_counts_outlines_and_missing_coverage(self):
        project=Transformer.from_crs(3310,4326,always_xy=True).transform
        original=transform(project,box(0,0,100,100))
        candidate=transform(project,box(0,0,60,100))
        atlas={'targets':[{},{}],'areas':[{'id':'one','geometry':mapping(original)},
            {'id':'missing','geometry':mapping(transform(project,box(200,0,300,100)))}]}
        result=compare_atlas(atlas,{'features':[{'geometry':mapping(candidate)}]},box(-1,-1,400,200))
        self.assertEqual(result['reproduced_count'],1)
        self.assertEqual(result['applicable_outline_count'],2)
        self.assertAlmostEqual(result['areas'][0]['overlap_fraction'],.6,places=5)
        self.assertFalse(result['areas'][1]['reproduced'])


if __name__=='__main__':
    unittest.main()
