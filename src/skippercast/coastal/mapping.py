"""Private segment mapping preserving bounded native cells without resampling."""
import json
import hashlib
from pathlib import Path

from .handoff import mapping_input
from .handoff.common import confined, digest, load, ref, resolve, write, validate_derived_geotiff

SCHEMA = 'coastal-mapping-run-v1'


def implementation():
    from skippercast.seafloor import terrain
    return {Path(module.__file__).name: hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
            for module in (terrain,)} | {'mapping.py': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def run(root, mapping_manifest, *, output_dir, now, review=None, minimum_valid_until=None):
    import numpy as np
    import rasterio
    from rasterio.shutil import copy as raster_copy
    from skippercast.coastal import vertical
    from skippercast.seafloor.terrain import derivatives, summarize
    manifest = load(root, mapping_manifest, contract=mapping_input.SCHEMA)
    out = confined(root, output_dir, existing=False)
    if out.exists() and any(out.iterdir()):
        completed = out / 'run.json'
        if not completed.is_file():
            raise ValueError('interrupted mapping output preserved; use a new owned output directory')
        prior = load(root, ref(root, completed, SCHEMA), contract=SCHEMA)
        if digest(prior.get('mapping_input')) != digest(manifest):
            raise ValueError('mapping output already belongs to a different input')
        verified = verify(root, prior, now=now, minimum_valid_until=minimum_valid_until)
        if not verified['ready']:
            return dict(schema=SCHEMA, segment_id=manifest['segment_id'], state='held', holds=verified['holds'])
        return prior
    checked = mapping_input.verify(root, manifest, now=now,minimum_valid_until=minimum_valid_until)
    if not checked['ready']:
        return dict(schema=SCHEMA, segment_id=manifest['segment_id'], state='held', holds=checked['holds'])
    facts, holds, _, valid, transform, crs, depth = mapping_input.observe(
        root, manifest['source'], window=manifest['window'], vertical=manifest['declared_vertical'],
        source_row=manifest.get('source_row'), metadata_sha256=manifest.get('metadata_sha256'))
    mapping_input.bind_segment(root,manifest.get('segment'),manifest['segment_id'],facts)
    facts.update(rights=manifest.get('rights'),synthetic=manifest.get('synthetic'))
    if facts['header']['resolution_m'][0] != facts['header']['resolution_m'][1]:
        return dict(schema=SCHEMA, segment_id=manifest['segment_id'], state='held',
                    holds=['native_rectangular_grid_derivatives_unsupported'])
    out.mkdir(parents=True, exist_ok=True)
    normalized = vertical.normalized(facts['vertical'])
    temporary = out / '.native-depth.tif'
    with rasterio.open(temporary, 'w', driver='GTiff', width=valid.shape[1], height=valid.shape[0],
                       count=1, dtype='float32', crs=crs, transform=transform, nodata=np.nan,
                       tiled=True, blockxsize=128, blockysize=128, compress='DEFLATE') as ds:
        ds.write(np.where(valid, depth, np.nan).astype('float32'), 1)
        ds.write_mask(valid.astype('uint8')*255)
        ds.set_band_description(1, 'depth_m_positive_down')
        ds.set_band_unit(1, 'm')
        ds.update_tags(vertical_contract=json.dumps(normalized, sort_keys=True, separators=(',', ':')),
                       vertical_sign='positive_down', scale_offset_applied='true',
                       vertical_datum=normalized['datum'], datum_realization=normalized['datum_realization'], source_sha256=manifest['source']['sha256'],
                       facts_digest=manifest['facts_digest'], publication_prohibited='true')
    terrain = out / 'terrain.tif'
    raster_copy(temporary, terrain, driver='COG', compress='DEFLATE', blocksize=128, overview_count=0)
    temporary.unlink()
    mask_path = out / 'support.tif'
    with rasterio.open(mask_path, 'w', driver='GTiff', width=valid.shape[1], height=valid.shape[0],
                       count=1, dtype='uint8', crs=crs, transform=transform, nodata=None, compress='DEFLATE') as ds:
        ds.write(valid.astype('uint8'), 1)
        ds.set_band_description(1, 'native_valid_support')
    layers = derivatives(depth, valid, max(facts['header']['resolution_m'])) if min(depth.shape) >= 3 else {}
    cells = dict(schema='coastal-terrain-summary-v1', segment_id=manifest['segment_id'], segment=manifest['segment'],
                 native_valid_count=int(valid.sum()), depth_m=summarize({'depth':depth}, valid)['depth'],
                 derivatives=summarize(layers, valid), support=facts['support'],
                 native_resolution_m=facts['header']['resolution_m'], interpolated=False,
                 habitat='unassessed', publication_prohibited=True)
    write(out / 'cells.json', cells)
    outputs = dict(terrain=ref(root, terrain, 'coastal-normalized-terrain-v1'),
                   mask=ref(root, mask_path, 'coastal-native-support-v2'),
                   cells=ref(root, out / 'cells.json', 'coastal-terrain-summary-v1'))
    result = dict(schema=SCHEMA, state='done', holds=[], segment_id=manifest['segment_id'],
                  mapping_input=manifest, facts_digest=manifest['facts_digest'], source=manifest['source'], segment=manifest['segment'],
                  vertical=normalized, outputs=outputs, publication_prohibited=True,
                  synthetic=manifest['synthetic'], provenance=dict(libs=mapping_input.libraries(),
                  implementation=implementation()))
    write(out / 'run.json', result)
    return result


def verify(root, run_manifest, *, now, minimum_valid_until=None):
    import numpy as np
    import rasterio
    from skippercast.coastal import vertical
    document = load(root, run_manifest, contract=SCHEMA)
    if document.get('schema') != SCHEMA or document.get('state') != 'done':
        raise ValueError('completed mapping run required')
    if document.get('provenance') != dict(libs=mapping_input.libraries(), implementation=implementation()):
        raise ValueError('mapping implementation/dependencies changed')
    source_manifest = document['mapping_input']
    if (document.get('source') != source_manifest.get('source')
            or document.get('segment_id') != source_manifest.get('segment_id')
            or document.get('segment') != source_manifest.get('segment')
            or document.get('synthetic') != source_manifest.get('synthetic')
            or document.get('publication_prohibited') is not True):
        raise ValueError('mapping source/prohibition lineage changed')
    checked = mapping_input.verify(root, source_manifest, now=now,minimum_valid_until=minimum_valid_until)
    facts, holds, _, valid, transform, crs, depth = mapping_input.observe(
        root, source_manifest['source'], window=source_manifest['window'], vertical=source_manifest['declared_vertical'],
        source_row=source_manifest.get('source_row'), metadata_sha256=source_manifest.get('metadata_sha256'))
    mapping_input.bind_segment(root,source_manifest.get('segment'),source_manifest['segment_id'],facts)
    facts.update(rights=source_manifest.get('rights'),synthetic=source_manifest.get('synthetic'))
    if facts['header']['resolution_m'][0] != facts['header']['resolution_m'][1]:
        raise ValueError('native_rectangular_grid_derivatives_unsupported')
    if document['facts_digest'] != checked['facts_digest'] or document['vertical'] != vertical.normalized(facts['vertical']):
        raise ValueError('mapping source/vertical lineage changed')
    with rasterio.open(validate_derived_geotiff(root, document['outputs']['terrain'], contract='coastal-normalized-terrain-v1')) as ds:
        if ds.shape != valid.shape or ds.count != 1 or ds.dtypes != ('float32',):
            raise ValueError('normalized terrain grid/header differs from native source')
        actual = ds.read(1, masked=True)
        if (ds.transform != transform or ds.crs != crs or ds.shape != valid.shape or ds.count != 1
                or ds.descriptions != ('depth_m_positive_down',) or ds.dtypes != ('float32',)
                or ds.units != ('m',) or ds.scales != (1.0,) or ds.offsets != (0.0,)
                or ds.tags().get('vertical_sign') != 'positive_down'
                or ds.tags().get('scale_offset_applied') != 'true'
                or ds.tags().get('datum_realization', 'unknown') != document['vertical']['datum_realization']
                or ds.tags().get('vertical_datum') != document['vertical']['datum']
                or ds.tags().get('publication_prohibited') != 'true'
                or json.loads(ds.tags().get('vertical_contract', '{}')) != document['vertical']
                or not np.array_equal(~np.ma.getmaskarray(actual), valid)
                or not np.array_equal(actual.filled(np.nan)[valid], depth.astype('float32')[valid])):
            raise ValueError('normalized terrain differs from exact native values/header')
    with rasterio.open(validate_derived_geotiff(root, document['outputs']['mask'], contract='coastal-native-support-v2')) as ds:
        if (ds.shape != valid.shape or ds.count != 1 or ds.dtypes != ('uint8',)
                or ds.transform != transform or ds.crs != crs
                or not np.array_equal(ds.read(1),valid.astype('uint8'))):
            raise ValueError('mapping support differs from native cells')
    cells = load(root, document['outputs']['cells'], contract='coastal-terrain-summary-v1')
    from skippercast.seafloor.terrain import derivatives, summarize
    layers = derivatives(depth, valid, max(facts['header']['resolution_m'])) if min(depth.shape) >= 3 else {}
    if (cells.get('segment_id') != document['segment_id'] or cells.get('segment') != document['segment']
            or digest(cells['support']) != digest(facts['support']) or cells['native_valid_count'] != int(valid.sum())
            or cells.get('depth_m') != summarize({'depth': depth}, valid)['depth']
            or cells.get('derivatives') != summarize(layers,valid)
            or cells.get('native_resolution_m') != facts['header']['resolution_m']
            or cells.get('interpolated') is not False
            or cells.get('schema') != 'coastal-terrain-summary-v1'
            or cells.get('habitat') != 'unassessed'
            or cells.get('publication_prohibited') is not True):
        raise ValueError('mapping support summary changed')
    return dict(ready=checked['ready'], holds=checked['holds'], run=document, facts=facts)
