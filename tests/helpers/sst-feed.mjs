// A synthetic regional SST analysis in the pipeline's shape (src/skippercast/pipeline/habitat_dynamics.py
// `sst_analysis`): a manifest naming its region and two SHA-256-pinned tiles of a drawable 6×4 grid.
// Nothing here is satellite data.
import {createHash} from 'node:crypto';

export const SST_FIELDS = ['latitude', 'longitude', 'temperature_c', 'analysis_error_c', 'temperature_gradient_c_per_km', 'thermal_contrast_supported'];
const sha = bytes => createHash('sha256').update(bytes).digest('hex');

/**
 * A 6×4 grid of 0.05° cells split into two tiles; (0, 0) is land (no temperature) and (1, 0) has no error. The one frame is
 * at `sampleAt`, so two feeds with different sample times have different tile bytes and paths. `tile` and `record` let a
 * test break one tile.
 */
export function sstFeed({region, status = 'ok', sampleAt = '2026-10-15T12:00:00Z', retrievedAt = '2026-10-16T06:00:00Z', maxAge = 72, tile = t => t, record = r => r}) {
  const time = Date.parse(sampleAt) / 1000;
  const tiles = [[-121.0, 35.0, -120.85, 35.2], [-120.85, 35.0, -120.7, 35.2]].map((bounds, k) => {
    const cells = [];
    for (let j = 0; j < 4; j++) for (let i = 0; i < 3; i++) {
      const lat = +(35.025 + j * 0.05).toFixed(3), lon = +(bounds[0] + 0.025 + i * 0.05).toFixed(3);
      const temp = k === 0 && i === 0 && j === 0 ? null : 14 + i * 0.2 + k * 0.6 + j * 0.1;
      cells.push([lat, lon, temp, k === 0 && i === 1 && j === 0 ? null : 0.3, null, null]);
    }
    const body = tile({schema_version: 1, region_id: region, layer_id: 'sst-analysis', bounds, resolution_degrees: [0.05, 0.05], fields: SST_FIELDS,
      frames: [{time, cells}]}, k);
    const bytes = Buffer.from(JSON.stringify(body));
    const path = `habitat-tiles/sst-analysis-${k}-0-${sha(bytes).slice(0, 16)}.json`;
    return {bytes, record: record({path, bounds, sha256: sha(bytes), bytes: bytes.length}, k)};
  });
  const manifest = {schema_version: 1, region_id: region,
    layers: {'sst-analysis': {id: 'sst-analysis', kind: 'analysis', sample_at: sampleAt, resolution_degrees: [0.05, 0.05], fields: SST_FIELDS, status, max_age_hours: maxAge,
      native_stride: 1, source_id: 'noaa-blended-sst', frames: [{time, valid_cells: 22, total_cells: 24}], tiles: tiles.map(t => t.record)}},
    sources: {'sst-analysis': {id: 'sst-analysis', name: 'NOAA Geo-Polar Blended night SST, 5 km', kind: 'analysis',
      url: 'https://coastwatch.noaa.gov/cwn/products/noaa-geo-polar-blended-global-sea-surface-temperature-analysis-level-4.html',
      max_age_hours: maxAge, status, data_retrieved_at: retrievedAt}}};
  return {manifest, tiles};
}
