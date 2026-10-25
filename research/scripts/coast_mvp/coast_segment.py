"""Bounded cached-only SYNTHETIC segment composition; REVIEW REQUIRED.

No discovery, fetch, coordinator execution, resume, signoff or archive. The caller
pins recipe/plan/run bytes and supplies a dedicated admitted root. Stage APIs are
used directly: no engine CLI children are spawned. Native GDAL utility APIs do
real mosaic/contour work. Real-data application is deliberately not supported.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes as ct
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import re
import stat
import sys

REPO = Path(__file__).resolve().parents[3]
DEFAULT_ADMITTED = REPO.parent / 'out'
STAGE_HASHES = {
    'coast_mosaic': 'f3f600a77722a076811d1ca8ae1723de0bcd2bfc33a2f5f8a99a8a9f3de8f6b4',
    'coast_contours': '46fde1940dcae4ccc649731a1bf9c5850e5f79aa72f13ebe0c8918bad48119d5',
    'coast_qa': 'be690acdfd81453d36a31e0e64f8ce3b09080bc6d4e9194577217f3b2572ff6f',
    'coast_rights': '76c1e470d2ceeb37b963cb4e738bc12f7c7a50789f10bee20426c7d701954702',
}
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_CELLS = 4096


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ValueError('missing checkout helper: ' + str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Source-pinned checkout helpers; never installed-engine imports.
recipe_api = load_module('s020_recipe', REPO / 'validate_recipe.py')
receipt_api = load_module('s020_receipt', REPO / 'scripts/validate_coast_receipt.py')


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def safe(path, *, root=None, directory=False):
    path = recipe_api.safe_path(Path(path), directory=directory)
    if root is not None:
        require(path.is_relative_to(root), 'outside admitted root')
    return path


def read_file(path):
    path = safe(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_size <= MAX_FILE_BYTES, 'bounded regular file required')
    # Existing no-follow, hash-checked reader also detects changes during reads.
    root_id = 'queue:control'
    resolver = receipt_api.Resolver({root_id: str(path.parent)}, allowed_root_ids={root_id})
    raw_hash = sha256(path.read_bytes()).hexdigest()
    return resolver.read(dict(root_id=root_id, path=path.name, sha256=raw_hash, bytes=info.st_size))


def read_json(path, expected=None):
    raw = read_file(path)
    if expected is not None:
        require(sha256(raw).hexdigest() == expected, 'frozen input hash mismatch')
    return receipt_api.loads(raw)


def child(root, relative):
    receipt_api.relative_parts(relative)
    return safe(root / relative, root=root)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value))


def ref(root, path, root_id):
    path = safe(path, root=root)
    raw = read_file(path)
    return dict(root_id=root_id, path=path.relative_to(root).as_posix(),
                sha256=sha256(raw).hexdigest(), bytes=len(raw))


def qualify_stages():
    """Exact API closure: four static modules, no process/network launch APIs.

    Not the separately held integration launcher or its refused contract suite.
    No CLI is called, including coast_qa's optional regional CLI branch.
    """
    import ast
    result = {}
    for name, expected in STAGE_HASHES.items():
        path = Path(__file__).parent / (name + '.py')
        raw = read_file(path)
        require(sha256(raw).hexdigest() == expected, 'stage source drift: ' + name)
        tree = ast.parse(raw)
        forbidden = {'subprocess', 'socket', 'requests', 'http', 'httpx', 'urllib.request', 'multiprocessing'}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                require(not any(a.name.split('.')[0] in forbidden for a in node.names), 'unqualified child/network import')
            if isinstance(node, ast.ImportFrom):
                require(node.module not in forbidden, 'unqualified child/network import')
            if isinstance(node, ast.Call):
                require(ast.unparse(node.func) not in {'eval', 'exec', 'os.system', 'os.popen'}, 'unqualified launch')
        result[name] = load_module('s020_' + name, path)
    return result


def verify_cog(path):
    """Independent structural check via public GDAL C raster/metadata APIs.

    Measures the actual GTiff IFD and block offsets (TIFF metadata domain), not
    filenames or the producer's self-report. Bounded single-band TIFF profile;
    directories precede data; overview IFDs and block ordering must be COG order.
    This is COG-layout validation, not scientific raster acceptance.
    """
    import rasterio
    path = safe(path)
    libs = sorted((Path(rasterio.__file__).parent.parent / 'rasterio.libs').glob('*gdal*'))
    require(bool(libs), 'supported bundled GDAL API unavailable')
    lib = ct.CDLL(str(libs[0]))
    P, I, S = ct.c_void_p, ct.c_int, ct.c_char_p
    signatures = {
        'GDALAllRegister': ([], None), 'GDALOpen': ([S, I], P), 'GDALClose': ([P], None),
        'GDALGetRasterCount': ([P], I), 'GDALGetRasterBand': ([P, I], P),
        'GDALGetMetadataItem': ([P, S, S], S), 'GDALGetOverviewCount': ([P], I),
        'GDALGetOverview': ([P, I], P), 'GDALGetRasterBandXSize': ([P], I),
        'GDALGetRasterBandYSize': ([P], I),
        'GDALGetBlockSize': ([P, ct.POINTER(I), ct.POINTER(I)], None),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(lib, name)
        fn.argtypes, fn.restype = args, result
    lib.GDALAllRegister()
    dataset = lib.GDALOpen(str(path).encode(), 0)
    require(bool(dataset), 'GDAL cannot open COG')
    try:
        require(lib.GDALGetRasterCount(dataset) == 1, 'COG requires bounded single-band profile')
        require(lib.GDALGetMetadataItem(dataset, b'LAYOUT', b'IMAGE_STRUCTURE') == b'COG', 'non-COG layout')
        band = lib.GDALGetRasterBand(dataset, 1)
        bands = [band] + [lib.GDALGetOverview(band, i) for i in range(lib.GDALGetOverviewCount(band))]
        directories, groups = [], []
        size = path.stat().st_size
        for current in bands:
            def meta(key):
                value = lib.GDALGetMetadataItem(current, key.encode(), b'TIFF')
                require(value is not None, 'missing GDAL TIFF structural metadata')
                return int(value)
            directories.append(meta('IFD_OFFSET'))
            x, y = I(), I()
            lib.GDALGetBlockSize(current, ct.byref(x), ct.byref(y))
            require(x.value >= 128 and y.value >= 128, 'COG must be tiled')
            width, height = lib.GDALGetRasterBandXSize(current), lib.GDALGetRasterBandYSize(current)
            blocks = []
            for row in range(math.ceil(height / y.value)):
                for col in range(math.ceil(width / x.value)):
                    offset, length = meta(f'BLOCK_OFFSET_{col}_{row}'), meta(f'BLOCK_SIZE_{col}_{row}')
                    require(offset > 0 and length > 0 and offset + length <= size, 'invalid TIFF data block')
                    blocks.append((offset, length))
            groups.append(blocks)
        require(directories == sorted(set(directories)), 'COG IFD order')
        ordered = [item for group in reversed(groups) for item in group]
        require(max(directories) < ordered[0][0], 'COG IFDs must precede data')
        require(all(a[0] + a[1] <= b[0] for a, b in zip(ordered, ordered[1:])), 'COG block ordering')
        return dict(format='COG', verifier='GDAL C API TIFF offsets', gdal_version=rasterio.__gdal_version__,
                    ifd_offsets=directories, block_count=len(ordered), single_band=True)
    finally:
        lib.GDALClose(dataset)


def prepare(input_root, *, admitted_root, workspace, recipe_sha256, plan_sha256, run_sha256, code_commit):
    admitted = safe(admitted_root, directory=True)
    require(admitted.is_dir(), 'admitted root must exist')
    inputs = safe(input_root, root=admitted, directory=True)
    workspace = safe(workspace, root=admitted, directory=True)
    require(not workspace.exists(), 'fresh exclusive workspace required')
    require(not inputs.is_relative_to(workspace) and not workspace.is_relative_to(inputs), 'input/output roots overlap')
    for value in (recipe_sha256, plan_sha256, run_sha256):
        require(isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value), 'exact frozen SHA256 required')
    require(re.fullmatch('[0-9a-f]{40}', code_commit) is not None, 'exact code commit required')
    recipe = read_json(inputs / 'recipe.json', recipe_sha256)
    plan = read_json(inputs / 'plan.json', plan_sha256)
    run = read_json(inputs / 'run.json', run_sha256)
    require(plan.get('schema') == 's020-synthetic-cached-plan-v1' and plan.get('synthetic_only') is True
            and plan.get('fetch') is False, 'only frozen synthetic cached plans; fetch must be off')
    require(plan.get('recipe_sha256') == recipe_sha256, 'plan/recipe identity mismatch')
    require(run['code_commit'] == code_commit, 'code identity mismatch')
    receipt_api.workflow.validate_schema(run)
    receipt_api.workflow._consistency(run)
    root_id = 'queue:' + run['campaign_segment_id']
    require(run['admission']['root_id'] == root_id, 'admission namespace mismatch')
    resolver = receipt_api.Resolver({root_id: str(inputs)}, allowed_root_ids={root_id})
    admission = receipt_api.loads(resolver.read(run['admission']))
    receipt_api.workflow.validate_schema(admission)
    require(not admission['holds'] and not admission['held_source_ids'], 'retained source hold')
    for key in ('campaign_segment_id', 'coordinator_segment_id', 'code_commit', 'skill_commit', 'plan_id', 'plan_sha256'):
        require(run[key] == admission[key], 'admission/run identity mismatch: ' + key)
    recipe_api.validate_recipe(recipe, workspace_root=admitted, metadata_root=inputs / 'metadata')
    require(bool(plan.get('sources')), 'nonempty frozen source rows required')
    ids = [row['source_id'] for row in plan['sources']]
    require(len(set(ids)) == len(ids), 'duplicate frozen source')
    require([row['catalog_id'] for row in plan['sources']] == recipe['sources'], 'recipe/plan catalog binding mismatch')
    admitted_sources = {row['source_id']: row for row in admission['sources']}
    require(set(ids) == set(admitted_sources) == set(admission['selected_source_ids']), 'source/admission population mismatch')
    sources, total, cache_need = [], 0, 0
    for index, row in enumerate(plan['sources']):
        cache = row['cache']
        require(cache['root_id'] == root_id and cache in admitted_sources[row['source_id']]['hot_cache'], 'cache/admission binding mismatch')
        target = child(inputs, cache['path'])
        require(target.suffix.lower() in {'.tif', '.tiff'}, 'synthetic cached GeoTIFF required')
        require(type(cache['bytes']) is int and 0 < cache['bytes'] <= MAX_FILE_BYTES, 'invalid cached bytes')
        total += cache['bytes']
        exists = target.exists()
        if exists:
            raw = resolver.read(cache)
            require(raw[:4] in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'), 'native TIFF bytes required')
        else:
            cache_need += cache['bytes']
        datum = recipe['datum_policy']['vertical_datum_by_source'][row['catalog_id']]
        require(datum == row['datum'] == admitted_sources[row['source_id']]['datum'], 'datum binding mismatch')
        require(type(row['resolution_m']) in (int, float) and math.isfinite(row['resolution_m']) and row['resolution_m'] > 0, 'resolution required')
        sources.append(dict(source_id=row['source_id'], bytes=cache['bytes'], cached=exists, cache_need_bytes=0 if exists else cache['bytes']))
    require(total <= recipe['cache_budget_bytes'] and total <= admission['budgets']['bytes'], 'cache budget exceeded')
    return dict(inputs=inputs, workspace=workspace, recipe=recipe, plan=plan, run=run, admission=admission,
                root_id=root_id, sources=sources, bytes=total, cache_need_bytes=cache_need)


@contextmanager
def native_offline():
    import rasterio
    import pyproj.network
    was_enabled = pyproj.network.is_network_enabled()
    pyproj.network.set_network_enabled(False)
    try:
        with rasterio.Env(GDAL_PAM_ENABLED='NO', GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR'):
            yield
    finally:
        pyproj.network.set_network_enabled(was_enabled)


def run_segment(input_root, *, workspace, admitted_root=DEFAULT_ADMITTED,
                recipe_sha256, plan_sha256, run_sha256, code_commit, dry_run=False, reserve_gib=250):
    state = prepare(input_root, admitted_root=admitted_root, workspace=workspace,
                    recipe_sha256=recipe_sha256, plan_sha256=plan_sha256, run_sha256=run_sha256, code_commit=code_commit)
    summary = {key: state[key] for key in ('sources', 'bytes', 'cache_need_bytes')}
    summary.update(fetch=False, synthetic_only=True, status='REVIEW REQUIRED', semantic_approval=False)
    if dry_run:
        return summary
    require(state['cache_need_bytes'] == 0, 'missing cached sources; fetching is disabled')
    stages = qualify_stages()
    import rasterio
    from rasterio.warp import transform_bounds
    recipe, plan, root = state['recipe'], state['plan'], state['workspace']
    require(math.isfinite(reserve_gib) and reserve_gib >= 0, 'invalid reserve')
    # C1 exact projection/cell formula is checked before any output write.
    projected = transform_bounds('EPSG:4326', 'EPSG:3310', *recipe['bbox'], densify_pts=101)
    width = math.ceil(projected[2] / 10) - math.floor(projected[0] / 10)
    height = math.ceil(projected[3] / 10) - math.floor(projected[1] / 10)
    require(0 < width * height <= MAX_CELLS, 'synthetic cell cap exceeded')
    rows = []
    for index, row in enumerate(plan['sources']):
        rights = row['rights']
        # Validate C5 metadata before stage writes; renderer remains review-required.
        rights_manifest = dict(schema_version=1, fixture_only=True, sources=[dict(
            source_id=row['source_id'], name='Synthetic ' + row['source_id'], source_url=row['source_url'],
            sha256=row['cache']['sha256'], contributed_cells=1, rights=rights)])
        stages['coast_rights'].render_manifest(rights_manifest)
        require(not any(s['csumb'] for s in stages['coast_rights']._used_sources(rights_manifest)),
                'rights permission unresolved')
        rows.append(dict(id='source-' + str(index), path=str(child(state['inputs'], row['cache']['path'])),
                         sha256=row['cache']['sha256'], resolution_m=row['resolution_m'], vertical_offset_m=0,
                         value_convention='elevation_positive_up', units='m',
                         vertical_datum='unstated' if row['datum'] == 'unknown' else row['datum'],
                         citation=row['source_url'], rights=rights['license'], attribution=rights['attribution'],
                         offset_note='Synthetic fixture; no datum transform, permission or coverage acceptance'))
    with native_offline():
        # Native validation before any output creation. Only local hash-pinned TIFFs.
        for row in rows:
            with rasterio.open(row['path'], driver='GTiff') as grid:
                require(grid.driver == 'GTiff' and grid.width * grid.height <= MAX_CELLS, 'bounded native TIFF required')
        root.mkdir(parents=True, exist_ok=False)
        def save(name, value):
            path = child(root, name)
            write_json(path, value)
            return ref(root, path, state['root_id'])
        # Preserve exact supplied recipe/run/admission bytes and cached inputs.
        for relative in ('recipe.json', 'plan.json', 'run.json', state['run']['admission']['path'],
                         *[row['cache']['path'] for row in plan['sources']]):
            dest = child(root, relative)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with dest.open('xb') as stream:
                stream.write(read_file(child(state['inputs'], relative)))
        save('stage-region.json', dict(id=recipe['slug'], bounds=recipe['bbox']))
        save('stage-sources.json', dict(schema_version=1, sources=rows))
        mosaic = stages['coast_mosaic'].mosaic(root / 'stage-region.json', root / 'stage-sources.json',
                    root / 'c1', reserve_gib=reserve_gib, max_cells=MAX_CELLS)
        measured = {name: verify_cog(root / 'c1' / row['path']) for name, row in mosaic['outputs'].items()}
        stages['coast_contours'].build(root / 'c1/elevation.tif', root / 'c1/contributor.tif', root / 'c1/manifest.json',
                    root / 'c2', max_cells=MAX_CELLS, max_tiles=4)
        # C1 manifests contain physical source paths: create a root-independent
        # copy for QA, without changing the frozen C1 receipt or cached bytes.
        stable_mosaic = json.loads(json.dumps(mosaic))
        for row in stable_mosaic['sources']:
            index = int(row['id'].split('-')[1])
            row['path'] = '../' + plan['sources'][index]['cache']['path']
        save('c1/qa-manifest.json', stable_mosaic)
        save('qa-config.json', dict(region=recipe['slug'], segments=[dict(id=recipe['slug'], manifest='c1/qa-manifest.json')]))
        qa = stages['coast_qa'].packet(root / 'qa-config.json', root / 'c4')
        rights_rows = []
        for index, row in enumerate(plan['sources']):
            rights_rows.append(dict(source_id=row['source_id'], name='Synthetic ' + row['source_id'],
                source_url=row['source_url'], sha256=row['cache']['sha256'], rights=row['rights'],
                contributed_cells=mosaic['contributor_cells'][str(next(s['code'] for s in mosaic['sources'] if s['id'] == 'source-' + str(index)))]))
        rights_manifest = dict(schema_version=1, fixture_only=True, sources=rights_rows)
        save('rights-manifest.json', rights_manifest)
        (root / 'rights.html').write_text(stages['coast_rights'].render_manifest(rights_manifest))
        bindings = [dict(source_id=row['source_id'], source_sha256=row['cache']['sha256']) for row in plan['sources']]
        inputs = []
        for index, row in enumerate(plan['sources']):
            evidence = save(f'evidence/source-{index}.json', dict(rights=row['rights'], datum=row['datum'],
                            resolution_m=row['resolution_m'], synthetic_only=True))
            inputs.append(dict(source_id=row['source_id'], source_sha256=row['cache']['sha256'], cache=row['cache'],
                               rights=evidence, datum=evidence, resolution=evidence))
        # Only accepted products are output rows; C1 volatile envelope remains
        # available for audit, but is not a root-independent content product.
        products = [(root / 'c1' / row['path'], 'coast_mosaic', measured[name]) for name, row in mosaic['outputs'].items()]
        products += [(p, 'coast_contours', dict(format=p.suffix[1:])) for p in sorted((root / 'c2').rglob('*')) if p.is_file()]
        products += [(p, 'coast_qa', dict(format=p.suffix[1:])) for p in sorted((root / 'c4').iterdir()) if p.is_file()]
        products.append((root / 'rights.html', 'coast_rights', dict(format='html')))
        outputs = []
        for index, (path, tool, measurement) in enumerate(products):
            format_ref = save(f'evidence/format-{index}.json', measurement)
            outputs.append(dict(artifact=ref(root, path, state['root_id']), contributing_sources=bindings,
                tool=dict(name=tool, version=STAGE_HASHES[tool], code_commit=code_commit),
                parameters=dict(driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                                plan_sha256=plan_sha256, synthetic_only=True),
                measured_format=format_ref))
        stats = qa['segments'][0]['stats']
        support = save('evidence/support.json', dict(crs=mosaic['crs'], bounds=mosaic['bounds_projected'],
                    width=mosaic['width'], height=mosaic['height'], resolution_m=10, water_mask='unavailable'))
        threshold = save('evidence/threshold.json', dict(hole_fraction_above=0.1, denominator='entire rectangular regular grid'))
        run = state['run']
        receipt = dict(schema='coast-segment-receipt-v1', schema_version=1,
            **{key: run[key] for key in ('created_utc', 'author_profile', 'author_model', 'card_id', 'code_commit',
                    'skill_commit', 'campaign_segment_id', 'coordinator_segment_id')},
            segment_slug=recipe['slug'], recipe_sha256=recipe_sha256, recipe=ref(root, root / 'recipe.json', state['root_id']),
            run=ref(root, root / 'run.json', state['root_id']), inputs=inputs, outputs=outputs,
            qa=dict(report=ref(root, root / 'c4/qa.json', state['root_id']), hole_numerator=stats['hole_cells'],
                coverage_denominator=stats['grid_cells'], units='regular grid cells', spatial_support=support,
                flags=['holes_above_10_percent'] if stats['hole_cells'] / stats['grid_cells'] > 0.1 else [], threshold_config=threshold),
            tier1=dict(mode='unavailable', text_result='unavailable', vision_result='unavailable',
                       reason='S-023 owns screening; no model or vision check performed'), closed=False)
        receipt['determinism_digest'] = receipt_api.determinism_digest(receipt)
        resolver = receipt_api.Resolver({state['root_id']: str(root)}, allowed_root_ids={state['root_id']})
        validation = receipt_api.validate_receipt(receipt, resolver, root_id=state['root_id'])
        save('receipt.json', receipt)
        return dict(**summary, receipt=receipt, validation=validation)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--admitted-root', default=DEFAULT_ADMITTED, type=Path)
    for name in ('recipe-sha256', 'plan-sha256', 'run-sha256', 'code-commit'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = vars(parser.parse_args(argv))
    try:
        result = run_segment(**args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
