// Seafloor habitat layer: data side. Pure and dependency-free so the map
// layer, tests and any later MapLibre port share one gate and one decoder.
//
// Contract: docs/seafloor.md "Regional publication contract (M4)". The Worker
// already refuses the archive unless the manifest is ready and unexpired; this
// module re-checks the manifest in the browser so an updating, held or stale
// publication shows as unavailable instead of a cached copy.

export const FEED_ROOT = '/feeds/tiles/seafloor/';
export const HABITAT_LABEL = 'Habitat candidate, unverified';
export const DEPTH_NOTE = 'Nominal depth; verify on your sounder.';
export const DISPLAY_NOTE = 'Display geometry only — not a navigation chart or export boundary.';

export const manifestURL = (region) => `${FEED_ROOT}manifest-${region}.json`;
export const archiveURL = (region) => `${FEED_ROOT}seafloor-${region}.pmtiles`;
export const ledgerURL = (region) => `${FEED_ROOT}regions/${region}/ledger.json`;

const REGION = /^[a-z0-9-]+$/;

/**
 * Decide whether a manifest may be shown. Returns {state, reason, manifest}:
 * state is 'ready', 'updating', 'held', 'expired' or 'unavailable'.
 */
export function manifestState(manifest, region, now = Date.now()) {
  if (!REGION.test(region || '')) return { state: 'unavailable', reason: 'No seafloor publication for this region' };
  if (!manifest || typeof manifest !== 'object') return { state: 'unavailable', reason: 'Seafloor layer unavailable' };
  if (manifest.status === 'updating') return { state: 'updating', reason: 'Seafloor layer is updating; try again shortly' };
  if (manifest.status === 'held') return { state: 'held', reason: 'Seafloor habitat is held for screening review' };
  if (manifest.status !== 'ready') return { state: 'unavailable', reason: 'Seafloor layer unavailable' };
  if (manifest.region !== region) return { state: 'unavailable', reason: 'Seafloor publication is for another region' };
  if (!/^[a-f0-9]{64}$/.test(manifest.archive_sha256 || '')) return { state: 'unavailable', reason: 'Seafloor publication is incomplete' };
  const expires = Date.parse(manifest.expires_at);
  if (!Number.isFinite(expires) || expires <= now) return { state: 'expired', reason: 'Seafloor screening has expired and is being refreshed' };
  return { state: 'ready', reason: '', manifest, expires };
}

/** Fetch and gate the manifest; never throws, never uses a cached copy. */
export async function loadManifest(region, fetchImpl = globalThis.fetch, now = Date.now()) {
  if (!REGION.test(region || '')) return manifestState(null, region, now);
  try {
    const response = await fetchImpl(manifestURL(region), { cache: 'no-store' });
    if (response.status === 503) {
      const body = await response.json().catch(() => null);
      return manifestState(body || { status: 'updating' }, region, now);
    }
    if (!response.ok) return manifestState(null, region, now);
    return manifestState(await response.json(), region, now);
  } catch {
    return manifestState(null, region, now);
  }
}

// ---- Mapbox Vector Tile (MVT 2.1) decoding -------------------------------
// Only what the seafloor archive needs: layers, string/number/bool values and
// polygon geometry. https://github.com/mapbox/vector-tile-spec/tree/master/2.1

class Reader {
  constructor(bytes, start = 0, end = bytes.length) { this.b = bytes; this.pos = start; this.end = end; }
  varint() {
    let result = 0, shift = 0, byte;
    do {
      byte = this.b[this.pos++];
      result += (byte & 0x7f) * 2 ** shift;
      shift += 7;
    } while (byte & 0x80);
    return result;
  }
  svarint() { const n = this.varint(); return n % 2 ? -(n + 1) / 2 : n / 2; }
  bytes() { const len = this.varint(), start = this.pos; this.pos += len; return [start, this.pos]; }
  string() { const [s, e] = this.bytes(); return new TextDecoder().decode(this.b.subarray(s, e)); }
  skip(type) {
    if (type === 0) this.varint();
    else if (type === 1) this.pos += 8;
    else if (type === 2) this.pos = this.bytes()[1];
    else if (type === 5) this.pos += 4;
    else throw new Error('Unsupported protobuf wire type ' + type);
  }
  fields(fn) {
    while (this.pos < this.end) {
      const tag = this.varint();
      fn(tag >> 3, tag & 7);
    }
  }
}

function readValue(r) {
  let value = null;
  const [s, e] = r.bytes();
  const v = new Reader(r.b, s, e);
  const view = new DataView(r.b.buffer, r.b.byteOffset);
  v.fields((field, type) => {
    if (field === 1) value = v.string();
    else if (field === 2) { value = view.getFloat32(v.pos, true); v.pos += 4; }
    else if (field === 3) { value = view.getFloat64(v.pos, true); v.pos += 8; }
    else if (field === 4 || field === 5) value = v.varint();
    else if (field === 6) value = v.svarint();
    else if (field === 7) value = Boolean(v.varint());
    else v.skip(type);
  });
  return value;
}

function packed(r) {
  const [s, e] = r.bytes(), out = [], p = new Reader(r.b, s, e);
  while (p.pos < e) out.push(p.varint());
  return out;
}

/** Decode tile bytes into {layerName: {extent, features: [{type, tags, geometry}]}}. */
export function decodeTile(bytes) {
  const buf = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const tile = new Reader(buf), layers = {};
  tile.fields((field, type) => {
    if (field !== 3) return tile.skip(type);
    const [s, e] = tile.bytes(), r = new Reader(buf, s, e);
    const layer = { name: '', extent: 4096, keys: [], values: [], raw: [] };
    r.fields((f, t) => {
      if (f === 1) layer.name = r.string();
      else if (f === 2) { const [fs, fe] = r.bytes(); layer.raw.push([fs, fe]); }
      else if (f === 3) layer.keys.push(r.string());
      else if (f === 4) layer.values.push(readValue(r));
      else if (f === 5) layer.extent = r.varint();
      else r.skip(t);
    });
    layer.features = layer.raw.map(([fs, fe]) => {
      const fr = new Reader(buf, fs, fe), feature = { type: 0, tags: [], geometry: [] };
      fr.fields((f, t) => {
        if (f === 2) feature.tags = packed(fr);
        else if (f === 3) feature.type = fr.varint();
        else if (f === 4) feature.geometry = packed(fr);
        else fr.skip(t);
      });
      const properties = {};
      for (let i = 0; i + 1 < feature.tags.length; i += 2) properties[layer.keys[feature.tags[i]]] = layer.values[feature.tags[i + 1]];
      return { type: feature.type, properties, commands: feature.geometry };
    });
    delete layer.raw;
    layers[layer.name] = layer;
  });
  return layers;
}

/** Tile-space rings from MVT geometry commands. */
export function decodeRings(commands) {
  const rings = [];
  let x = 0, y = 0, ring = null;
  for (let i = 0; i < commands.length;) {
    const id = commands[i] & 7, count = commands[i] >> 3;
    i++;
    if (id === 7) { if (ring?.length) { ring.push([...ring[0]]); rings.push(ring); } ring = null; continue; }
    for (let k = 0; k < count; k++) {
      const dx = commands[i++], dy = commands[i++];
      x += (dx >> 1) ^ -(dx & 1);
      y += (dy >> 1) ^ -(dy & 1);
      if (id === 1) { if (ring?.length) rings.push(ring); ring = [[x, y]]; }
      else if (id === 2 && ring) ring.push([x, y]);
    }
  }
  if (ring?.length) rings.push(ring);
  return rings;
}

const signedArea = (ring) => {
  let sum = 0;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) sum += (ring[j][0] - ring[i][0]) * (ring[i][1] + ring[j][1]);
  return sum;
};

/** Group rings into polygons: each ring with the first ring's winding starts a new polygon. */
export function classifyRings(rings) {
  const polygons = [];
  let outer;
  for (const ring of rings) {
    const area = signedArea(ring);
    if (!area) continue;
    if (outer === undefined) outer = area < 0;
    if ((area < 0) === outer) polygons.push([ring]);
    else if (polygons.length) polygons.at(-1).push(ring);
  }
  return polygons;
}

/** Web-Mercator tile pixel to [lng, lat]. */
export function toLngLat(z, tx, ty, extent, [px, py]) {
  const n = 2 ** z;
  const lng = ((tx + px / extent) / n) * 360 - 180;
  const merc = Math.PI * (1 - (2 * (ty + py / extent)) / n);
  const lat = (Math.atan(Math.sinh(merc)) * 180) / Math.PI;
  return [Math.round(lng * 1e7) / 1e7, Math.round(lat * 1e7) / 1e7];
}

/** GeoJSON features for one layer of one decoded tile (polygons only). */
export function tileFeatures(decoded, layerName, z, x, y) {
  const layer = decoded[layerName];
  if (!layer) return [];
  return layer.features.filter((f) => f.type === 3).map((f) => ({
    type: 'Feature',
    properties: f.properties,
    geometry: {
      type: 'MultiPolygon',
      coordinates: classifyRings(decodeRings(f.commands)).map((poly) => poly.map((ring) => ring.map((p) => toLngLat(z, x, y, layer.extent, p)))),
    },
  })).filter((f) => f.geometry.coordinates.length);
}

/**
 * Merge features split across tiles by their stable `id`: one feature per id,
 * its polygon parts combined, properties from the first part seen.
 * Features without an id are dropped rather than shown twice.
 */
export function dedupeById(features) {
  const byId = new Map();
  for (const f of features) {
    const id = f?.properties?.id;
    if (typeof id !== 'string' || !id) continue;
    const seen = byId.get(id);
    if (!seen) byId.set(id, { type: 'Feature', properties: f.properties, geometry: { type: 'MultiPolygon', coordinates: [...f.geometry.coordinates] } });
    else seen.geometry.coordinates.push(...f.geometry.coordinates);
  }
  return [...byId.values()];
}

/** Tiles at zoom z covering a [west, south, east, north] box. */
export function tilesForBounds([west, south, east, north], z) {
  const n = 2 ** z;
  const tx = (lng) => Math.min(n - 1, Math.max(0, Math.floor(((lng + 180) / 360) * n)));
  const ty = (lat) => {
    const r = (Math.max(-85, Math.min(85, lat)) * Math.PI) / 180;
    return Math.min(n - 1, Math.max(0, Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * n)));
  };
  const out = [];
  for (let x = tx(west); x <= tx(east); x++) for (let y = ty(north); y <= ty(south); y++) out.push([z, x, y]);
  return out;
}

// ---- Styling and provenance ------------------------------------------------

export const GRADE_STYLE = {
  A: { color: '#7a3e9d', label: 'A · most rugged terrain' },
  B: { color: '#b0607f', label: 'B · moderately rugged' },
  C: { color: '#d59a6a', label: 'C · some relief' },
};
export const FIT_STYLE = {
  3: { color: '#1f6f8b', label: '3 · strongest physical fit' },
  2: { color: '#4f9fbf', label: '2 · moderate physical fit' },
  1: { color: '#9cc9dd', label: '1 · weak physical fit' },
};
export const UNKNOWN_COLOR = '#8a949b';

/** Fill colour for a habitat feature under the chosen view ('terrain' or a fit_* key). */
export function habitatColor(properties, view = 'terrain') {
  if (view === 'terrain') return GRADE_STYLE[properties?.terrain_grade]?.color || UNKNOWN_COLOR;
  return FIT_STYLE[properties?.[view]]?.color || UNKNOWN_COLOR;
}

const parse = (value) => {
  if (typeof value !== 'string') return value ?? null;
  try { return JSON.parse(value); } catch { return value; }
};
const feet = (n) => (Number.isFinite(n) ? Math.round(n) : null);

/**
 * Plain-language details for one selected habitat feature. Nested evidence is
 * parsed here, only for the selected feature. Unknown values stay unknown.
 */
export function habitatDetails(properties = {}) {
  const sources = parse(properties.source_ids);
  const screen = parse(properties.screen);
  const substrate = parse(properties.substrate);
  const lo = feet(properties.depth_min_ft), hi = feet(properties.depth_max_ft);
  const fits = Object.keys(properties).filter((k) => k.startsWith('fit_')).sort().map((k) => ({
    key: k,
    name: k.slice(4).replace(/_/g, ' '),
    value: [1, 2, 3].includes(properties[k]) ? properties[k] : 'unknown',
  }));
  return {
    title: HABITAT_LABEL,
    depth: lo !== null && hi !== null ? `${lo}–${hi} ft nominal` : 'Depth unknown',
    depthNote: DEPTH_NOTE,
    grade: GRADE_STYLE[properties.terrain_grade] ? properties.terrain_grade : 'unknown',
    fits,
    source: {
      ids: Array.isArray(sources) ? sources : sources ? [String(sources)] : [],
      year: Number.isFinite(properties.source_year) ? properties.source_year : 'unknown',
      resolution: Number.isFinite(properties.resolution_m) ? `${properties.resolution_m} m` : 'unknown',
      datum: typeof properties.vertical_datum === 'string' && properties.vertical_datum ? properties.vertical_datum : 'unknown',
    },
    substrate: substrate && typeof substrate === 'object' ? {
      sameSurvey: substrate.same_survey_as_depth ?? 'unknown',
      independent: substrate.independent_confirmation === true,
    } : null,
    screened: screen && typeof screen === 'object' ? screen.status === 'pass' : false,
    notice: typeof properties.planning_notice === 'string' ? properties.planning_notice : 'Planning only. Not a navigation chart. Check current CDFW regulations.',
    displayNote: DISPLAY_NOTE,
  };
}
