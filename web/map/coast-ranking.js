// Where to look consumes the same hash-verified, screened SkipperCast release
// as the planner. No Fish bridge or renderer import. The normal brief still
// loads only its region's slim file, after first paint / Save-Data consent.
import {loadManifest} from '../../dist/seafloor-data.js';
import {loadReefTrip, loadReefTripBrief} from '../../dist/reef-trip-data.js';

export const HABITAT_REGIONS = Object.freeze(['morro-bay', 'cambria-san-simeon', 'monterey-point-sur', 'point-arguello-conception']);

/** All four controls must be ready; no partial coast-wide release or stale cache. */
export async function habitatGate(fetchImpl = globalThis.fetch, now = Date.now()) {
  const gates = await Promise.all(HABITAT_REGIONS.map(region => loadManifest(region, fetchImpl, now)));
  if (gates.some(g => g.state !== 'ready')) throw Error('Reviewed habitat unavailable');
  return {expiresAt: Math.min(...gates.map(g => g.expires)), manifests: gates.map(g => g.manifest)};
}

/** Adapt already verified canonical targets, retaining credits and the slim verdict binding. */
const adapted = new WeakMap();
export function habitatFeatures(loaded) {
  if (adapted.has(loaded)) return adapted.get(loaded);
  const areas = new Map(loaded.areas.map(a => [a.id, a.geometry]));
  const features = loaded.targets.map(t => {
    const geometry = areas.get(t.id);
    const p = {id: t.id, region: loaded.publication.region, exportable: true, screen_status: 'pass',
      screen_expires_at: loaded.publication.expires_at,
      waypoint_latitude: t.latitude, waypoint_longitude: t.longitude,
      depth_min_ft: t.neighborhood_depth_ft?.[0], depth_max_ft: t.neighborhood_depth_ft?.[1],
      terrain_score: t.habitat_score, terrain_grade: t.habitat_grade,
      source_rights: t.source_rights, protected_place: t.protected_place,
      protected_fingerprint: loaded.protected_fingerprint, slim: loaded.slim === true};
    for (const [group, fit] of Object.entries(t.species_fit ?? {})) p['fit_' + group.replaceAll('-', '_')] = fit;
    return {type: 'Feature', id: t.id, geometry: geometry ?? {type: 'Point', coordinates: [t.longitude, t.latitude]}, properties: p};
  });
  adapted.set(loaded, features);
  return features;
}

/** One region's existing bounded/hash-verified loader, with a coast-wide control gate. */
export async function loadHabitatPublication(region, {full = false, ...options} = {}) {
  if (!HABITAT_REGIONS.includes(region)) return (full ? loadReefTrip : loadReefTripBrief)(region, options);
  const before = await habitatGate(options.fetchImpl, options.now);
  const loaded = await (full ? loadReefTrip : loadReefTripBrief)(region, options);
  const after = await habitatGate(options.fetchImpl);
  // A held region or replacement of this region during the transfer invalidates the load.
  const live = after.manifests.find(m => m.region === region);
  if (live.export_sha256 !== loaded.publication.export_sha256) throw Error('Reviewed habitat changed while loading');
  return {...loaded, habitatExpiresAt: Math.min(before.expiresAt, after.expiresAt)};
}

/** Legacy coast-wide consumer, now backed only by SkipperCast's verified exports. */
export async function loadReviewedHabitat() {
  const loaded = await Promise.all(HABITAT_REGIONS.map(region => loadHabitatPublication(region)));
  return {features: loaded.flatMap(habitatFeatures), expiresAt: Math.min(...loaded.map(l => l.habitatExpiresAt))};
}

/** Same fit/terrain ordering as before, without importing the terrain renderer. */
export function rankedHabitat(features, field, now = Date.now()) {
  return features.filter(f => f?.properties?.exportable === true && f.properties.screen_status === 'pass'
    && Date.parse(f.properties.screen_expires_at) > now && (!field || f.properties[field] >= 2)
    && (['Polygon', 'MultiPolygon'].includes(f.geometry?.type) || f.properties.slim === true))
    .sort((a, b) => (field ? b.properties[field] - a.properties[field] : 0)
      || b.properties.terrain_score - a.properties.terrain_score || String(a.id ?? a.properties.id).localeCompare(String(b.id ?? b.properties.id)));
}
