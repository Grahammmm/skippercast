"""R4: build the selected public mosaic with the offline coast mosaic tool."""
import json
from pathlib import Path
import subprocess
import sys

from skippercast.paths import repo_root
from skippercast.relief import receipts

SCOPES = ('public',)
UPSTREAM = ('select',)
SCRIPT = 'research/scripts/coast_mvp/coast_mosaic.py'
CODE_FILES = (SCRIPT,)
RESERVE_GIB = 250


def add_region_config(parser):
    parser.add_argument('--region-config', type=Path, help='defaults to regions/<id>/region.json')


add_arguments = add_region_config


def region_config(ctx):
    return ctx.args.region_config or repo_root() / 'regions' / ctx.region.id / 'region.json'


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def attests(ctx, key, path):
    """Use only files bound by a verified upstream receipt, not leftovers on disk."""
    recorded = ctx.region.record(path)
    return any(row['path'] == recorded for row in ctx.upstream[key]['outputs'])


def upstream_file(ctx, key, path):
    if not attests(ctx, key, path):
        raise receipts.ReceiptError(f'{key} does not attest {path.name}')
    return path


def selected(ctx, filename):
    return upstream_file(ctx, 'select', ctx.region.dir / 'select' / filename)


def sources(ctx):
    doc = read_json(selected(ctx, 'sources.json'))
    if doc['scope'] != 'public' or any(row['rights_class'] != 'public' for row in doc['sources']):
        raise receipts.ReceiptError('expected the public selection')
    return doc['sources']


def raster_refs(manifest, rows):
    """Input raster references in the selector's mosaic and native manifests."""
    for row in rows:
        if row['rights_class'] != 'public':
            raise receipts.ReceiptError('non-public entry in a public stage')
        for field, pin, role in (('path', 'sha256', 'grid'), ('support_path', 'support_sha256', 'support')):
            value = row.get(field)
            if value is None and field == 'support_path':
                continue
            if not isinstance(value, str) or '://' in value or value.startswith('/vsi'):
                raise receipts.ReceiptError('expected a local raster reference')
            yield receipts.Input(manifest.parent / Path(value).expanduser(), f'{role}:{row["id"]}'), row[pin]


def verify_rasters(refs):
    for item, pin in refs:
        if receipts.sha256_file(item.path) != pin:
            raise receipts.ReceiptError(f'selected raster hash changed: {item.role}')


def run_tool(script, *args, **kwargs):
    return subprocess.run([sys.executable, str(repo_root() / script), *map(str, args)], check=True, **kwargs)


def plan(ctx):
    table = selected(ctx, 'sources.json')
    inputs = [receipts.Input(region_config(ctx), 'region'), receipts.Input(table, 'sources')]
    inputs.extend(item for item, _ in raster_refs(table, sources(ctx)))
    return receipts.Plan(inputs, {'cell_m': 10, 'crs': 'EPSG:3310', 'reserve_gib': RESERVE_GIB})


def build(ctx, out):
    config = region_config(ctx).resolve()
    if read_json(config)['id'] != ctx.region.id:
        raise receipts.ReceiptError('region config id differs from the requested region')
    table = selected(ctx, 'sources.json')
    rows = sources(ctx)
    if not rows:
        raise receipts.Held('selection contains no public mosaic sources')
    # The mosaic tool checks the elevation pins itself. Bind any support pins too.
    verify_rasters((item, pin) for item, pin in raster_refs(table, rows) if item.role.startswith('support:'))
    out.rmdir()  # coast_mosaic requires a nonexistent destination; this is the receipt's empty temp dir.
    run_tool(SCRIPT, '--region', config, '--sources', table, '--output', out, '--reserve-gib', RESERVE_GIB)
    path = out / 'manifest.json'
    manifest = read_json(path)
    for row in manifest['sources']:
        # The tool records input locations for research; the stage manifest keeps provenance, not host paths.
        row.pop('path', None)
        row.pop('support_path', None)
    path.write_bytes(receipts.canonical(manifest) + b'\n')
    for filename in ('elevation.tif', 'contributor.tif', 'support_count.tif'):
        if not (out / filename).is_file():
            raise receipts.ReceiptError(f'mosaic did not produce {filename}')
