"""Claims recorded in research receipts (moved from dist/data/ by P1-02b).

These assertions used to run in scripts/check_web.py while the receipts were
published with the app. The receipts are no longer shipped, so the checks run
here, reading them through research.lib.receipts; nothing was relaxed.
"""
import json
from pathlib import Path
import unittest

from research.lib.receipts import RECEIPTS, locate

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'dist'


class ReceiptClaimsTest(unittest.TestCase):
    def test_expanded_native_depth_inventory(self):
        name = 'noaa-vr-native-depth-expanded-review.json'
        data = json.loads((WEB / 'data' / name).read_text())
        manifest = json.loads((ROOT / 'catalog/noaa-vr-native-review-sources.json').read_text())
        assert manifest['scope'] == 'california-original-vr-depth-review-inputs'
        reviews = [json.loads(locate(path).read_text()) for path in manifest['review_files']]
        sectors = json.loads((WEB / 'data/coastal-sectors.json').read_text())['sectors']
        assert data['scope'] == 'california-expanded-original-vr-depth-inventory'
        assert data['source_review_count'] == len(reviews)
        assert data['survey_file_count'] == len(data['files']) == sum(r['survey_file_count'] for r in reviews)
        assert data['fishing_target'] is False and data['exportable'] is False
        assert {row['sector_id'] for row in data['sectors']} == {row['id'] for row in sectors}
        assert len({row['bag_url'] for row in data['files']}) == len(data['files'])
        assert {row['bag_url'] for row in data['files']} == {
            file['bag_url'] for review in reviews for file in review['files']}
        for row in data['sectors']:
            contributors = [source for source in data['files'] if source['sectors'].get(
                row['sector_id'], {}).get('depth_uncertainty_eligible_cells', 0) > 0]
            assert row['survey_ids_with_eligible_cells'] == sorted({s['survey_id'] for s in contributors})
            assert row['source_files_with_eligible_cells'] == len(contributors)
            for key in ('fine_native_grids', 'measured_native_cells',
                        'depth_uncertainty_eligible_cells'):
                assert row[key] == sum(source['sectors'].get(row['sector_id'], {}).get(key, 0)
                                       for source in data['files'])

    def test_usgs_morro_report_datum(self):
        manifest = json.loads((ROOT / 'catalog/usgs-morro-report-datum-source.json').read_text())
        review = json.loads((RECEIPTS / 'usgs-morro-report-datum-review.json').read_text())
        assert review['scope'] == manifest['scope']
        assert review['report_sha256'] == manifest['report_sha256']
        assert review['report_url'] == manifest['report_url']
        assert review['report_depth_reference'] == 'MLLW'
        assert {row['release_id'] for row in review['sources']} == set(manifest['release_ids'])
        assert all(row['depth_qualified_for_fishing'] is False and
                   row['has_per_cell_product_uncertainty'] is False and
                   row['vertical_accuracy_lower_bound_m'] == .2 and
                   row['vertical_accuracy_upper_bound_m'] is None for row in review['sources'])
        assert review['fishing_target'] is False and review['exportable'] is False

    def test_usgs_bathy_accuracy_statewide(self):
        review = json.loads((RECEIPTS / 'usgs-bathymetry-accuracy-review.json').read_text())
        ledger = json.loads((WEB / 'data/usgs-depth-datum-ledger.json').read_text())
        assert review['scope'] == 'california-usgs-original-bathymetry-accuracy-review'
        assert review['status'] == 'ok' and not review['issues']
        assert review['source_grid_count'] == review['fully_verified_source_count'] == len(review['sources']) == ledger['source_grid_count']
        originals = {row['metadata_url']: row for row in ledger['sources']}
        assert {row['metadata_url'] for row in review['sources']} == set(originals)
        for row in review['sources']:
            assert row['status'] == 'ok' and row['metadata_sha256'] == originals[row['metadata_url']]['metadata_sha256']
            assert row['depth_qualified_for_fishing'] is False
            assert row['per_cell_uncertainty_available'] is False
        assert review['fishing_target'] is False and review['exportable'] is False

    def test_h11876_sidescan_context(self):
        review = json.loads((RECEIPTS / 'h11876-original-sidescan-review.json').read_text())
        assert review['scope'] == 'h11876-original-sidescan-camera-context'
        assert review['source_sha256'] == 'fea036f596158b4f549ad86b83a8f66068637c24f848b867f3e772b8cf5f09e0'
        assert review['actual_raster_pixel_size_m'] == [1.5, 1.5]
        assert review['reviewed_rocky_windows_with_sidescan_coverage'] == review['reviewed_rocky_window_count'] == 11
        assert sum(row['patch_count'] for row in review['transects']) == 44
        assert review['fishing_target'] is False and review['exportable'] is False
        assert all('latitude' not in row and 'longitude' not in row and 'coordinates' not in row
                   for row in review['transects'])

    def test_h11967_induration_matches_chart_screen(self):
        induration = json.loads((RECEIPTS / 'h11967-noaa-induration-camera-review.json').read_text())
        chart = json.loads((RECEIPTS / 'h11967-enc-camera-research-screen.json').read_text())
        assert induration['scope'] == 'original-bag-camera-versus-noaa-2017-induration-research'
        assert induration['survey_id'] == 'H11967' and induration['camera_windows_checked'] == 18
        assert induration['source_context_sha256'] == chart['candidate_research_context_sha256']
        assert sum(induration['class_counts'].values()) == len(induration['rows']) == 18
        assert sum(induration['quality_counts'].values()) == 18
        assert induration['fishing_target'] is False and induration['exportable'] is False
        assert all('coordinates' not in row and 'longitude' not in row and 'latitude' not in row
                   for row in induration['rows'])

    def test_h11983_source_and_hazard_gate_agree_and_aptos_and_csumb_bridge(self):
        original_lead = json.loads((RECEIPTS / 'noaa-h11983-native-source-review.json').read_text())
        hazard_gate = json.loads((RECEIPTS / 'noaa-h11983-camera-hazard-research-review.json').read_text())
        assert original_lead['survey_id'] == hazard_gate['survey_id'] == 'H11983'
        assert original_lead['nbs_and_original_bag_qualified_rocky_windows'] == hazard_gate['original_qualified_historical_camera_windows'] == 3
        assert original_lead['report_danger_count'] == hazard_gate['historical_report_dangers'] == 11
        assert original_lead['enc_danger_layers_queried'] == hazard_gate['enc_query_layers'] == 18
        assert all(packet['fishing_target'] is False and packet['exportable'] is False
                   for packet in (original_lead, hazard_gate))
        assert 'coordinates' not in json.dumps(original_lead) and 'coordinates' not in json.dumps(hazard_gate)
        aptos = json.loads((RECEIPTS / 'usgs-offshore-aptos-native-audit.json').read_text())
        assert aptos['product_count'] == aptos['inspected_count'] == 4
        assert aptos['fishing_target'] is False and aptos['exportable'] is False
        assert all(row['status'] == 'ok' for row in aptos['products'])
        aptos_depth = json.loads((RECEIPTS / 'usgs-offshore-aptos-noaa-mllw-overlap-review.json').read_text())
        assert aptos_depth['tile_count'] == len(aptos_depth['tiles']) == 9
        assert aptos_depth['fishing_target'] is False and aptos_depth['exportable'] is False
        assert all(tile['qualified_measured_mllw_pixels'] == 0 and
                   tile['strict_measured_rock_overlap_pixels'] == 0 for tile in aptos_depth['tiles'])
        datum_bridge = json.loads((RECEIPTS / 'csumb-vdatum-bridge-review.json').read_text())
        assert datum_bridge['scope'] == 'csumb-original-navd88-geoid09-vdatum-bridge-review'
        assert len(datum_bridge['samples']) == 9
        assert {sample['source_id'] for sample in datum_bridge['samples']} == {
            'csumb-scc-block04', 'csumb-scc-block05', 'csumb-scc-block06',
            'csumb-bss-block01', 'csumb-bss-block02', 'csumb-bss-block03', 'csumb-bss-block08',
            'csumb-bss-block12', 'csumb-bss-block13'}
        assert datum_bridge['source_horizontal_realization_verified'] is False
        assert datum_bridge['mllw_raster_converted'] is False
        assert datum_bridge['depth_qualified'] is False
        assert datum_bridge['fishing_target'] is False and datum_bridge['exportable'] is False
        assert datum_bridge['alternative_horizontal_frame_probe']['status'] == 'api_rejected'

    def test_san_miguel_original_habitat_reviews(self):
        san_miguel_regular = json.loads((RECEIPTS / 'san-miguel-original-habitat-depth-review.json').read_text())
        san_miguel_vr = json.loads((RECEIPTS / 'san-miguel-original-habitat-vr-review.json').read_text())
        assert san_miguel_regular['noaa_measured_cells_in_window'] == 257
        assert san_miguel_regular['substrate_classes']['h']['depth_uncertainty_eligible_cells'] == 0
        assert san_miguel_vr['counts']['hard_eligible_cells'] == 648740
        assert san_miguel_vr['counts']['hard_cells_after_enc_buffer'] == 601603
        assert san_miguel_vr['enc_danger_features'] == 201
        assert all(packet['fishing_target'] is False and packet['exportable'] is False
                   for packet in (san_miguel_regular, san_miguel_vr))


if __name__ == "__main__":
    unittest.main()
