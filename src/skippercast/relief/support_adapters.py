"""E2E-03c: per-cell evidence adapters that may certify R2 support class 3.

``normalize.adapter_for`` reads ``ADAPTERS[family]`` and records each adapter's
id and code digest in the R2 params and sidecar, so editing this file starts a
new normalisation generation. An adapter returns uint8 classes aligned with the
Grid: 1 interpolated, 2 unknown, 3 measured on valid cells, 0 elsewhere.

Only NOAA's own per-cell coverage flags certify a cell (E2E-PIPELINE §3a):

* BlueTopo: band 3 "Contributor" codes resolved through the tile's raster
  attribute table (``<tile>.tiff.aux.xml``, declared as evidence). NOAA states
  that depths whose contributor has ``bathy_coverage`` False are interpolated,
  that bathymetry measurements are where it is True, and that ``coverage`` False
  forces ``bathy_coverage`` False (bluetopo_faq.html, bluetopo_specs.html).
* BAG / VR BAG: the optional georeferenced metadata layer of the Elevation layer
  with the same fields (profile NOAA-OCS-2022.10;
  ``BAG_root/georef_metadata/Elevation/keys`` per node, ``varres_keys`` per
  refinement node, ``values`` records; BAG FSD Appendix A). Metadata is
  layer-specific: an Uncertainty layer's table, a layer stating another profile
  type, or one stating no profile at all is never read, and support stays 2.

A cell without evidence stays 2: no evidence file or layer, key 0, a code the
table does not list, a missing flag, or ``bathy_coverage`` True without
``coverage`` True (which the specification rules out). A survey id that names
interpolation, a chart or a generalisation can only lower a class. No adapter
reads a source-wide label, a nominal resolution or a footprint. Every other
inventory family has no adapter and stays 2 (report SUPPORT-ADAPTERS.md); the
lidar return-count adapter waits for the DATA-LIVE-11 lidar-grid admission.
"""
from pathlib import Path
import xml.etree.ElementTree as ET

import h5py
import numpy as np

from .normalize import SupportAdapter

INTERPOLATED, UNKNOWN, MEASURED = 1, 2, 3
LOWERING_SURVEY_IDS = ('.interpolated', 'chart', 'generalization')
ELEVATION_LAYER, PROFILE, PROFILE_ATTRIBUTE = 'Elevation', 'NOAA-OCS-2022.10', 'Metadata Profile Type'


def text(value):
    return value.decode(errors='replace') if isinstance(value, bytes) else str(value or '')


def flag(value):
    """A documented boolean (RAT text '1'/'0', HDF5 bool or uint8), else None."""
    if isinstance(value, (bytes, str)):
        return {'1': True, 'true': True, '0': False, 'false': False}.get(text(value).strip().lower())
    if isinstance(value, (bool, np.bool_, int, np.integer)) and int(value) in (0, 1):
        return bool(value)
    return None


def record_class(coverage, bathy_coverage, survey_id=''):
    """Class of one contributor or metadata record (NOAA BlueTopo FAQ; BAG FSD App. A)."""
    full, bathy = flag(coverage), flag(bathy_coverage)
    if bathy is False:
        return INTERPOLATED
    if bathy is not True or full is not True:
        return UNKNOWN
    survey = text(survey_id).lower()
    return INTERPOLATED if any(mark in survey for mark in LOWERING_SURVEY_IDS) else MEASURED


def by_code(codes, usable, table, valid):
    """Map per-cell integer codes through {code: class}; any other valid cell is 2."""
    out = np.full(valid.shape, UNKNOWN, dtype='uint8')
    if usable.any():
        keys, inverse = np.unique(codes[usable].astype('int64'), return_inverse=True)
        out[usable] = np.array([table.get(k, UNKNOWN) for k in keys.tolist()], dtype='uint8')[inverse]
    out[~valid] = 0
    return out


def unknown(grid):
    return np.where(grid.valid, UNKNOWN, 0).astype('uint8')


def read_rat(path):
    """Contributor rows of a GDAL PAM raster attribute table: {code: {field: text}}."""
    root = ET.parse(path).getroot()
    tables = [(band.get('band'), table) for band in root.iter('PAMRasterBand')
              for table in band.findall('GDALRasterAttributeTable')]
    if not tables:
        tables = [(None, table) for table in root.iter('GDALRasterAttributeTable')]
    tables = [table for band, table in tables if band in (None, '3')]
    if len(tables) != 1:
        raise ValueError('expected one contributor raster attribute table for band 3')
    fields = {int(f.get('index')): f.findtext('Name') for f in tables[0].findall('FieldDefn')}
    names = [fields[i] for i in sorted(fields)]
    if 'value' not in names:
        raise ValueError('contributor raster attribute table has no value field')
    rows = {}
    for node in tables[0].findall('Row'):
        cells = [cell.text or '' for cell in node.findall('F')]
        if len(cells) != len(names):
            raise ValueError('malformed contributor raster attribute table row')
        row = dict(zip(names, cells))
        value = float(row['value'])
        if not value.is_integer() or rows.get(int(value), row) != row:
            raise ValueError('contributor raster attribute table has a bad or conflicting value')
        rows[int(value)] = row
    return rows


def bluetopo_classify(ds, grid, evidence):
    if not evidence:
        return unknown(grid)
    expected = Path(ds.name).name + '.aux.xml'
    if len(evidence) != 1 or Path(evidence[0]).name != expected:
        raise ValueError(f'BlueTopo evidence must be exactly this tile\'s attribute table {expected}')
    if ds.count != 3 or (ds.descriptions[2] or '').lower() != 'contributor':
        raise ValueError('BlueTopo band 3 must be the Contributor layer')
    codes = ds.read(3)
    if codes.shape != grid.valid.shape:
        raise ValueError('BlueTopo contributor band is not aligned with the elevation grid')
    table = {code: record_class(row.get('coverage'), row.get('bathy_coverage'), row.get('source_survey_id'))
             for code, row in read_rat(evidence[0]).items()}
    with np.errstate(invalid='ignore'):
        usable = (grid.valid & (ds.read_masks(3) != 0) & np.isfinite(codes)
                  & (np.abs(codes) < 2 ** 31) & (codes == np.floor(codes)))
    return by_code(np.where(usable, codes, 0), usable, table, grid.valid)


def coverage_layer(root):
    """The Elevation layer's NOAA-OCS-2022.10 georeferenced metadata, else None.

    Each ``georef_metadata`` group describes the BAG layer of the same name, so only
    ``georef_metadata/Elevation`` can say what was measured at an elevation node; an
    Uncertainty (or any other layer's) table is never read. A stated profile type other
    than the documented one, or no stated profile at all, gives the columns no documented
    meaning (the FSD makes the profile type optional and the record definition free-form,
    so matching field names alone prove nothing): no evidence.
    """
    group = root.get('georef_metadata')
    layer = group.get(ELEVATION_LAYER) if isinstance(group, h5py.Group) else None
    if not (isinstance(layer, h5py.Group) and 'keys' in layer and 'values' in layer):
        return None
    if not {'coverage', 'bathy_coverage'} <= set(layer['values'].dtype.names or ()):
        return None
    stated = []
    for holder in (layer, layer['keys'], layer['values']):
        value = holder.attrs.get(PROFILE_ATTRIBUTE)
        if value is not None:
            stated.append(text(value.item() if isinstance(value, np.ndarray) else value).strip('\0 '))
    # Affirmative evidence only: at least one statement, and every statement is the documented profile.
    return layer if stated and all(s == PROFILE for s in stated) else None


def bag_classify(ds, grid, evidence):
    if evidence:
        raise ValueError('the BAG adapter reads only the BAG file itself')
    with h5py.File(ds.name, 'r') as bag:
        root = bag['BAG_root']
        layer = coverage_layer(root)
        if layer is None:
            return unknown(grid)
        records = layer['values'][:]
        survey = records['source_survey_id'] if 'source_survey_id' in records.dtype.names else [''] * len(records)
        # Row 0 of the values table is ignored by definition (key 0 = no data).
        table = {i: record_class(records['coverage'][i], records['bathy_coverage'][i], survey[i])
                 for i in range(1, len(records))}
        if grid.refinement is None:
            keys = layer['keys'][:]
            if keys.shape != grid.valid.shape:
                raise ValueError('BAG metadata keys are not aligned with the elevation grid')
            keys = keys[::-1]  # stored south-first; the Grid is north-up
        else:
            if 'varres_keys' not in layer:
                return unknown(grid)
            block = root['varres_metadata'][grid.refinement]
            start = int(block['index'])
            ny, nx = int(block['dimensions_y']), int(block['dimensions_x'])
            vr = layer['varres_keys']
            if vr.ndim not in (1, 2) or (ny, nx) != grid.valid.shape or start + nx * ny > vr.shape[-1]:
                raise ValueError('BAG refinement metadata keys are not aligned with the refinement grid')
            stored = vr[start:start + nx * ny] if vr.ndim == 1 else vr[0, start:start + nx * ny]
            keys = stored.reshape(ny, nx)[::-1]
    usable = grid.valid & (keys > 0)
    return by_code(np.where(usable, keys, 0), usable, table, grid.valid)


BLUETOPO = SupportAdapter('nbs-contributor-bathy-coverage/1', bluetopo_classify)
BAG = SupportAdapter('bag-georef-metadata-bathy-coverage/1', bag_classify)

# Keys are inventory family names (localmapq inventory) plus normalize.py's BlueTopo alias.
ADAPTERS = {'nbs_bluetopo': BLUETOPO, 'bluetopo': BLUETOPO, 'NOAA NOS BAG survey': BAG}
