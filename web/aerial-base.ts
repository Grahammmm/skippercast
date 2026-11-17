// Region metadata only: safe for the landing page without loading the Chart.
/** The one catalog source an aerial base may name (catalog/sources.json, FE-45). */
export const AERIAL_CATALOG_ID = 'usgs-naip';
/** A region's aerial base as its package records it: catalog source, acquisition window, check date and note. */
export interface AerialBase {
  readonly source: typeof AERIAL_CATALOG_ID;
  readonly first: string;
  readonly last: string;
  readonly checkedAt: string;
  readonly note: string;
  /** The package opens the Chart on Aerial (`basemap.default`). */
  readonly byDefault: boolean;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
/** True only for a real calendar day: the UTC date must round-trip exactly (no overflow into another day). */
function isRealDate(s: string): boolean {
  const m = DATE.exec(s);
  if (!m) return false;
  const [y, mo, d] = m.slice(1).map(Number) as [number, number, number];
  const t = new Date(0);
  t.setUTCFullYear(y, mo - 1, d);
  return t.getUTCFullYear() === y && t.getUTCMonth() === mo - 1 && t.getUTCDate() === d;
}
/** region.json's `basemap.aerial`, or null where the region offers none or the record is not usgs-naip with ordered dates. */
export function aerialBase(region: unknown): AerialBase | null {
  const a = (region as {basemap?: {default?: unknown; aerial?: {source?: unknown; checked_at?: unknown; acquired?: {first?: unknown; last?: unknown}; note?: unknown}}} | null)?.basemap?.aerial;
  const first = a?.acquired?.first, last = a?.acquired?.last, checked = a?.checked_at, note = a?.note;
  if (a?.source !== AERIAL_CATALOG_ID || typeof first !== 'string' || typeof last !== 'string' || typeof checked !== 'string' || typeof note !== 'string') return null;
  if (![first, last, checked].every(isRealDate) || first > last || last > checked) return null;
  return {source: AERIAL_CATALOG_ID, first, last, checkedAt: checked, note, byDefault: (region as {basemap?: {default?: unknown}}).basemap?.default === 'aerial'};
}

