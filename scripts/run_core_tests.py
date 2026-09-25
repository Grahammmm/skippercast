"""Run dependency-light app tests on every supported core Python version.

The separate survey-science CI job installs pinned GIS packages and runs the
entire suite, including the modules excluded here.
"""
from pathlib import Path
import sys
import unittest


GIS_TEST_MODULES = {
    'test_bluetopo_source',
    'test_bottom_targets',
    'test_camera_native_terrain',
    'test_cdfw_substrate_pipeline',
    'test_central_sediment_context',
    'test_csumb_bss_native',
    'test_csumb_scc_native',
    'test_enc_hazard_refresh',
    'test_native_hard_context',
    'test_native_sector_leads',
    'test_nbs_bag_reconciliation',
    'test_nbs_modeling_tile',
    'test_nbs_scheme_check',
    'test_nbs_statewide_camera_tiles',
    'test_noaa_induration_camera',
    'test_noaa_chlorophyll',
    'test_noaa_hfr',
    'test_noaa_sst',
    'test_original_camera_chart_lead',
    'test_original_class_nbs_tiles',
    'test_region_bag_coverage',
    'test_regular_bag_camera',
    'test_regular_native_depth',
    'test_regular_bag_hard',
    'test_sansimeon_bedrock_overlap',
    'test_santa_cruz_region',
    'test_search_plan_geometry',
    'test_shelter_cove_region',
    'test_san_diego_substrate_lead',
    'test_statewide_camera_dedup',
    'test_statewide_regular_report_review',
    'test_usgs_context_pipeline',
    'test_usgs_caldig_v2',
    'test_usgs_csmp_sources',
    'test_usgs_depth_datum_ledger',
    'test_usgs_doi_pipeline',
    'test_usgs_video_audit',
    'test_vr_camera_overlap',
    'test_vr_hard_context',
    'test_vr_native_depth',
    'test_vr_region_protection',
    'test_vdatum_samples',
}


def main():
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(root / 'src'))
    names = [p.stem for p in sorted((root / 'tests').glob('test_*.py'))]
    missing = GIS_TEST_MODULES - set(names)
    if missing:
        raise SystemExit(f'GIS test classification is stale: {sorted(missing)}')
    suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName('tests.' + name)
                               for name in names if name not in GIS_TEST_MODULES)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
