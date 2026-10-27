"""Run pinned C3 against existing real C2 tiles, with no install or product edits.

Uses an explicitly supplied durable in-place TypeScript/MapLibre installation.
Copies only browser distribution assets, not node_modules, to a private packet.
The browser receipt reports unsupported-pixel probes; rendering is not acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
import shutil
import subprocess

import threading
from urllib.parse import urlsplit


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def c1_sources(manifest):
    from research.scripts.coast_mvp.coast_c1_preview import validate_manifest
    return [dict(id=s['id'], label=s['id'], url=s['citation'], attribution=s['attribution'],
                 license=s['rights'], datum=s['vertical_datum'] + '; ' + s['offset_note'],
                 resolutionM=s['resolution_m'], permissionRequired=True)
            for s in validate_manifest(manifest)]


def verify_c2_binding(c1, c1_sha, producer_receipt):
    if (producer_receipt.get('status') != 'machine_success_review_required'
            or producer_receipt.get('returncode') != 0):
        raise ValueError('completed review-required C2 producer receipt required')
    expected = {'manifest.json': c1_sha,
                'elevation.tif': c1['outputs']['elevation']['sha256'],
                'contributor.tif': c1['outputs']['contributor']['sha256']}
    if any(producer_receipt.get('input_sha256', {}).get(key) != value for key, value in expected.items()):
        raise ValueError('C2 producer receipt does not bind the admitted C1 inputs')


VIEWS = [
    dict(name='c3-oblique', center=[-121.08, 35.34], zoom=10.8, pitch=45, bearing=-25),
    dict(name='c3-overhead', center=[-121.08, 35.38], zoom=10.5, pitch=0, bearing=0),
    dict(name='c3-shelf-close', center=[-120.94, 35.30], zoom=12.2, pitch=50, bearing=30),
]
HTML = '''<!doctype html><html lang="en"><meta charset="utf-8">
<title>Real C2 / pinned C3 local diagnostic</title>
<link rel="stylesheet" href="vendor/maplibre-gl.css">
<style>html,body,#map{margin:0;width:100%;height:100%;font:13px system-ui;background:#12364a;color:#e4f5ef}
.coast-mvp-chrome{position:absolute;z-index:2;left:16px;top:65px;width:390px;pointer-events:none}
.coast-mvp-chrome strong,.coast-mvp-chrome details{display:block;background:#092838ee;border:1px solid #79c7b5;padding:10px;border-radius:8px;margin-bottom:7px;pointer-events:auto}
.coast-mvp-chrome details{max-height:800px;overflow:auto}.coast-mvp-chrome strong{color:#ffe09a}
.coast-mvp-chrome a,a{color:#a9e9dc}#status{position:absolute;z-index:3;bottom:10px;left:16px;right:16px;background:#092838f4;padding:12px}
header{position:absolute;top:0;left:0;right:0;padding:12px;background:#342b19;z-index:3;color:#ffe1a0}
#receipt{display:none}</style><div id="map"></div>
<header>NOT FOR NAVIGATION · REAL C2 / C3 diagnostic · review_required · unresolved datum/rights · <a href="rights.html">Full rights page</a></header>
<output id="status">Loading actual local terrain-RGB / contour MVT; C2 zoom 10 (overscaling adds no detail).</output><pre id="receipt"></pre>
<script type="importmap">{"imports":{"maplibre-gl":"./vendor/maplibre-gl.mjs"}}</script>
<script type="module">
import * as maplibregl from 'maplibre-gl';
import {CoastMvpViewer} from './compiled/coast3d/mvp.js';
maplibregl.setWorkerUrl('./vendor/maplibre-gl-worker.mjs');
const errors=[];const view=VIEW;const probes=PROBES;const status=document.querySelector('#status');
window.addEventListener('error',e=>errors.push(e.message));
try {
 const viewer=await CoastMvpViewer.load(document.querySelector('#map'),'./tiles/viewer-manifest.json');
 const map=viewer.map;window.preview=viewer;
 map.on('error',e=>errors.push(e.error.message));
 map.jumpTo(view);
 map.once('idle',()=>{
  const count=map.querySourceFeatures('mvp-contours',{sourceLayer:'contours'}).length;
  const unknown=probes.filter(p=>map.getBounds().contains(p)).map(p=>({coordinate:p,elevation:map.queryTerrainElevation(p)})).filter(p=>p.elevation!==null);
  const unsupportedRendered=unknown.some(p=>Number.isFinite(p.elevation));
  const receipt={view,actual:{center:map.getCenter(),zoom:map.getZoom(),pitch:map.getPitch(),bearing:map.getBearing()},
    decodedContourFeatures:count,centerDisplayedElevation:map.queryTerrainElevation(map.getCenter()),errors,
    transparentPixelProbes:unknown,unsupportedRendered,terrain:map.getTerrain(),sources:map.getStyle().sources};
  status.textContent=(unsupportedRendered?'SUPPORT GAP: C3 assigns terrain to transparent C2 pixels. DIAGNOSTIC ONLY; not display-accepted. ':'')+
    'Actual C2 terrain-RGB + '+count+' decoded contour features · relief ×3 · C2 z10 · no datum/rights clearance · '+view.name;
  document.querySelector('#receipt').textContent=JSON.stringify(receipt);
  document.body.dataset.ready='true';
 });
} catch(e) {errors.push(e.message);status.textContent='FAILED: '+e.message;document.body.dataset.failed='true';}
</script></html>'''


def prepare(repo, revision, c1_path, c2, c2_receipt, dependencies, output):
    import numpy as np
    import rasterio
    # This refuses the disposable workspace pattern rather than silently borrowing it.
    dependencies = dependencies.resolve()
    if any(part in ('.worktrees', 'workspaces') for part in dependencies.parts):
        raise ValueError('disposable task node_modules is not admitted')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('exact C3 head SHA required')
    if any(output.resolve().is_relative_to(root.resolve()) for root in (c1_path.parent, c2, dependencies)):
        raise ValueError('output must not write into admitted inputs or durable dependencies')
    c1 = json.loads(c1_path.read_text())
    verify_c2_binding(c1, sha(c1_path), json.loads(c2_receipt.read_text()))
    c2_manifest = json.loads((c2 / 'manifest.json').read_text())
    if c2_manifest['zoom'] != 10 or c2_manifest['tile_scheme'] != 'XYZ':
        raise ValueError('this bounded probe expects real C2 z10 XYZ')
    output.mkdir(parents=True, exist_ok=False)
    sources = output / 'source'
    (sources / 'coast3d').mkdir(parents=True)
    pins = {}
    for path in ('packages/coast/src/coast3d/mvp.ts', 'packages/coast/src/palette.ts'):
        data = subprocess.run(['git', '-C', str(repo), 'show', f'{revision}:{path}'], check=True, capture_output=True).stdout
        target = sources / path.removeprefix('packages/coast/src/')
        target.write_bytes(data)
        pins[path] = sha(target)
    compiler = dependencies / 'typescript/lib/tsc.js'
    command = ['node', str(compiler), str(sources / 'coast3d/mvp.ts'), str(sources / 'palette.ts'),
               '--ignoreConfig', '--target', 'ES2022', '--module', 'ES2022', '--noCheck', '--rewriteRelativeImportExtensions',
               '--outDir', str(output / 'compiled')]
    compiled = subprocess.run(command, capture_output=True, text=True, timeout=30)
    (output / 'compile.log').write_text(compiled.stdout + compiled.stderr)
    compiled.check_returncode()
    vendor = output / 'vendor'
    vendor.mkdir()
    vendor_hashes = {}
    distribution = dependencies / 'maplibre-gl/dist'
    for name in ('maplibre-gl.mjs', 'maplibre-gl-worker.mjs', 'maplibre-gl.css'):
        shutil.copyfile(distribution / name, vendor / name)
        vendor_hashes[name] = sha(vendor / name)
    tiles = output / 'tiles'
    tiles.mkdir()
    tile_hashes, transparent = {}, []
    terrain_files = list((c2 / 'terrain').rglob('*.png'))
    if len(terrain_files) != c2_manifest['terrain_tiles'] or not 1 <= len(terrain_files) <= 64:
        raise ValueError('C2 terrain tile count mismatch or bounded tile cap exceeded')
    for kind, suffix in (('terrain', '.png'), ('vector', '.pbf')):
        for source in sorted((c2 / kind).rglob('*' + suffix)):
            relative = source.relative_to(c2)
            target = tiles / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            tile_hashes[str(relative)] = sha(target)
            if tile_hashes[str(relative)] != sha(source):
                raise ValueError('C2 tile changed during snapshot')
            if kind == 'terrain':
                with rasterio.open(source) as image:
                    alpha = image.read(4)
                y, x = np.where(alpha == 0)
                if len(x):
                    z, tx, ty = map(int, (source.parent.parent.name, source.parent.name, source.stem))
                    # Deterministic scattered probes, retaining exact original alpha=0 support.
                    for at in np.linspace(0, len(x)-1, min(12, len(x)), dtype=int):
                        wx = (tx + (float(x[at])+.5)/alpha.shape[1]) / (2**z)
                        wy = (ty + (float(y[at])+.5)/alpha.shape[0]) / (2**z)
                        transparent.append([wx*360-180, math.degrees(math.atan(math.sinh(math.pi*(1-2*wy))))])
    adapted = dict(schemaVersion=1, region='Real Morro Bay C1 → C2; review required', synthetic=False,
                   bounds=c1['bounds_wgs84'], center=VIEWS[0]['center'], zoom=VIEWS[0]['zoom'], tileZoom=10, tileSize=256,
                   terrain=c2_manifest['terrain_template'], contours=c2_manifest['vector_template'], contourLayer='contours', sources=c1_sources(c1))
    (tiles / 'viewer-manifest.json').write_text(json.dumps(adapted, indent=2))
    from research.scripts.coast_mvp.coast_c1_preview import rights_page
    (output / 'rights.html').write_text(rights_page(c1, sha(c1_path)))
    for view in VIEWS:
        (output / f'{view["name"]}.html').write_text(HTML.replace('VIEW', json.dumps(view)).replace('PROBES', json.dumps(transparent)))
    receipt = {'status': 'review_required', 'mode': 'actual_c3_real_c2_diagnostic', 'c3_head': revision,
               'source_hashes': pins, 'compiler_command': command, 'compiler_sha256': sha(compiler),
               'durable_dependencies': str(dependencies), 'vendor_sha256': vendor_hashes,
               'c1_manifest_sha256': sha(c1_path), 'c2_manifest_sha256': sha(c2 / 'manifest.json'),
               'c2_producer_receipt_sha256': sha(c2_receipt), 'c2_limitations': c2_manifest['limitations'],
               'c2_tiles_sha256': tile_hashes, 'transparent_probe_count': len(transparent)}
    return receipt


def run_browser(output, browser, receipt):
    responses = []
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(output), **kwargs)
        def log_message(self, format, *args):
            pass
        def log_request(self, code='-', size='-'):
            responses.append({'path': self.path, 'status': code})
        def end_headers(self):
            path = Path(self.translate_path(urlsplit(self.path).path))
            if path.suffix == '.pbf' and path.is_file():
                with path.open('rb') as stream:
                    if stream.read(2) == b'\x1f\x8b':
                        self.send_header('Content-Encoding', 'gzip')
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    receipt['views'] = []
    playwright = Path(receipt['durable_dependencies']) / '@playwright/test/index.mjs'
    runner = output / 'capture-real.mjs'
    runner.write_text('''
import {writeFile} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
const [modulePath,binary,origin,out]=process.argv.slice(2);
const {chromium}=await import(pathToFileURL(modulePath).href);
const browser=await chromium.launch({executablePath:binary,headless:true,args:['--no-sandbox','--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const views=[];
try {
 const page=await browser.newPage({viewport:{width:1440,height:1100}});
 await page.route('**/*',route=>route.request().url().startsWith(origin+'/')?route.continue():route.abort());
 const pageErrors=[];page.on('pageerror',e=>pageErrors.push(e.message));
 for(const name of ['c3-oblique','c3-overhead','c3-shelf-close']) {
  await page.goto(origin+'/'+name+'.html');
  await page.waitForSelector('body[data-ready="true"]',{timeout:45000});
  const found=JSON.parse(await page.locator('#receipt').textContent());
  found.pageErrors=[...pageErrors];
  await page.screenshot({path:out+'/'+name+'.png'});
  const before=await page.locator('canvas').screenshot();
  await page.evaluate(()=>new Promise(resolve=>{const m=window.preview.map;m.once('idle',()=>resolve());m.setLayoutProperty('contours','visibility','none');}));
  const after=await page.locator('canvas').screenshot();
  found.contourPixelDifference=!before.equals(after);
  if(found.decodedContourFeatures<=0 || found.pageErrors.length || !found.contourPixelDifference)throw Error('C3 render proof failed');
  views.push(found);
 }
} finally {
 await writeFile(out+'/capture-results.json',JSON.stringify(views,null,2));
 await browser.close();
}
''')
    command = ['node', str(runner), str(playwright), str(browser),
               f'http://127.0.0.1:{server.server_port}', str(output)]
    receipt['browser_command'] = command
    receipt['browser_sandbox_disabled'] = True
    receipt['typescript_scope'] = 'emit only (--noCheck); not pnpm check or full product typecheck'
    receipt['browser_driver_sha256'] = sha(playwright)
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
        (output / 'capture-browser.log').write_text(completed.stdout + completed.stderr)
        completed.check_returncode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        results = output / 'capture-results.json'
        if results.exists():
            receipt['views'] = json.loads(results.read_text())
            for view in receipt['views']:
                view['screenshot_sha256'] = sha(output / (view['view']['name'] + '.png'))
        receipt['http_responses'] = responses
        (output / 'c3-browser-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('repo', 'c1-manifest', 'c2', 'c2-receipt', 'dependencies', 'output', 'browser'):
        parser.add_argument('--'+name, required=True, type=Path)
    parser.add_argument('--c3-head', required=True)
    args = parser.parse_args()
    receipt = prepare(args.repo, args.c3_head, args.c1_manifest, args.c2, args.c2_receipt, args.dependencies, args.output)
    result = run_browser(args.output, args.browser, receipt)
    print(json.dumps({'views': [{'view': v['view']['name'], 'features': v['decodedContourFeatures'],
                                 'unsupportedRendered': v['unsupportedRendered'], 'errors': v['errors']} for v in result['views']],
                      'http_errors': [r for r in result['http_responses'] if r['status'] != 200]}, indent=2))


if __name__ == '__main__':
    main()
