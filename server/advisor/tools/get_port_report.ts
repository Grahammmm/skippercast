// get_port_report (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 §
// what's biting and § freshness; FR-1 interim, FR-4): what boats reported out
// of a port: the day's answer (TA-A1, answers/reports.ts: the stored one when
// it is current, else composed from the same facts without a second model
// call), the latest five published skipper reports for the port from advisor_reports
// (at most 14 days old; a verified boat is named, an unverified one is "a
// boat"), and the landing reports from the region's daily feed with their
// Insufficient/Low/Moderate label (answers/confidence.ts), labelled as reported
// by the landing (principle 5). Never a probability, never a catch rate.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS, portName, portRegion} from '../links.ts';
import {resolvePort, landingNames} from '../answers/resolve.ts';
import {regionConfig} from '../answers/regions.ts';
import {dailyFeed, feedReader} from '../answers/feeds.ts';
import {reportEvidence, targetSpecies} from '../answers/confidence.ts';
import type {LandingReport} from '../answers/confidence.ts';
import {addDays, daysBetween, localDate} from '../answers/time.ts';
// TA-I1: the verified/unverified contract (05 § Verification) is shared with get_trips.
import {publicBoat} from '../intake/skippers.ts';
// TA-A1: the day's answer.
import {dailyAnswer} from '../answers/reports.ts';
import {t} from '../strings.ts';

export const MAX_SKIPPER_REPORTS = 5, MAX_REPORT_AGE_DAYS = 14, MAX_LANDING_REPORTS = 6;

interface ReportRow {report_date: string; trip_type: string | null; anglers: number | null; counts_json: string; verified: number; notes: string | null; boat_name: string; boat_slug: string; published_at: string | null}
interface Count {species_key: string; label: string; kept: number | null; released: number | null}

function counts(json: string): Count[] {
  try {
    const v = JSON.parse(json);
    if (!Array.isArray(v)) return [];
    return v.filter(c => c && typeof c === 'object').slice(0, 12).map(c => ({
      species_key: typeof c.species_key === 'string' ? c.species_key : 'other', label: typeof c.label === 'string' ? c.label.slice(0, 40) : '',
      kept: Number.isFinite(c.kept) ? c.kept : null, released: Number.isFinite(c.released) ? c.released : null,
    }));
  } catch { return []; }
}
const ago = (today: string, date: string): string => { const d = daysBetween(date, today); return d === 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`; };
const weekday = (date: string): string => new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US', {weekday: 'short', timeZone: 'UTC'});

export const getPortReport: AdvisorTool = {
  name: 'get_port_report',
  description: "Recent fish reports for a port: the day's summary, the latest skipper reports (date, boat, counts, whether the boat is verified) and the landing's reports labelled as such, with how fresh they are. Use it for \"what's biting\" and before mentioning any catch. Never turn it into odds.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {port: {type: 'string', enum: [...PORT_IDS], description: 'Port id'}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'reports',
  async run(input, ctx) {
    const resolved = resolvePort(String(input.port ?? ''), ctx.contact, ctx.settings);
    if (!resolved) return {result: {error: 'unknown port'}};
    const port = resolved.port, regionId = portRegion(port)!, region = regionConfig(regionId);
    const tz = region?.timezone ?? 'America/Los_Angeles', today = localDate(ctx.now, tz), since = addDays(today, -MAX_REPORT_AGE_DAYS);

    // Skipper reports (ours): published, newest first, at most 14 days old.
    const rows = (await ctx.db.prepare(`SELECT r.report_date,r.trip_type,r.anglers,r.counts_json,r.verified,r.notes,r.published_at,b.name AS boat_name,b.slug AS boat_slug
        FROM advisor_reports r JOIN advisor_boats b ON b.id=r.boat_id WHERE r.port=? AND r.status='published' AND r.report_date>=? AND r.report_date<=?
        ORDER BY r.report_date DESC, r.published_at DESC LIMIT ?`).bind(port, since, today, MAX_SKIPPER_REPORTS).all<ReportRow>()).results;
    const skipper = rows.map(r => ({
      date: r.report_date, day: weekday(r.report_date), age: ago(today, r.report_date),
      ...publicBoat({name: r.boat_name, slug: r.boat_slug, verified: Boolean(r.verified)}),
      trip_type: r.trip_type, anglers: r.anglers, counts: counts(r.counts_json),
    }));

    // Landing reports (the scraped daily feed, cited as the landing's): this port's names, the last seven days.
    let landing: Record<string, unknown> = {available: false};
    const feed = region ? await dailyFeed(region, feedReader(ctx.deps)) : null;
    if (feed && region) {
      const names = new Set(landingNames(port).map(n => n.toLowerCase()));
      const portFeed = {...feed, reports: (feed.reports as LandingReport[]).filter(r => names.has(String(r.port ?? '').toLowerCase()))};
      const targets = [...new Set(region.species.filter(t => t !== 'dungeness'))];
      const bySpecies = targets.map(t => ({target: t, ...reportEvidence(portFeed, t, ctx.now, null, tz)}));
      const recent = bySpecies.flatMap(e => e.reports).filter((r, i, a) => a.findIndex(x => x.id === r.id) === i)
        .sort((a, b) => String(b.date).localeCompare(String(a.date))).slice(0, MAX_LANDING_REPORTS);
      landing = {
        available: true, label: t(ctx.language, 'landing_label'), feed_generated_at: feed.generated_at,
        window: {from: bySpecies[0]?.start ?? null, to: bySpecies[0]?.end ?? null},
        recent_activity: bySpecies.filter(e => e.reports.length || e.target === 'reef').map(e => ({target: e.target, species: targetSpecies(e.target), confidence: e.confidence, trips: e.reports.length, boats: e.boats, days: e.days})),
        reports: recent.map(r => ({date: r.date, age: ago(today, String(r.date)), boat: r.boat, trip_type: r.trip_type ?? null,
          catches: (r.catches ?? []).filter(c => (c.count ?? 0) > 0).slice(0, 8).map(c => ({label: (c as {label?: string}).label ?? c.species, count: c.count}))})),
      };
    }

    const answer = await dailyAnswer(ctx.env.DB ? ctx.env : {...ctx.env, DB: ctx.db}, port, today, ctx.language, {...ctx.deps, clock: ctx.deps.clock ?? (() => ctx.now)}, {generate: false});
    return {result: {
      port, port_name: portName(port), region: regionId, today,
      daily: {text: answer.text, source: answer.source === 'cache' ? 'stored' : 'composed', note: 'The answer for a plain "what\'s biting": send it as it is, or use it with the reports below for a more specific question.'},
      skipper_reports: skipper,
      skipper_reports_note: skipper.length ? `Newest first, at most ${MAX_REPORT_AGE_DAYS} days old. Name only verified boats; say "a boat" for the others. Always say the date or how many days ago.` : `No skipper reports for this port in the last ${MAX_REPORT_AGE_DAYS} days.`,
      landing,
      freshness: {newest_skipper_report: skipper[0]?.date ?? null, newest_landing_report: (landing.reports as {date: string}[] | undefined)?.[0]?.date ?? null},
      confidence_words: ['Insufficient', 'Low', 'Moderate'],
      catch_probability: null,
      link: `{{link:port:${port}}}`,
    }};
  },
};
