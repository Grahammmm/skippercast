"""R5a: build the public Deep relief archive and coverage sidecar."""
from skippercast.relief import mosaic, receipts

SCOPES = ('public',)
UPSTREAM = ('select', 'mosaic:public')
# Give each layer its own atomic target so a rebuild never replaces sibling layers.
TARGET = 'layers/public/tiles'
SCRIPT = 'scripts/build_bathy_tiles.py'
CODE_FILES = (SCRIPT, 'skippercast.relief.mosaic', 'skippercast.relief.pmtiles_v3')  # the script writes the archive with pmtiles_v3
VARIANT = 'medium'  # MB-01's fixed Deep ramp with medium relief


def elevation(ctx):
    return mosaic.upstream_file(ctx, 'mosaic.public', ctx.region.dir / 'mosaic/public/elevation.tif')


add_arguments = mosaic.add_region_config


def plan(ctx):
    native = mosaic.selected(ctx, 'native.json')
    inputs = [receipts.Input(mosaic.region_config(ctx), 'region'), receipts.Input(elevation(ctx), 'elevation'),
              receipts.Input(native, 'native')]
    inputs.extend(item for item, _ in mosaic.raster_refs(native, mosaic.read_json(native)))
    return receipts.Plan(inputs, {'ramp': 'deep-fixed-v1', 'variant': VARIANT})


def build(ctx, out):
    region = mosaic.read_json(mosaic.region_config(ctx))
    if region['id'] != ctx.region.id:
        raise receipts.ReceiptError('region config id differs from the requested region')
    native = mosaic.selected(ctx, 'native.json')
    rows = mosaic.read_json(native)
    mosaic.verify_rasters(mosaic.raster_refs(native, rows))
    help_text = mosaic.run_tool(SCRIPT, '--help', capture_output=True, text=True).stdout
    clip = '--clip-bounds' in help_text
    args = ['--source', elevation(ctx), '--output', out / 'relief.pmtiles', '--coverage-json', out / 'coverage.json',
            '--label', ctx.region.id, '--variant', VARIANT]
    if rows:  # The legacy reader rejects an empty list; the mosaic can supply background on its own.
        args.extend(('--native-manifest', native))
    if clip:
        args.extend(('--clip-bounds', *region['bounds']))
    else:
        # Before DL-3 the builder has no per-cell certification gate. Never request z16+ on it.
        args.extend(('--maxzoom', 15))
    mosaic.run_tool(SCRIPT, *args, cwd=native.parent)
    for filename in ('relief.pmtiles', 'coverage.json'):
        if not (out / filename).is_file():
            raise receipts.ReceiptError(f'tiles did not produce {filename}')
    return {'clip_bounds': region['bounds'] if clip else None,
            'clip_status': 'applied' if clip else 'builder has no --clip-bounds; capped at z15'}
