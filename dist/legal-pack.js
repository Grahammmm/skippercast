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
    const staleChecks = PARTS.includes(id) && (!checks.length || checks.some(s => s?.status !== 'ok' || !fresh(s.data_retrieved_at ?? s.checked_at, now, Math.min(36, s.max_age_hours > 0 ? s.max_age_hours : 36))));
    const date = new Intl.DateTimeFormat('en-CA', {timeZone: config?.timezone ?? 'America/Los_Angeles', year: 'numeric', month: '2-digit', day: '2-digit'}).format(now);
    const expired = id === 'rules' && (!/^\d{4}-\d{2}-\d{2}$/.test(d?.valid_from ?? '') || !/^\d{4}-\d{2}-\d{2}$/.test(d?.valid_through ?? '') || date < d.valid_from || date > d.valid_through);
    items.push({id, saved: !!valid, saved_at: hit?.saved_at ?? null,
      generated_at: valid ? d.generated_at ?? null : null,
      reviewed_at: record?.reviewed_at ?? null, valid_from: record?.valid_from ?? null, valid_through: record?.valid_through ?? null,
      sources: [...new Set(sources)],
      stale: !valid || !fresh(hit?.saved_at, now) || (PARTS.includes(id) && !fresh(d.generated_at, now)) || staleChecks || expired});
  }
  return {complete: !!assets && items.every(item => item.saved), stale: items.some(item => item.stale), items};
}
