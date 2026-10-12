"""Regular native BAG adapter. VR overviews are rejected, never resampled as depth."""
import h5py
import rasterio
from pathlib import Path

from skippercast.platform.bottom_targets import bag_metadata
from .snapshot import SealedSnapshot


def inspect_metadata(view, survey_id):
    if type(view) is not SealedSnapshot:raise ValueError("registered capability required")
    with view.open_hdf() as source:
        root = source['BAG_root']
        if 'varres_refinements' in root and root['varres_refinements'].size:
            raise ValueError('Variable-resolution BAG requires a native-refinement adapter; overview rejected')
        if root['metadata'].size > 1_000_000:
            raise ValueError('Oversized BAG metadata')
        xml = root['metadata'][:].tobytes().decode('utf-8').rstrip('\0')
    result = bag_metadata(xml, survey_id, strict=True)
    # Audited format semantics, not an invented external-document checksum.
    # BAG FSD 2.0 / Release 2.0.1 (2022-12-01), axiomatic definitions:
    # sounding z is elevation (positive up), vertical measurements are metres.
    result['elevation_convention'] = {
        'sign': 'positive_up', 'units': 'm', 'array': 'BAG_root/elevation',
        'reference_crs_role': 'vertical_reference_coordinate',
        'specification': 'BAG FSD 2.0 / Release 2.0.1 (2022-12-01)',
        'ref': 'https://bag.readthedocs.io/en/master/fsd/FSD-AxiomaticDefs.html'}
    return result
