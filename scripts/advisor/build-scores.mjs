#!/usr/bin/env node
// Offline "best bets" score file for one region (server/advisor/score/best-bets.ts, issue #3845).
// Reads local copies of the region's intelligence feed (forecast models) and daily feed
// (NWS alerts), the reviewed region manifest, the public-grounds allowlist, the charter
// grounds and the atlas targets; writes the score file and prints the top three bets.
// No network, no model call, no D1; nothing in the advisor reads its output yet.
//
//   node scripts/advisor/build-scores.mjs --intel intel.json --daily latest.json [--region morro-bay]
//        [--now 2026-11-28T16:00:00Z] [--days 7] [--out scores.json]
import {readFileSync, writeFileSync} from 'node:fs';
import {parseArgs} from 'node:util';

const root = new URL('../../', import.meta.url);
const read = p => JSON.parse(readFileSync(p instanceof URL ? p : new URL(p, root)));
const {values: args} = parseArgs({options: {
  intel: {type: 'string'}, daily: {type: 'string'}, region: {type: 'string', default: 'morro-bay'},
  now: {type: 'string'}, days: {type: 'string', default: '7'}, out: {type: 'string'},
}});
if (!args.intel || !args.daily) {
  console.error('usage: build-scores.mjs --intel <intelligence.json> --daily <latest.json> [--region id] [--now ISO] [--days N] [--out file]');
  process.exit(2);
}
const region = read(`regions/${args.region}/region.json`);
globalThis.REGIONS = {[region.id]: region};
const {buildScores, bestBets, reefGrounds} = await import('../../server/advisor/score/best-bets.ts');
const {addDays, localDate} = await import('../../server/advisor/answers/time.ts');

const now = args.now ? Date.parse(args.now) : Date.now();
const days = Math.max(1, Math.min(7, Number.parseInt(args.days, 10) || 7));
const today = localDate(now, region.timezone);
const grounds = reefGrounds(region, read('catalog/advisor/public-grounds.json').regions[region.id] ?? [], read('dist/data/charter-grounds.json').grounds);
const file = buildScores({
  region, intel: JSON.parse(readFileSync(args.intel)), daily: JSON.parse(readFileSync(args.daily)),
  grounds, targets: read('dist/data/atlas.json').targets, now,
  dates: Array.from({length: days}, (_, i) => addDays(today, i)),
});
if (args.out) writeFileSync(args.out, `${JSON.stringify(file, null, 1)}\n`);
const open = file.rows.filter(r => r.rank !== null).length;
console.log(`${file.region_id} ${file.weights_version}: ${file.rows.length} rows (${open} open), forecast ${file.forecast_issued ?? 'unknown'} (${file.forecast_age_hours ?? '?'} h old), alerts checked: ${file.advisories_checked}`);
for (const r of bestBets(file)) {
  console.log(`  ${r.date} ${r.block.padEnd(9)} ${r.area.padEnd(16)} rank ${r.rank.toFixed(3)}  C ${r.conditions.value} (${r.conditions.comfort}; ${r.conditions.reasons.join('; ')})  H ${r.habitat.value}  evidence ${r.evidence}`);
}
