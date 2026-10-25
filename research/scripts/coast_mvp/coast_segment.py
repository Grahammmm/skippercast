"""Bounded cached-only SYNTHETIC segment composition; REVIEW REQUIRED.

No discovery, fetch, coordinator execution, signoff or archive. The caller
pins recipe/plan/run bytes and supplies a dedicated admitted root. Stage APIs are
used directly: no engine CLI children are spawned. Native GDAL utility APIs do
real mosaic/contour work. Real-data application is deliberately not supported.

S-026 resume: every stage writes a sealed, write-once stage receipt binding its
exact inputs, outputs, tool bytes and recipe/plan/run pins. A rerun skips only
stages whose binding and output bytes still match; stale or tampered stages are
refused, never silently reused or overwritten. Residue of an interrupted stage is
moved (renamed) into quarantine/; nothing is ever deleted and no cache is
released. Manifests are write-once and recorded in an append-only hash-chained
history. Archiving stays with skills/coast-segment-close.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes as ct
from hashlib import sha256
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4

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


def prepare(input_root, *, admitted_root, workspace, recipe_sha256, plan_sha256, run_sha256, code_commit,
            resume=False):
    admitted = safe(admitted_root, directory=True)
    require(admitted.is_dir(), 'admitted root must exist')
    inputs = safe(input_root, root=admitted, directory=True)
    workspace = safe(workspace, root=admitted, directory=True)
    existing = resume and workspace.exists()
    if existing:
        marker = workspace / MARKER
        require(workspace.is_dir() and marker.is_file() and not marker.is_symlink(),
                'resume requires an existing marked segment workspace')
    else:
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
    state = dict(inputs=inputs, workspace=workspace, recipe=recipe, plan=plan, run=run, admission=admission,
                 root_id=root_id, sources=sources, bytes=total, cache_need_bytes=cache_need)
    if existing:
        require(read_json(workspace / MARKER) == workspace_marker(state), 'resume workspace marker mismatch')
    return state


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


STAGES = ('inputs', 'c1', 'c2', 'c4', 'c5', 'receipt')
STAGE_TOOLS = {'inputs': (), 'c1': ('coast_mosaic',), 'c2': ('coast_contours',), 'c4': ('coast_qa',),
               'c5': ('coast_rights',), 'receipt': ()}
STAGE_SCHEMA = 'coast-segment-stage-v1'
MARKER = 'segment-workspace.json'
STAGE_DIR, MANIFEST_DIR, QUARANTINE_DIR = 'stages', 'manifests', 'quarantine'
HISTORY = MANIFEST_DIR + '/history.jsonl'
ARCHIVE_OWNER = 'skills/coast-segment-close (archive_segment.py, verify_archive.py; release_hot_cache.py operator-only)'


def workspace_marker(state):
    return dict(schema='coast-segment-workspace-v1', root_id=state['root_id'], segment_slug=state['recipe']['slug'],
                campaign_segment_id=state['run']['campaign_segment_id'])


def file_sha(path):
    return sha256(read_file(path)).hexdigest()


def tool_identity(stage):
    """Measured tool binding: driver, stage-module and helper bytes plus native versions."""
    import numpy
    import rasterio
    here = Path(__file__).resolve()
    return dict(driver_sha256=file_sha(here),
                stages={name: file_sha(here.parent / (name + '.py')) for name in STAGE_TOOLS[stage]},
                helpers={'validate_recipe.py': file_sha(REPO / 'validate_recipe.py'),
                         'validate_coast_receipt.py': file_sha(REPO / 'scripts/validate_coast_receipt.py')},
                rasterio=rasterio.__version__, gdal=rasterio.__gdal_version__, numpy=numpy.__version__)


def owned_paths(state, stage):
    """Workspace-relative paths a stage creates. Later stages never write here."""
    if stage == 'inputs':
        return ['recipe.json', 'plan.json', 'run.json', state['run']['admission']['path'],
                *[row['cache']['path'] for row in state['plan']['sources']], 'stage-region.json', 'stage-sources.json']
    return {'c1': ['c1'], 'c2': ['c2'], 'c4': ['c1/qa-manifest.json', 'qa-config.json', 'c4'],
            'c5': ['rights-manifest.json', 'rights.html'], 'receipt': ['evidence', 'receipt.json']}[stage]


def stage_binding(state, stage, upstream, pins, params):
    if stage == 'inputs':
        copied = owned_paths(state, 'inputs')[:-2]
        inputs = [ref(state['inputs'], child(state['inputs'], relative), 'input') for relative in copied]
    else:
        inputs = list(upstream)
    return dict(schema='coast-segment-stage-binding-v1', stage=stage, recipe=dict(pins, parameters=params),
                tool=tool_identity(stage), inputs=inputs)


def stage_seal(value):
    return sha256(canonical({k: v for k, v in value.items() if k != 'seal_sha256'})).hexdigest()


def load_stage(root, stage):
    """Return (receipt, 'sealed') or (None, 'absent'|'partial'). Never trusts partial bytes."""
    path = root / STAGE_DIR / (stage + '.json')
    require(not path.is_symlink(), 'symlinked stage receipt refused: ' + stage)
    if not path.exists():
        return None, 'absent'
    value, sealed = None, False
    try:
        raw = read_file(path)
        value = receipt_api.loads(raw)
        sealed = (isinstance(value, dict) and raw == canonical(value) and value.get('schema') == STAGE_SCHEMA
                  and value.get('stage') == stage and value.get('complete') is True
                  and isinstance(value.get('outputs'), list) and value.get('seal_sha256') == stage_seal(value)
                  and value.get('binding_sha256') == sha256(canonical(value.get('binding'))).hexdigest())
    except (ValueError, TypeError, KeyError, RecursionError):
        sealed = False
    return (value, 'sealed') if sealed else (None, 'partial')


def write_stage(root, stage, value):
    """Fully written + fsynced pending file, then renamed into a never-existing name."""
    value = {k: v for k, v in value.items() if k != 'seal_sha256'}
    value['seal_sha256'] = stage_seal(value)
    final = root / STAGE_DIR / (stage + '.json')
    pending = root / STAGE_DIR / '.pending' / f'{stage}-{uuid4().hex}.json'
    pending.parent.mkdir(parents=True, exist_ok=True)
    with pending.open('xb') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    require(not final.exists() and not final.is_symlink(), 'stage receipt already exists; never overwritten')
    os.rename(pending, final)
    return value


def residue(state, stage):
    root = state['workspace']
    return any((root / r).exists() or (root / r).is_symlink()
               for r in owned_paths(state, stage) + [f'{STAGE_DIR}/{stage}.json'])


def quarantine(state, stage, attempt):
    """Rename (never delete) an incomplete stage's residue and partial receipt aside."""
    root, moved = state['workspace'], []
    for relative in owned_paths(state, stage) + [f'{STAGE_DIR}/{stage}.json']:
        source = child(root, relative)
        if source.exists():
            dest = child(root, f'{QUARANTINE_DIR}/{attempt}/{stage}/{relative}')
            require(not dest.exists(), 'quarantine collision')
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.rename(source, dest)
            moved.append(dest.relative_to(root).as_posix())
    return moved


def collect_outputs(state, stage):
    root, refs = state['workspace'], []
    for relative in owned_paths(state, stage):
        path = child(root, relative)
        files = sorted(p for p in path.rglob('*') if not p.is_dir()) if path.is_dir() else [path]
        refs += [ref(root, p, state['root_id']) for p in files]
    return sorted(refs, key=lambda r: r['path'])


def verify_outputs(root, outputs):
    for item in outputs:
        path = child(root, item['path'])
        if path.is_symlink() or not path.is_file():
            return 'missing output ' + item['path']
        raw = read_file(path)
        if (sha256(raw).hexdigest(), len(raw)) != (item['sha256'], item['bytes']):
            return 'output hash mismatch ' + item['path']
    return None


def _save(state, name, value):
    path = child(state['workspace'], name)
    write_json(path, value)
    return ref(state['workspace'], path, state['root_id'])


def _run_inputs(state, stages, results, pins, params):
    root = state['workspace']
    # Preserve exact supplied recipe/run/admission bytes and cached inputs.
    for relative in owned_paths(state, 'inputs')[:-2]:
        dest = child(root, relative)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with dest.open('xb') as stream:
            stream.write(read_file(child(state['inputs'], relative)))
    _save(state, 'stage-region.json', dict(id=state['recipe']['slug'], bounds=state['recipe']['bbox']))
    _save(state, 'stage-sources.json', dict(schema_version=1, sources=state['rows']))
    return {}


def _run_c1(state, stages, results, pins, params):
    root = state['workspace']
    mosaic = stages['coast_mosaic'].mosaic(root / 'stage-region.json', root / 'stage-sources.json',
                root / 'c1', reserve_gib=state['reserve_gib'], max_cells=MAX_CELLS)
    measured = {name: verify_cog(root / 'c1' / row['path']) for name, row in mosaic['outputs'].items()}
    return dict(mosaic=mosaic, measured=measured)


def _run_c2(state, stages, results, pins, params):
    root = state['workspace']
    stages['coast_contours'].build(root / 'c1/elevation.tif', root / 'c1/contributor.tif', root / 'c1/manifest.json',
                root / 'c2', max_cells=MAX_CELLS, max_tiles=params['max_tiles'])
    return {}


def _run_c4(state, stages, results, pins, params):
    root, recipe = state['workspace'], state['recipe']
    # C1 manifests contain physical source paths: create a root-independent
    # copy for QA, without changing the frozen C1 receipt or cached bytes.
    stable_mosaic = json.loads(json.dumps(results['c1']['mosaic']))
    for row in stable_mosaic['sources']:
        index = int(row['id'].split('-')[1])
        row['path'] = '../' + state['plan']['sources'][index]['cache']['path']
    _save(state, 'c1/qa-manifest.json', stable_mosaic)
    _save(state, 'qa-config.json', dict(region=recipe['slug'], segments=[dict(id=recipe['slug'], manifest='c1/qa-manifest.json')]))
    return dict(qa=stages['coast_qa'].packet(root / 'qa-config.json', root / 'c4'))


def _run_c5(state, stages, results, pins, params):
    mosaic, rights_rows = results['c1']['mosaic'], []
    for index, row in enumerate(state['plan']['sources']):
        code = next(s['code'] for s in mosaic['sources'] if s['id'] == 'source-' + str(index))
        rights_rows.append(dict(source_id=row['source_id'], name='Synthetic ' + row['source_id'],
            source_url=row['source_url'], sha256=row['cache']['sha256'], rights=row['rights'],
            contributed_cells=mosaic['contributor_cells'][str(code)]))
    rights_manifest = dict(schema_version=1, fixture_only=True, sources=rights_rows)
    _save(state, 'rights-manifest.json', rights_manifest)
    with child(state['workspace'], 'rights.html').open('xb') as stream:
        stream.write(stages['coast_rights'].render_manifest(rights_manifest).encode('utf-8'))
    return {}


def _run_receipt(state, stages, results, pins, params):
    root, plan, recipe, run = state['workspace'], state['plan'], state['recipe'], state['run']
    mosaic, measured, qa = results['c1']['mosaic'], results['c1']['measured'], results['c4']['qa']
    save = lambda name, value: _save(state, name, value)  # noqa: E731
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
            tool=dict(name=tool, version=STAGE_HASHES[tool], code_commit=pins['code_commit']),
            parameters=dict(driver_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
                            plan_sha256=pins['plan_sha256'], synthetic_only=True),
            measured_format=format_ref))
    stats = qa['segments'][0]['stats']
    support = save('evidence/support.json', dict(crs=mosaic['crs'], bounds=mosaic['bounds_projected'],
                width=mosaic['width'], height=mosaic['height'], resolution_m=10, water_mask='unavailable'))
    threshold = save('evidence/threshold.json', dict(hole_fraction_above=0.1, denominator='entire rectangular regular grid'))
    receipt = dict(schema='coast-segment-receipt-v1', schema_version=1,
        **{key: run[key] for key in ('created_utc', 'author_profile', 'author_model', 'card_id', 'code_commit',
                'skill_commit', 'campaign_segment_id', 'coordinator_segment_id')},
        segment_slug=recipe['slug'], recipe_sha256=pins['recipe_sha256'], recipe=ref(root, root / 'recipe.json', state['root_id']),
        run=ref(root, root / 'run.json', state['root_id']), inputs=inputs, outputs=outputs,
        qa=dict(report=ref(root, root / 'c4/qa.json', state['root_id']), hole_numerator=stats['hole_cells'],
            coverage_denominator=stats['grid_cells'], units='regular grid cells', spatial_support=support,
            flags=['holes_above_10_percent'] if stats['hole_cells'] / stats['grid_cells'] > 0.1 else [], threshold_config=threshold),
        tier1=dict(mode='unavailable', text_result='unavailable', vision_result='unavailable',
                   reason='S-023 owns screening; no model or vision check performed'), closed=False)
    receipt['determinism_digest'] = receipt_api.determinism_digest(receipt)
    resolver = receipt_api.Resolver({state['root_id']: str(root)}, allowed_root_ids={state['root_id']})
    receipt_api.validate_receipt(receipt, resolver, root_id=state['root_id'])
    save('receipt.json', receipt)
    return dict(receipt=receipt)


RUNNERS = {'inputs': _run_inputs, 'c1': _run_c1, 'c2': _run_c2, 'c4': _run_c4, 'c5': _run_c5, 'receipt': _run_receipt}


def _walk(state, *, pins, params, execute, stages=None):
    """Classify each stage in order; in execute mode reuse, refuse or run it.

    Status values: complete (sealed receipt, exact binding, output bytes match),
    stale (sealed receipt with a different binding), tampered (exact binding but
    missing/changed output), incomplete (partial receipt or residue), pending
    (nothing written), blocked (an upstream stage is not complete).
    """
    root, upstream, results, values, report = state['workspace'], [], {}, {}, []
    attempt, blocked = uuid4().hex, False
    for stage in STAGES:
        if blocked:
            report.append(dict(stage=stage, status='blocked'))
            continue
        binding = stage_binding(state, stage, upstream, pins, params)
        digest = sha256(canonical(binding)).hexdigest()
        value, why = load_stage(root, stage) if root.exists() else (None, 'absent')
        problem = None
        if value is None:
            status = 'incomplete' if why == 'partial' or (root.exists() and residue(state, stage)) else 'pending'
        elif value['binding_sha256'] != digest:
            status = 'stale'
        else:
            problem = verify_outputs(root, value['outputs'])
            status = 'tampered' if problem else 'complete'
        if not execute:
            report.append(dict(stage=stage, status=status, **({'reason': problem} if problem else {})))
            blocked = status != 'complete'
            if not blocked:
                upstream += value['outputs']
            continue
        require(status != 'stale', 'stale stage binding refused: ' + stage)
        require(status != 'tampered', f'tampered stage output refused: {stage}: {problem}')
        if status == 'complete':
            report.append(dict(stage=stage, action='reused', quarantined=[]))
        else:
            moved = quarantine(state, stage, attempt) if status == 'incomplete' else []
            result = receipt_api.loads(canonical(RUNNERS[stage](state, stages, results, pins, params)))
            value = write_stage(root, stage, dict(schema=STAGE_SCHEMA, stage=stage, binding=binding,
                binding_sha256=digest, outputs=collect_outputs(state, stage), result=result, complete=True,
                status='REVIEW REQUIRED', semantic_approval=False))
            report.append(dict(stage=stage, action='executed', quarantined=moved))
        results[stage], values[stage] = value['result'], value
        upstream += value['outputs']
    return results, values, report


def _write_manifest(state, prefix, value):
    root, raw = state['workspace'], canonical(value)
    path = child(root, f'{MANIFEST_DIR}/{prefix}-{sha256(raw).hexdigest()[:16]}.json')
    if path.exists():
        require(read_file(path) == raw, 'existing manifest differs; never overwritten')
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)
    return ref(root, path, state['root_id'])


def verify_history(state):
    """Return (rows, tip sha). Any partial/edited/reordered row refuses."""
    path = state['workspace'] / HISTORY
    if not path.exists() and not path.is_symlink():
        return 0, None
    raw, previous = read_file(child(state['workspace'], HISTORY)), None
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        try:
            item = receipt_api.loads(line)
            ok = (line == canonical(item) and item.get('seq') == index and item.get('previous_row_sha256') == previous)
        except (ValueError, TypeError, AttributeError, RecursionError):
            ok = False
        require(ok, 'manifest history damaged; attended reconciliation required')
        previous = sha256(line).hexdigest()
    return len(lines), previous


def _append_history(state, row):
    count, previous = verify_history(state)
    row = dict(row, schema='coast-segment-manifest-history-v1', seq=count, previous_row_sha256=previous)
    data = canonical(row)
    path = child(state['workspace'], HISTORY)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('ab') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(seq=count, rows=count + 1, row_sha256=sha256(data).hexdigest())


def _manifests(state, values, report, *, viewer):
    root, root_id = state['workspace'], state['root_id']
    receipt = values['receipt']['result']['receipt']
    stage_receipts = [ref(root, root / STAGE_DIR / (stage + '.json'), root_id) for stage in STAGES]
    files = sorted((item for stage in STAGES for item in values[stage]['outputs']), key=lambda r: r['path'])
    archive = _write_manifest(state, 'archive-candidates', dict(
        schema='coast-segment-archive-candidates-v1', campaign_segment_id=state['run']['campaign_segment_id'],
        segment_slug=state['recipe']['slug'], determinism_digest=receipt['determinism_digest'],
        receipt=ref(root, root / 'receipt.json', root_id), stage_receipts=stage_receipts, files=files,
        cache_files=[item for item in files if item['path'].startswith('cache/')],
        archive_owner=ARCHIVE_OWNER, archived=False, archive_verified=False,
        cache_release='not performed; release_hot_cache.py is operator-only', closed=False,
        status='REVIEW REQUIRED', semantic_approval=False))
    viewer_ref = None
    if viewer:
        layers = sorted((item for stage in ('c1', 'c2', 'c4') for item in values[stage]['outputs']
                         if item['path'].startswith(('c1/', 'c2/', 'c4/'))), key=lambda r: r['path'])
        viewer_ref = _write_manifest(state, 'viewer', dict(
            schema='coast-segment-local-viewer-v1', opt_in=True, local_only=True, publication_allowed=False,
            mask_qualified=False, terrain_mask_gate='HELD; this manifest never implies mask qualification',
            segment_slug=state['recipe']['slug'], determinism_digest=receipt['determinism_digest'],
            receipt=ref(root, root / 'receipt.json', root_id), layers=layers, status='REVIEW REQUIRED'))
    history = _append_history(state, dict(
        determinism_digest=receipt['determinism_digest'], code_commit=state['run']['code_commit'],
        executed=[r['stage'] for r in report if r['action'] == 'executed'],
        reused=[r['stage'] for r in report if r['action'] == 'reused'],
        quarantined=[path for r in report for path in r['quarantined']],
        archive_candidates=archive, viewer=viewer_ref))
    return dict(archive_candidates=archive, viewer=viewer_ref), history


def _preflight(state, reserve_gib):
    """All checks that precede any workspace write."""
    require(state['cache_need_bytes'] == 0, 'missing cached sources; fetching is disabled')
    stages = qualify_stages()
    state['reserve_gib'] = reserve_gib
    import rasterio
    from rasterio.warp import transform_bounds
    recipe, plan = state['recipe'], state['plan']
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
    state['rows'] = rows
    return stages


def _pins(recipe_sha256, plan_sha256, run_sha256, code_commit):
    return dict(recipe_sha256=recipe_sha256, plan_sha256=plan_sha256, run_sha256=run_sha256, code_commit=code_commit)


def _params(reserve_gib):
    # The disk reserve is a run-time precondition, not an output-shaping input,
    # so it is enforced on execution but deliberately not part of stage bindings.
    return dict(max_cells=MAX_CELLS, max_tiles=4, synthetic_only=True)


def _execute(input_root, *, workspace, admitted_root, recipe_sha256, plan_sha256, run_sha256, code_commit,
             dry_run, reserve_gib, resume, viewer):
    state = prepare(input_root, admitted_root=admitted_root, workspace=workspace, recipe_sha256=recipe_sha256,
                    plan_sha256=plan_sha256, run_sha256=run_sha256, code_commit=code_commit, resume=resume)
    summary = {key: state[key] for key in ('sources', 'bytes', 'cache_need_bytes')}
    summary.update(fetch=False, synthetic_only=True, status='REVIEW REQUIRED', semantic_approval=False)
    if dry_run:
        return summary
    stages = _preflight(state, reserve_gib)
    pins, params = _pins(recipe_sha256, plan_sha256, run_sha256, code_commit), _params(reserve_gib)
    root = state['workspace']
    if root.exists():
        verify_history(state)  # refuse a damaged history before any stage work
    with native_offline():
        if not root.exists():
            root.mkdir(parents=True, exist_ok=False)
            write_json(root / MARKER, workspace_marker(state))
        results, values, report = _walk(state, pins=pins, params=params, execute=True, stages=stages)
        receipt = results['receipt']['receipt']
        resolver = receipt_api.Resolver({state['root_id']: str(root)}, allowed_root_ids={state['root_id']})
        validation = receipt_api.validate_receipt(receipt, resolver, root_id=state['root_id'])
        manifests, history = _manifests(state, values, report, viewer=viewer)
    return dict(**summary, receipt=receipt, validation=validation, stages=report,
                executed=[r['stage'] for r in report if r['action'] == 'executed'],
                reused=[r['stage'] for r in report if r['action'] == 'reused'],
                manifests=manifests, history=history)


def run_segment(input_root, *, workspace, admitted_root=DEFAULT_ADMITTED,
                recipe_sha256, plan_sha256, run_sha256, code_commit, dry_run=False, reserve_gib=250, viewer=False):
    """Fresh exclusive workspace only (S-020 contract); stage receipts make it resumable."""
    return _execute(input_root, workspace=workspace, admitted_root=admitted_root, recipe_sha256=recipe_sha256,
                    plan_sha256=plan_sha256, run_sha256=run_sha256, code_commit=code_commit, dry_run=dry_run,
                    reserve_gib=reserve_gib, resume=False, viewer=viewer)


def resume_segment(input_root, *, workspace, admitted_root=DEFAULT_ADMITTED,
                   recipe_sha256, plan_sha256, run_sha256, code_commit, dry_run=False, reserve_gib=250, viewer=False):
    """Resume a marked workspace (or start a fresh one). Reuses only exactly bound stages."""
    return _execute(input_root, workspace=workspace, admitted_root=admitted_root, recipe_sha256=recipe_sha256,
                    plan_sha256=plan_sha256, run_sha256=run_sha256, code_commit=code_commit, dry_run=dry_run,
                    reserve_gib=reserve_gib, resume=True, viewer=viewer)


def segment_status(input_root, *, workspace, admitted_root=DEFAULT_ADMITTED,
                   recipe_sha256, plan_sha256, run_sha256, code_commit, reserve_gib=250):
    """Read-only truthful per-stage status for the given pins. Writes nothing."""
    state = prepare(input_root, admitted_root=admitted_root, workspace=workspace, recipe_sha256=recipe_sha256,
                    plan_sha256=plan_sha256, run_sha256=run_sha256, code_commit=code_commit, resume=True)
    require(math.isfinite(reserve_gib) and reserve_gib >= 0, 'invalid reserve')
    _, _, report = _walk(state, pins=_pins(recipe_sha256, plan_sha256, run_sha256, code_commit),
                         params=_params(reserve_gib), execute=False)
    return dict(stages=report, complete=all(r['status'] == 'complete' for r in report),
                status='REVIEW REQUIRED', semantic_approval=False, closed=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True, type=Path)
    parser.add_argument('--workspace', required=True, type=Path)
    parser.add_argument('--admitted-root', default=DEFAULT_ADMITTED, type=Path)
    for name in ('recipe-sha256', 'plan-sha256', 'run-sha256', 'code-commit'):
        parser.add_argument('--' + name, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--status', action='store_true', help='read-only per-stage status')
    parser.add_argument('--resume', action='store_true', help='reuse exactly bound stages of a marked workspace')
    parser.add_argument('--viewer', action='store_true', help='opt-in local viewer manifest (never mask qualification)')
    args = vars(parser.parse_args(argv))
    status, resume = args.pop('status'), args.pop('resume')
    try:
        if status:
            args.pop('dry_run'), args.pop('viewer')
            result = segment_status(**args)
        else:
            result = (resume_segment if resume else run_segment)(**args)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print('REFUSED: ' + str(error), file=sys.stderr)
        return 3
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
