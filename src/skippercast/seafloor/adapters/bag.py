"""Regular native BAG adapter. VR overviews are rejected, never resampled as depth."""
import h5py
import rasterio
from pathlib import Path

from skippercast.platform.bottom_targets import bag_metadata


def inspect_metadata(path, survey_id):
    with h5py.File(path, 'r') as source:
        root = source['BAG_root']
        if 'varres_refinements' in root and root['varres_refinements'].size:
            raise ValueError('Variable-resolution BAG requires a native-refinement adapter; overview rejected')
        if root['metadata'].size > 1_000_000:
            raise ValueError('Oversized BAG metadata')
        xml = root['metadata'][:].tobytes().decode('utf-8').rstrip('\0')
    return bag_metadata(xml, survey_id, strict=False)


def open_source(path, row):
    inspect_metadata(path, Path(row['url']).name.split('_')[0])
    dataset = rasterio.open(path)
    if dataset.driver != 'BAG' or dataset.count != 2 or not dataset.crs:
        dataset.close()
        raise ValueError('Expected regular BAG elevation and uncertainty bands')
    return dataset
