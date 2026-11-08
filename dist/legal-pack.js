// Cache-only legal inventory. Presence is not legal clearance; never fetch or refresh a saved date here.
import {dailyPartPath, SAVED_HEADER} from './offline-core.js';

const PARTS = ['regulations', 'mpa-boundaries', 'additional-closures'];
const fresh = (iso, now, hours = 36) => {
  const age = now - Date.parse(iso);
  return Number.isFinite(age) && age >= 0 && age <= hours * 3600000;
};
const https = value => { try { return new URL(value).protocol === 'https:'; } catch { return false; } };

/** Inspect the actual responses, including evictions since save. Works on old packs, with no metadata migration. */
export async function inspectLegalPack(cache, regionId, origin, now = Date.now()) {
  async function read(path) {
    try {
      if (!path) return null;
      const url = new URL(path, origin + '/');
      if (url.origin !== origin) return null;
      const response = await cache.match(url.href);
      return response?.ok ? {data: await response.json(), saved_at: response.headers.get(SAVED_HEADER)} : null;
    } catch { return null; }
  }
  const config = (await read(`/regions/${regionId}/region.json`))?.data;
  const assets = config?.id === regionId ? config.assets : null;
  const requests = [
    ['rules', assets?.regulations], ['areas', assets?.protected_areas],
    ...PARTS.map(part => [part, dailyPartPath(regionId, part)]),
  ];
  const items = [];
  for (const [id, path] of requests) {
    const hit = await read(path), d = hit?.data;
    const valid = id === 'rules' ? d?.schema_version === 1
      : id === 'areas' ? d?.type === 'FeatureCollection' && Array.isArray(d.features)
      : d?.schema_version === 1 && d.region_id === regionId && d.part === id
        && !!(id === 'regulations' ? d.regulations : d.sources);
    const record = valid ? (id === 'regulations' ? d.regulations : d) : null;
    const sources = Object.values(record?.sources ?? {}).map(s => s?.url).concat(record?.source_url ?? []).filter(https);
    // A new download cannot make an old source check fresh. Unknown/error checks warn as well.
    const checks = Object.values(record?.checks ?? record?.sources ?? {});
    // Pipeline regulation checks: healthy is status 'unchanged' with source_status 'ok'. 'out-of-scope' and
    // 'not-requested' checks are not this region's rules and never made a request, so they neither pass nor warn.
    // Source entries of the other parts report plain status 'ok'.
    const skipped = s => id === 'regulations' && (s?.status === 'out-of-scope' || s?.status === 'not-requested');
    const healthy = s => id === 'regulations' ? s?.status === 'unchanged' && s.source_status === 'ok' : s?.status === 'ok';
    const staleChecks = PARTS.includes(id) && (!checks.length || checks.some(s => !skipped(s) && (!healthy(s) || !fresh(s.data_retrieved_at ?? s.checked_at, now, Math.min(36, s.max_age_hours > 0 ? s.max_age_hours : 36)))));
    const date = new Intl.DateTimeFormat('en-CA', {timeZone: config?.timezone ?? 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
    const expired = id === 'rules' && (!/^\d{4}-\d{2}-\d{2}$/.test(d?.valid_from ?? '') || !/^\d{4}-\d{2}-\d{2}$/.test(d?.valid_through ?? '') || date < d.valid_from || date > d.valid_through);
    // The static boundary snapshot carries its own source check date. A fresh cache-save time cannot stand in for it:
    // an old, undated, unreadable or future-dated snapshot warns however recently it was downloaded.
    const checkedAt = id === 'areas' && valid && typeof d.checked_at === 'string' ? d.checked_at : null;
    const staleSnapshot = id === 'areas' && !fresh(checkedAt, now);
    items.push({id, saved: !!valid, saved_at: hit?.saved_at ?? null,
      generated_at: valid ? d.generated_at ?? null : null,
      checked_at: checkedAt,
      reviewed_at: record?.reviewed_at ?? null, valid_from: record?.valid_from ?? null, valid_through: record?.valid_through ?? null,
      sources: [...new Set(sources)],
      stale: !valid || !fresh(hit?.saved_at, now) || (PARTS.includes(id) && !fresh(d.generated_at, now)) || staleChecks || staleSnapshot || expired});
  }
  return {complete: !!assets && items.every(item => item.saved), stale: items.some(item => item.stale), items};
}
