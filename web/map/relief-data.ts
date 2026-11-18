// FE10: pure selection from the deployed, reviewed catalog/relief/<region>.json.
// The pointer is the trust anchor, not PMTiles headers or embedded metadata.
// Selection does not authenticate object bytes. E2E-17 verifies tiles using
// digest_root_sha256 from this result before a renderer can use them.
export type ReliefTier = '1m' | '2m' | '5m' | 'estimated' | 'none';
type ReliefBounds = readonly [west: number, south: number, east: number, north: number];
type ReliefIdentity = Readonly<{sha256: string; bytes: number; digest_root_sha256: string}>;
type ReliefSource = Readonly<{
  id: string; attribution: string; survey_dates: readonly string[]; release_date?: string;
  vertical_datum: string; label: string; estimated: boolean; public_display: 'allowed'; terms_url?: string;
}>;
type DepthBand = Readonly<{
  source_id: string; min_depth_m: number; max_depth_m: number; resolution_m: number;
  tier: Exclude<ReliefTier, 'none'>;
}>;
type ReliefArchive = ReliefIdentity & Readonly<{
  region: string; object_key: string; minzoom: number; maxzoom: number; bounds: ReliefBounds;
  release_sha256: string; envelope_sha256: string; private: false;
  sources: readonly ReliefSource[]; mask: 'transparent-nodata'; depth_bands: readonly DepthBand[];
  // Availability summary, not a map of pixels. Use surveyed footprints for spatial claims.
  native_support_by_zoom: Readonly<Partial<Record<number, readonly ReliefTier[]>>>;
}>;

type Refusal = 'missing' | 'wrong-region' | 'unreviewed' | 'private' | 'identity' | 'metadata' | 'unknown-resolution';
type Resolution = {status: 'ready'; archive: ReliefArchive} | {status: 'unavailable'; reason: Refusal};

const SHA256 = /^[a-f0-9]{64}$/;
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
// Rights basis (DATA-LIVE-9): G decision 2026-11-18 put all map data live, including CSUMB/SFML lineage
// and sources with unconfirmed terms (owner-accepted risk; revisit when paid). Lineage names and an
// unresolved licence are therefore not refusals. MBARI stays excluded until G answers DATA-LIVE-PLAN
// §5 #2. Integrity checks below are unchanged.
const EXCLUDED_MBARI = /\bmbari\b|monterey bay aquarium research institute/i;
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === 'object' && !Array.isArray(v);
const text = (v: unknown): v is string => typeof v === 'string' && v.trim().length > 0;
const hash = (v: unknown): v is string => typeof v === 'string' && SHA256.test(v);
const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const metres = (v: unknown): v is number => finite(v) && v > 0;
const count = (v: unknown): v is number => finite(v) && Number.isSafeInteger(v) && v >= 0;
const refused = (reason: Refusal): Resolution => ({status: 'unavailable', reason});

function publicSource(row: unknown): row is Record<string, unknown> & {rights: Record<string, unknown>} {
  // Raw-file redistribution (publication_allowed, redistribution_reviewed, review_status) is a separate
  // decision that stays off; it does not govern showing derived depth shading.
  return record(row) && row.rights_class === 'public' && record(row.rights) && row.rights.public_display === 'allowed' &&
    row.private !== true &&
    ![row.id, row.provider, row.attribution, row.source_url, row.rights.attribution, row.rights.terms_url]
      .some(v => text(v) && EXCLUDED_MBARI.test(v));
}

function publicSources(pointer: Record<string, unknown>) {
  const rows = pointer.sources;
  return pointer.private === false && Array.isArray(rows) && rows.length && rows.every(publicSource) ? rows : undefined;
}

function boundsOf(value: unknown): ReliefBounds | undefined {
  if (!Array.isArray(value) || value.length !== 4) return;
  const [w, s, e, n] = value;
  if (finite(w) && finite(s) && finite(e) && finite(n) && w >= -180 && e <= 180 && w < e && s >= -90 && n <= 90 && s < n) {
    return [w, s, e, n];
  }
}

function measuredTier(resolution: number) {
  return resolution <= 1 ? '1m' : resolution <= 2 ? '2m' : resolution <= 5 ? '5m' : 'estimated';
}

function depthBands(summary: Record<string, unknown>, sources: ReadonlyMap<string, ReliefSource>): DepthBand[] | undefined {
  if (!Array.isArray(summary.depth_bands) || !summary.depth_bands.length) return;
  const bands: DepthBand[] = [];
  for (const band of summary.depth_bands) {
    if (!record(band)) return;
    const {source_id, min_depth_m: min, max_depth_m: max, resolution_m: resolution, support_class: support} = band;
    const source = typeof source_id === 'string' ? sources.get(source_id) : undefined;
    if (!source || !finite(min) || !finite(max) || min < 0 || max <= min || !metres(resolution)) return;
    // Do not promote a source label to evidence. Split bands crossing 20 m
    // at the producer if a separate, certified deep tier can be reported.
    const tier = support === 3 && !source.estimated && (resolution <= 1 || min >= 20)
      ? measuredTier(resolution) : 'estimated';
    bands.push({source_id: source.id, min_depth_m: min, max_depth_m: max, resolution_m: resolution, tier});
  }
  if (new Set(bands.map(band => band.source_id)).size !== sources.size) return;
  return bands;
}

function zoomSupport(value: unknown, min: number, max: number, sources: ReadonlyMap<string, ReliefSource>, bands: readonly DepthBand[]) {
  if (!record(value)) return;
  const result: Partial<Record<number, readonly ReliefTier[]>> = {};
  for (let z = 8; z <= 17; z++) {
    const zoom = value[z];
    if (z < min || z > max) {
      // The builder can emit explicit zero rows above the last written tile.
      if (zoom !== undefined && (!record(zoom) || zoom.tiles !== 0 || !Array.isArray(zoom.sources) || zoom.sources.length)) return;
      result[z] = ['none'];
      continue;
    }
    if (!record(zoom) || !count(zoom.tiles) || !Array.isArray(zoom.sources)) return;
    if (!zoom.tiles) {
      if (z === min || z === max || zoom.sources.length) return;
      result[z] = ['none'];
      continue;
    }
    const limit = z >= 16 ? 20 : 91.44;
    if (zoom.limit_m !== limit || (z >= 14 && !zoom.sources.length)) return;
    // 2518's counts are nominal native support, not cell certification.
    // For z16–17 the reviewed producer must explicitly certify every water
    // pixel in emitted tiles, not just the source cores (E2E-06/R7).
    if (z >= 16 && zoom.support_class !== 3) return;
    const tiers = new Set<ReliefTier>();
    for (const row of zoom.sources) {
      if (!record(row) || typeof row.id !== 'string' || !metres(row.resolution_m) ||
          row.resolution_m > (z >= 16 ? 1 : 5) || !count(row.tiles) || !row.tiles || row.tiles > zoom.tiles) return;
      const source = sources.get(row.id);
      const relevant = bands.filter(band => band.source_id === row.id && band.min_depth_m < limit && band.resolution_m === row.resolution_m);
      if (!source || !relevant.length) return;
      if (z >= 16 && (source.estimated || relevant.some(band => band.tier !== '1m'))) return;
      if (zoom.support_class === 3) for (const band of relevant) tiers.add(band.tier);
      else tiers.add('estimated');
    }
    result[z] = tiers.size ? [...tiers].sort() : ['estimated']; // overview mosaic, not a surveyed tier
  }
  // Never ignore a claimed tile outside the supported 8–17 namespace.
  if (Object.keys(value).some(z => !Object.hasOwn(result, z))) return;
  return result;
}

/** Only pass a pointer from the deployed catalog; do not fall back to `previous`.
 * `observed` is a caller-verified whole-object receipt, never a header/range check. */
export function resolveRelief(region: string, pointer: unknown, observed?: ReliefIdentity): Resolution {
  if (pointer == null) return refused('missing');
  if (!record(pointer) || pointer.region !== region || !ID.test(region)) return refused('wrong-region');
  const rows = publicSources(pointer);
  if (!rows) return refused('private');
  if ((pointer.status !== undefined && pointer.status !== 'reviewed') ||
      !hash(pointer.release_sha256) || !hash(pointer.envelope_sha256)) return refused('unreviewed');
  const {sha256, bytes, digest_root_sha256, release_sha256, envelope_sha256, minzoom, maxzoom, detail_summary} = pointer;
  if (!hash(sha256) || !count(bytes) || !bytes || !hash(digest_root_sha256) ||
      (observed && (observed.sha256 !== sha256 || observed.bytes !== bytes || observed.digest_root_sha256 !== digest_root_sha256))) {
    return refused('identity');
  }
  const bounds = boundsOf(pointer.bounds);
  if (!bounds || !count(minzoom) || !count(maxzoom) || minzoom < 8 || maxzoom > 17 || minzoom > maxzoom ||
      !record(detail_summary) || detail_summary.mask !== 'transparent-nodata') return refused('metadata');

  const sources = new Map<string, ReliefSource>();
  for (const row of rows) {
    const {id, attribution, survey_dates, release_date, vertical_datum, label} = row;
    if (!text(id) || sources.has(id) || !text(attribution) || !text(vertical_datum) || !text(label) ||
        !Array.isArray(survey_dates) || !survey_dates.length || !survey_dates.every(text) ||
        (release_date !== undefined && !text(release_date))) return refused('metadata');
    sources.set(id, {id, attribution, survey_dates: [...survey_dates], release_date, vertical_datum, label,
      estimated: label !== 'measured' || row.estimated === true, public_display: 'allowed',
      terms_url: text(row.rights.terms_url) ? row.rights.terms_url : undefined});
  }
  const depth_bands = depthBands(detail_summary, sources);
  const native_support_by_zoom = depth_bands && zoomSupport(pointer.native_support_by_zoom, minzoom, maxzoom, sources, depth_bands);
  if (!depth_bands || !native_support_by_zoom) return refused('unknown-resolution');
  const object_key = `tiles/relief/${region}/${sha256}.pmtiles`;
  return {status: 'ready', archive: {region, object_key, sha256, bytes, digest_root_sha256, release_sha256, envelope_sha256,
    minzoom, maxzoom, bounds, private: false, sources: [...sources.values()], mask: detail_summary.mask,
    depth_bands, native_support_by_zoom}};
}

/** One object per distinct hash, with each reviewed region's clipped bounds retained.
 * Bounding-box overlap alone cannot prove deduplication: coverage and holes can differ. */
export function selectReliefArchives(regions: Iterable<string>, pointers: ReadonlyMap<string, unknown>) {
  const byHash = new Map<string, ReliefArchive[]>();
  const conflicts = new Set<string>();
  const unavailable = new Map<string, Refusal>();
  for (const region of new Set(regions)) {
    const result = resolveRelief(region, pointers.get(region));
    if (result.status === 'unavailable') {
      unavailable.set(region, result.reason);
      continue;
    }
    const archive = result.archive;
    const bindings = byHash.get(archive.sha256);
    if (!bindings) byHash.set(archive.sha256, [archive]);
    else {
      const first = bindings[0]!;
      if (first.bytes !== archive.bytes || first.digest_root_sha256 !== archive.digest_root_sha256) conflicts.add(archive.sha256);
      bindings.push(archive);
    }
  }
  for (const sha256 of conflicts) {
    for (const binding of byHash.get(sha256) ?? []) unavailable.set(binding.region, 'identity');
    byHash.delete(sha256);
  }
  // The same bytes cannot be made public merely by changing their region alias.
  for (const [region, pointer] of pointers) {
    if (!record(pointer) || pointer.region !== region || !hash(pointer.sha256) || !byHash.has(pointer.sha256) || publicSources(pointer)) continue;
    for (const binding of byHash.get(pointer.sha256) ?? []) unavailable.set(binding.region, 'private');
    byHash.delete(pointer.sha256);
  }
  return {archives: [...byHash.values()].map(bindings => ({archive: bindings[0]!, bindings})), unavailable};
}
