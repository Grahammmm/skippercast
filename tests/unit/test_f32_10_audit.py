"""Only active supergrid cells can supply NOAA VR depth-screen evidence."""
import hashlib

import pytest


@pytest.mark.gis
@pytest.mark.parametrize(
    ('second_depth', 'nearshore_count', 'lead'),
    [(-90, 0, False), (-20, 1, True)],
    ids=['unreferenced-shallow-trailer', 'referenced-shallow-cell'],
)
def test_vr_depth_screen_counts_only_referenced_cells(tmp_path, second_depth, nearshore_count, lead):
    import h5py
    import numpy as np

    from research.scripts.screen_noaa_vr_source_depth import screen, source_path

    record: dict[str, str | int] = dict(
        survey_id='SYNTHETIC', url='https://data.ngdc.noaa.gov/SYNTHETIC_MB_VR_MLLW.bag',
        survey_start='2000-01-01', survey_end='2000-01-02', source_report_url='https://example.invalid/synthetic',
    )
    xml = b'''<metadata>
      <CharacterString>SYNTHETIC</CharacterString>
      <CharacterString>PROJCS["Synthetic"]</CharacterString>
      <CharacterString>VERT_CS["Synthetic",VERT_DATUM["MLLW",2005]]</CharacterString>
      <BAG_VertUncertCode>productUncert</BAG_VertUncertCode>
      <beginPosition>2000-01-01</beginPosition><endPosition>2000-01-02</endPosition>
    </metadata>'''
    path = source_path(record, tmp_path)
    grid_dtype = [('index', '<u4'), ('dimensions_x', '<u4'), ('dimensions_y', '<u4'),
                  ('resolution_x', '<f4'), ('resolution_y', '<f4'),
                  ('sw_corner_x', '<f4'), ('sw_corner_y', '<f4')]
    cell_dtype = [('depth', '<f4'), ('depth_uncrt', '<f4')]
    with h5py.File(path, 'w') as bag:
        root = bag.create_group('BAG_root')
        root['metadata'] = np.frombuffer(xml, dtype='S1')
        # Overview order differs from storage order; the empty supergrid owns nothing.
        root['varres_metadata'] = np.array([[(1, 1, 1, 2, 2, 0, 0), (0, 1, 1, 2, 2, 0, 0),
                                             (0xFFFFFFFF, 0, 0, 0, 0, 0, 0)]], dtype=grid_dtype)
        # A scan to the dataset length would count the unused -20 m record as a lead
        # and also let the unused -300 m record change the deepest sounding.
        root['varres_refinements'] = np.array([[(-100, 1), (second_depth, 1), (-20, 1), (-300, 1)]],
                                              dtype=cell_dtype)
    data = path.read_bytes()
    record.update(file_bytes=len(data), file_sha256=hashlib.sha256(data).hexdigest(),
                  metadata_sha256=hashlib.sha256(xml).hexdigest())

    result = screen(record, tmp_path)

    assert result['nearshore_depth_lead'] is lead
    assert result['raw_cells_in_25_to_200_ft_mllw_band'] == nearshore_count
    assert result['original_refinement_records'] == result['measured_depth_cells'] == 2
    assert result['shallowest_elevation_m_mllw'] == second_depth
    assert result['deepest_elevation_m_mllw'] == -100
    assert result['fishing_target'] is result['exportable'] is False
