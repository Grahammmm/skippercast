"""Admission checks for original GeoTIFF elevation samples."""
from pyproj import CRS

METRE_UNITS = {'m', 'metre', 'metres', 'meter', 'meters'}


def require_unpacked_metre_elevation(dataset):
    # Rasterio returns stored values without applying the band's scale/offset.
    if dataset.scales != (1,) or dataset.offsets != (0,):
        raise ValueError('Packed elevation values (scale/offset) are not converted silently')
    # An omitted band unit uses the native producer route's metre-elevation
    # convention, not the horizontal CRS units. Neither declaration may contradict it.
    units = (dataset.units[0] or '').strip().lower()
    if units and units not in METRE_UNITS:
        raise ValueError('Band units are not metres; refusing to convert them silently')
    if any(axis.unit_conversion_factor != 1 or axis.unit_name.lower() not in METRE_UNITS
           for axis in CRS.from_user_input(dataset.crs).axis_info[2:]):
        raise ValueError('Vertical CRS units are not metres; refusing to convert them silently')
