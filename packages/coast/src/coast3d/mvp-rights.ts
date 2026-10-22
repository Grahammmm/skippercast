import {
  CSUMB_NOTICE, GEBCO_CAVEAT, NO_ENDORSEMENT, NOT_FOR_NAVIGATION, RIGHTS_REVIEW,
  mentionsCsumb, mentionsGebco, validateMvpManifest,
  type MvpManifest, type MvpSource,
} from './mvp.ts';

/**
 * Offline adapter: C5 rights inventory (schema_version=1) -> C3 presentation manifest.
 *
 * It mirrors C5's contributor rules instead of importing research tooling (product
 * code must not import research/). It never fetches URLs, reads rasters or verifies
 * hashes/citations, and never infers commercial permission: every row stays
 * review_required and any CSUMB involvement becomes needs_permission.
 */
export type C3TileBase = Omit<MvpManifest, 'sources' | 'rightsInventory'> & {
  mosaic: {datum: string; resolutionM: number};
};
export type RightsLink = {
  /** Relative path, beside the presentation manifest, of the complete C5 rights page. */
  page: string;
  /** SHA-256 of the exact C5 inventory bytes the adapter read. */
  inventorySha256: string;
};

const HEX64 = /^[0-9a-f]{64}$/;
function text(value: unknown, field: string): string {
  if (typeof value !== 'string' || !value.trim()) throw Error(`${field} must be a nonempty string`);
  return value;
}
function httpsUrl(value: unknown, field: string): string {
  const s = text(value, field);
  let u: URL;
  try { u = new URL(s); } catch { throw Error(`${field} must be an HTTPS URL`); }
  if (u.protocol !== 'https:' || !u.hostname || u.username || u.password || /\s/.test(s)) {
    throw Error(`${field} must be an HTTPS URL without credentials or whitespace`);
  }
  return s;
}

export function adaptC5Rights(inventory: unknown, base: C3TileBase, link: RightsLink): MvpManifest {
  const inv = inventory as {schema_version?: unknown; sources?: unknown; fixture_only?: unknown};
  if (!inv || typeof inv !== 'object' || Array.isArray(inv) || inv.schema_version !== 1 || !Array.isArray(inv.sources)) {
    throw Error('C5 inventory must have schema_version=1 and sources[]');
  }
  if (!HEX64.test(String(link?.inventorySha256))) throw Error('inventory sha256 must be 64 lowercase hex characters');
  const seen = new Set<string>();
  const used: MvpSource[] = [];
  for (const raw of inv.sources) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw Error('each source must be an object');
    const row = raw as Record<string, unknown>;
    const id = text(row.source_id, 'source_id');
    if (seen.has(id)) throw Error(`duplicate source_id: ${id}`);
    seen.add(id);
    const cells = row.contributed_cells;
    // Missing or guessed usage is an error, never treated as zero.
    if (typeof cells !== 'number' || !Number.isSafeInteger(cells) || cells < 0) {
      throw Error(`${id}: contributed_cells must be a nonnegative integer`);
    }
    if (cells === 0) continue;
    const name = text(row.name, `${id}.name`);
    const url = httpsUrl(row.source_url, `${id}.source_url`);
    const sha256 = text(row.sha256, `${id}.sha256`);
    if (!HEX64.test(sha256)) throw Error(`${id}: sha256 must be 64 lowercase hex characters`);
    const rights = row.rights as Record<string, unknown> | undefined;
    if (!rights || typeof rights !== 'object' || Array.isArray(rights)) throw Error(`${id}: rights object is required`);
    const license = text(rights.license, `${id}.rights.license`);
    const termsUrl = httpsUrl(rights.terms_url, `${id}.rights.terms_url`);
    const attribution = text(rights.attribution, `${id}.rights.attribution`);
    if (typeof rights.csumb_involved !== 'boolean') throw Error(`${id}: rights.csumb_involved must be boolean`);
    // Keep the hold even when an obvious CSUMB source is wrongly tagged false.
    const csumb = rights.csumb_involved || mentionsCsumb([id, name, url, license, termsUrl, attribution]);
    used.push({
      id, label: name, url, attribution, license, datum: null, resolutionM: null,
      permissionRequired: csumb,
      rights: {sha256, termsUrl, contributedCells: cells, csumbInvolved: csumb,
        status: csumb ? 'needs_permission' : 'review_required'},
    });
  }
  if (!used.length) throw Error('C5 inventory has no contributing sources; refusing an unattributed terrain view');
  used.sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const caveats = [NOT_FOR_NAVIGATION, RIGHTS_REVIEW, NO_ENDORSEMENT];
  if (used.some(s => s.rights!.csumbInvolved)) caveats.push(CSUMB_NOTICE);
  if (used.some(s => mentionsGebco([s.id, s.label, s.url ?? '', s.license, s.rights!.termsUrl, s.attribution]))) caveats.push(GEBCO_CAVEAT);
  if (!base || typeof base !== 'object' || typeof base.synthetic !== 'boolean' || !base.mosaic || typeof base.mosaic !== 'object') {
    throw Error('C3 tile base needs a synthetic flag and mosaic datum/spacing');
  }
  const b = base;
  // Copy only C3 presentation fields; nothing else from the tile base reaches the viewer.
  const manifest: MvpManifest = {
    schemaVersion: b.schemaVersion, region: b.region,
    // A synthetic inventory can never label a view as measured.
    synthetic: b.synthetic || inv.fixture_only === true,
    bounds: b.bounds, center: b.center, zoom: b.zoom, tileZoom: b.tileZoom, tileSize: b.tileSize,
    terrain: b.terrain, contours: b.contours, contourLayer: b.contourLayer,
    mosaic: {datum: b.mosaic.datum, resolutionM: b.mosaic.resolutionM},
    sources: used,
    rightsInventory: {schemaVersion: 1, sha256: link.inventorySha256, page: link.page, status: 'review_required', caveats},
  };
  return validateMvpManifest(structuredClone(manifest));
}
