// Prints whether the six data-rights rows behind the `report` coast feed would let the Worker honour it.
// Reads the register through the Worker's own FEED_SOURCES and coastFeeds; writes nothing, sends nothing.
import {fileURLToPath} from 'node:url';

globalThis.REGIONS ??= {};
globalThis.DEPLOYMENT ??= {allowed_origins: ['https://skippercast.com']};
const {FEED_SOURCES, coastFeeds} = await import('../server/coast-data.ts');

const OK = {review_status: 'approved', rights: {commercial_use: 'allowed'}};
const PR_LINE = 'rows changed by PR #2223 (R4-SC-05): https://github.com/Grahammmm/skippercast/pull/2223';
const ids = FEED_SOURCES.report;
const label = row => row ? `${row.review_status ?? 'unknown'}/${row.rights?.commercial_use ?? 'unknown'}` : 'missing';

// The register with every report row but `keep` replaced by a confirmed one, so the Worker judges `keep` alone.
const only = (sources, keep) => [...sources.filter(s => !ids.includes(s.id) || s.id === keep),
  ...ids.filter(id => id !== keep).map(id => ({id, ...OK}))];
const honours = sources => coastFeeds('report', sources).has('report');

export function readiness(sources) {
  const byId = new Map(sources.map(s => [s.id, s]));
  const lines = ids.map(id => {
    const row = byId.get(id);
    if (!row) return `${id}: missing -> refused`;
    const status = row.review_status ?? 'unknown', use = row.rights?.commercial_use ?? 'unknown';
    const mark = !honours(only(sources, id)) ? 'refused' : status === 'candidate' || use === 'unknown' ? 'needs-owner-confirmation' : 'confirmed';
    return `${id}: ${status}, ${use} -> ${mark}`;
  });
  const honoured = honours(sources);
  const culprit = honoured ? undefined : ids.find(id => !honours(only(sources, id)));
  lines.push(honoured ? 'report would be honoured' : `report would be dropped because ${culprit}: ${label(byId.get(culprit))}`);
  lines.push(PR_LINE);
  if (lines.length > 12) throw new Error(`readiness would print ${lines.length} lines; the limit is 12`);
  return {lines, honoured};
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const {default: catalog} = await import('../catalog/sources.json', {with: {type: 'json'}});
  const {lines, honoured} = readiness(catalog.sources);
  console.log(lines.join('\n'));
  process.exit(honoured ? 0 : 1);
}
