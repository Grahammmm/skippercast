// NAIP aerial source config (FE-45, docs/plans/front-end/design.md § 9, § 11):
// catalog/sources.json, packages/coast's naipSource() and the region flags
// describe one fixed USGS service with one attribution, and the platform build
// carries each region's basemap.aerial into dist/. Offline: no tile is fetched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, existsSync} from 'node:fs';
import {mapSourceHosts, naipSource} from '../packages/coast/src/map-sources.ts';

const json = path => JSON.parse(readFileSync(new URL(`../${path}`, import.meta.url), 'utf8'));
const naip = json('catalog/sources.json').sources.find(source => source.id === 'usgs-naip');
const regionIds = readdirSync(new URL('../regions/', import.meta.url), {withFileTypes: true})
  .filter(entry => entry.isDirectory() && existsSync(new URL(`../regions/${entry.name}/region.json`, import.meta.url)))
  .map(entry => entry.name);

test('the catalog NAIP host is the one packages/coast allows', () => {
  assert.ok(naip, 'catalog/sources.json has usgs-naip');
  assert.deepEqual(naip.allowed_hosts, ['imagery.nationalmap.gov']);
  assert.ok(mapSourceHosts.includes(`https://${naip.allowed_hosts[0]}`), 'catalog host is in mapSourceHosts');
  assert.equal(new URL(naip.tiles.endpoint).origin, `https://${naip.allowed_hosts[0]}`);
});

test('naipSource() requests the catalog endpoint with the catalog rendering rule and attribution', () => {
  const source = naipSource();
  assert.equal(source.tiles.length, 1);
  for (const template of source.tiles) {
    const url = new URL(template.replace('{bbox-epsg-3857}', '0,0,1,1'));
    assert.equal(`${url.origin}${url.pathname}`, naip.tiles.endpoint);
    assert.ok(mapSourceHosts.includes(url.origin));
    assert.deepEqual(JSON.parse(url.searchParams.get('renderingRule')), {rasterFunction: naip.tiles.rendering_rule});
  }
  assert.equal(source.attribution, naip.rights.attribution);
  assert.equal(naip.rights.license, 'public-domain');
  assert.equal(naip.rights.commercial_use, 'allowed');
  assert.equal(naip.rights.attribution_required, true);
});

// SC1407-07: the URL's own parameters, for the default (jpgpng) and the png32 fallback form.
const params = source => new URL(source.tiles[0].replace('{bbox-epsg-3857}', '0,0,1,1')).searchParams;

test('naipSource() asks 512 px tiles as jpgpng by default and png32 on request, every other parameter unchanged', () => {
  const mixed = naipSource(), png = naipSource('png32');
  assert.deepEqual(naipSource('jpgpng'), mixed, 'jpgpng is the default');
  for (const [source, format] of [[mixed, 'jpgpng'], [png, 'png32']]) {
    assert.equal(source.type, 'raster');
    assert.equal(source.tileSize, 512);
    assert.deepEqual([source.minzoom, source.maxzoom], [6, 18], 'one source zoom lower than the 256 px 7..19');
    assert.equal(source.tiles.length, 1);
    const p = params(source);
    assert.equal(p.get('size'), '512,512', 'the image is the tile size: no resampling');
    assert.equal(p.get('format'), format, 'never jpg alone: open water needs transparency');
    assert.equal(p.get('transparent'), 'true');
    assert.equal(p.get('f'), 'image');
    assert.deepEqual([p.get('bboxSR'), p.get('imageSR')], ['3857', '3857']);
    assert.deepEqual(JSON.parse(p.get('renderingRule')), {rasterFunction: 'NaturalColor'});
    assert.equal(source.attribution, 'USGS / USDA · NAIP aerial imagery (dated mosaic)');
    assert.ok(source.tiles[0].includes('bbox={bbox-epsg-3857}&'), 'MapLibre fills the tile box');
    assert.ok(source.tiles[0].startsWith('https://imagery.nationalmap.gov/arcgis/rest/services/USGSNAIPImagery/ImageServer/exportImage?'));
  }
  assert.equal(params(naipSource('jpg')).get('format'), 'jpgpng', 'an unknown format is never passed through');
});

/**
 * The raster tile zoom MapLibre asks for at map zoom `zoom` (maplibre-gl covering_tiles.ts coveringZoomLevel with a
 * raster source's roundZoom, then clamped to maxzoom, nothing under minzoom), and how many source pixels span the world
 * there (one tile spans 2^-tile of it in tileSize pixels): equal values are equal ground resolution.
 */
function tileAt(source, zoom) {
  const z = Math.max(0, Math.round(zoom + Math.log2(512 / source.tileSize)));
  const tile = Math.min(z, source.maxzoom);
  if (tile < source.minzoom) return null;
  return {tile, worldPixels: source.tileSize * 2 ** tile};
}

test('512 px tiles draw over the same map zooms at the same ground resolution as the 256 px source did', () => {
  const before = {tileSize: 256, minzoom: 7, maxzoom: 19}, after = naipSource();
  for (const zoom of [0, 4.9, 5, 5.49, 5.5, 5.51, 6, 6.4, 6.5, 6.99, 7, 9.25, 12, 12.5, 12.51, 14.2, 17.5, 18, 18.49, 18.5, 19, 20, 22, 24]) {
    const a = tileAt(before, zoom), b = tileAt(after, zoom);
    assert.equal(b === null, a === null, `map zoom ${zoom}: drawn by both or neither`);
    if (a) assert.equal(b.worldPixels, a.worldPixels, `map zoom ${zoom}: same source pixels across the world (old tile z ${a.tile}, new ${b.tile})`);
  }
  assert.equal(tileAt(after, 5.49), null, 'nothing below the old first drawn map zoom');
  assert.ok(tileAt(after, 5.5), 'the old first drawn map zoom still draws');
  assert.equal(tileAt(after, 24).tile, 18, 'overzoomed past the native resolution, as before');
  assert.equal(tileAt(after, 24).worldPixels, tileAt(before, 24).worldPixels);
});

test('every aerial region names usgs-naip with a dated acquisition window', () => {
  const aerial = regionIds.filter(id => json(`regions/${id}/region.json`).basemap?.aerial);
  assert.deepEqual(aerial, ['morro-bay'], 'only regions whose coverage was checked offer the aerial base');
  for (const id of aerial) {
    const {source, checked_at, acquired} = json(`regions/${id}/region.json`).basemap.aerial;
    assert.equal(source, naip.id);
    assert.ok(acquired.first <= acquired.last && acquired.last <= checked_at, id);
  }
});

test('the platform build carries basemap.aerial into each published region', () => {
  for (const id of regionIds) {
    const config = json(`regions/${id}/region.json`);
    if (config.status === 'draft') continue;
    assert.deepEqual(json(`dist/regions/${id}/region.json`).basemap, config.basemap, id);
  }
});
