"""R7a: capture the fixed MB-08 Chart screenshots of one package, under a receipt.

    region.py shots --region <id> --out <OUT> --basemap <basemap.pmtiles> [--lon X --lat Y]

Runs scripts/relief/qa_shots.mjs on the current package's release.json. The receipt (inputs: the
release bytes and the basemap; upstream: package) is what lets `region.py qa` trust the pack: QA
accepts only a shots.json and PNGs that this stage recorded for the exact release it measures.
"""
from pathlib import Path
import subprocess

from skippercast.paths import repo_root
from skippercast.relief import package, receipts

UPSTREAM = ('package',)
SCRIPT = 'scripts/relief/qa_shots.mjs'
CODE_FILES = (SCRIPT,)
TARGET = 'shots/{generation}'


def add_arguments(parser):
    parser.add_argument('--basemap', type=Path, required=True, help='local basemap PMTiles for the chart context')
    parser.add_argument('--lon', type=float, help='fixed camera longitude (default: release centre)')
    parser.add_argument('--lat', type=float, help='fixed camera latitude (default: release centre)')


def release_path(ctx):
    """The release.json that the current package receipt attests."""
    package_receipt = ctx.upstream['package']
    relative = f'release/{package_receipt["generation"]}/release.json'
    if not any(row['path'] == relative for row in package_receipt['outputs']):
        raise receipts.ReceiptError('the package receipt does not attest its release.json')
    return package.artifact_path(ctx.region.dir, relative)


def camera(ctx):
    lon, lat = ctx.args.lon, ctx.args.lat
    if (lon is None) != (lat is None):
        raise receipts.ReceiptError('--lon and --lat go together')
    return [] if lon is None else [lon, lat]


def plan(ctx):
    return receipts.Plan([receipts.Input(release_path(ctx), 'release'), receipts.Input(ctx.args.basemap, 'basemap')],
                         {'camera': camera(ctx)})


def capture(command, **kwargs):
    """The one place a browser is launched; tests replace it."""
    return subprocess.run(command, check=True, **kwargs)


def build(ctx, out):
    release = release_path(ctx)
    out.rmdir()  # qa_shots.mjs requires a nonexistent destination; this is the receipt's empty temp dir.
    capture(['node', str(repo_root() / SCRIPT), str(release), str(ctx.args.basemap), str(out), *map(str, camera(ctx))],
            cwd=repo_root())
    if not (out / 'shots.json').is_file():
        raise receipts.ReceiptError('capture did not produce shots.json')
