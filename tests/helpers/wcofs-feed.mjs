// A synthetic regional WCOFS layer in the pipeline's shape (src/skippercast/pipeline/habitat_dynamics.py
// `wcofs_surface`): a manifest naming its region and two SHA-256-pinned tiles, served by a fake fetch that
// records every URL. Nothing here is model data.
import {createHash} from 'node:crypto';

export const FIELDS = ['latitude', 'longitude', 'temperature_c', 'u_mps', 'v_mps', 'temperature_gradient_c_per_km'];
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

/**
 * `times` are epoch seconds; `grid` gives each tile's cell centres as [lat, lon]; `flow(lat, lon, time)` gives
 * [u, v] in m/s or null for a dry cell. `tile` and `record` let a test break one tile.
 */
export function wcofsFeed({region, times, grids, flow, status = 'ok', issuedAt, retrievedAt, maxAge = 36, tile = t => t, record = r => r}) {
  const tiles = grids.map(({bounds, cells}, k) => {
    const body = tile({schema_version: 1, region_id: region, layer_id: 'wcofs-surface-forecast', bounds, resolution_degrees: [0.04, 0.04], fields: FIELDS,
      frames: times.map(time => ({time, cells: cells.map(([lat, lon]) => { const uv = flow(lat, lon, time); return [lat, lon, 12.5, uv?.[0] ?? null, uv?.[1] ?? null, null]; })}))}, k);
    const bytes = Buffer.from(JSON.stringify(body));
    return {bytes, record: record({path: `habitat-tiles/wcofs-surface-forecast-${k}-0-${sha(bytes).slice(0, 16)}.json`, bounds, sha256: sha(bytes), bytes: bytes.length}, k)};
  });
  const manifest = {schema_version: 1, region_id: region,
    layers: {'wcofs-surface-forecast': {id: 'wcofs-surface-forecast', kind: 'forecast', issued_at: issuedAt, resolution_degrees: [0.04, 0.04], horizontal_datum: 'NAD83',
      vertical_layer: 'surface 0 m', surface_only: true, fields: FIELDS, status, max_age_hours: maxAge, native_stride: 1, source_id: 'noaa-wcofs',
      limitations: 'Synthetic test forecast.', frames: times.map(time => ({time, valid_cells: 1, total_cells: 1})), tiles: tiles.map(t => t.record)}},
    sources: {'wcofs-surface-forecast': {id: 'wcofs-surface-forecast', name: 'NOAA West Coast Operational Forecast System', kind: 'forecast',
      url: 'https://tidesandcurrents.noaa.gov/ofs/wcofs/wcofs_info.html', max_age_hours: maxAge, status, data_retrieved_at: retrievedAt}}};
  return {manifest, tiles};
}

/** A fetch serving `feed` for `region` under `page`'s origin. */
export function feedServer({manifest, tiles}, {page, region, manifestStatus = 200}) {
  const base = new URL(`/feeds/conditions/regions/${region}/`, page).href, asked = [];
  const fetchFn = async url => {
    asked.push(url);
    if (url === `${base}habitat-dynamics.json`) return manifestStatus === 200 ? Response.json(manifest) : new Response('Not found', {status: manifestStatus});
    const t = tiles.find(t => url === base + t.record.path);
    return t ? new Response(t.bytes) : new Response('Not found', {status: 404});
  };
  return {fetchFn, asked};
}
