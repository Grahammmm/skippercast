"""R5c: build the public mapping zone and contributor detail labels."""
from pathlib import Path
from tempfile import TemporaryDirectory

from skippercast.relief import mosaic, receipts

SCOPES = ('public',)
UPSTREAM = ('select', 'mosaic:public')
TARGET = 'layers/public/zone'
SCRIPT = 'scripts/build_survey_zone.py'
CODE_FILES = (SCRIPT, 'skippercast.relief.mosaic', 'skippercast.platform.contracts')


def add_arguments(parser):
    mosaic.add_region_config(parser)
    parser.add_argument('--coarse', type=Path, required=True, help='local EPSG:3310 coarse elevation TIFF')
    parser.add_argument('--water', type=Path, required=True, help='reviewed local WGS84 ocean-water GeoJSON')
    parser.add_argument('--coarse-source', required=True, help='public source id for the coarse elevation grid')
    parser.add_argument('--coarse-date', help='producer date for the coarse grid, if known')


def grids(ctx):
    folder = ctx.region.dir / 'mosaic/public'
    files = [mosaic.upstream_file(ctx, 'mosaic.public', folder / name)
             for name in ('elevation.tif', 'contributor.tif', 'manifest.json')]
    support = folder / 'support_class.tif'
    return files, support if mosaic.attests(ctx, 'mosaic.public', support) else None


def plan(ctx):
    files, support = grids(ctx)
    inputs = [receipts.Input(path, path.name) for path in files]
    if support:
        inputs.append(receipts.Input(support, 'support-class'))
    inputs.extend((receipts.Input(mosaic.region_config(ctx), 'region'), receipts.Input(ctx.args.coarse, 'coarse'),
                   receipts.Input(ctx.args.water, 'water'),
                   receipts.Input(mosaic.selected(ctx, 'selection.json'), 'selection'),
                   receipts.Input(mosaic.selected(ctx, 'sources.json'), 'sources')))
    return receipts.Plan(inputs, {'coarse_source': ctx.args.coarse_source, 'coarse_date': ctx.args.coarse_date})


def build(ctx, out):
    args = ctx.args
    selection = mosaic.read_json(mosaic.selected(ctx, 'selection.json'))
    if selection['region'] != ctx.region.id or selection['scope'] != 'public':
        raise receipts.ReceiptError('expected this region’s public selection')
    # DL-2 reports decisions in `files` and carries the display labels in `sources.json`.
    # MB-09 wants a public label row per contributor, not the selection's cache paths.
    included = {r['id'] for r in selection['files'] if r['decision'] == 'included' and r['rights_class'] == 'public'}
    labels = []
    for row in mosaic.sources(ctx):
        if row['id'] not in included:
            raise receipts.ReceiptError(f'no public selection decision for {row["id"]}')
        label = {k: row[k] for k in ('id', 'rights_class', 'label', 'name', 'date', 'provenance') if k in row}
        if row.get('priority_class') == 'compiled':
            label['provenance'] = 'compiled'
        labels.append(label)
    files, support = grids(ctx)
    with TemporaryDirectory(dir=out) as scratch:
        path = Path(scratch) / 'selection.json'
        path.write_bytes(receipts.canonical({'region': ctx.region.id, 'sources': labels}))
        flags = ['--region', mosaic.region_config(ctx), '--coarse', args.coarse, '--water', args.water,
                 '--mosaic', files[0].parent, '--selection', path, '--output', out,
                 '--coarse-source', args.coarse_source]
        if args.coarse_date:
            flags.extend(('--coarse-date', args.coarse_date))
        if support:
            flags.extend(('--support', support))
        mosaic.run_tool(SCRIPT, *flags)
    for filename in ('zone.geojson', 'detail.geojson'):
        if not (out / filename).is_file():
            raise receipts.ReceiptError(f'zone did not produce {filename}')
