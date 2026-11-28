// get_best_bets (fishing friend slice 1b, issue #3845; G BESTBET 2026-11-28): the best few
// ground x day x 3-hour block calls for reef fish (rockfish, lingcod) by boat, from the
// pure scorer (score/best-bets.ts) over the same intelligence and daily feeds get_conditions
// reads, with H from the reviewed ground catalog (catalog/advisor/best-bet-grounds.json) so
// the atlas never loads on the reply path. Offered only when ADVISOR_BEST_BETS is on
// (tools/index.ts toolsForRole). Never a percentage, a score number or a coordinate: the
// result carries the call, its reasons and how sure it is in words. A stale or unreadable
// forecast, an incomplete or old marine alert check, or a block with an hour of no
// forecast makes no call. Each call carries its factors (score/explain.ts): every input marked
// helps / neutral / hurts with its source, so the friend can say why.
import type {AdvisorTool} from './tool.ts';
import type {Language} from '../types.ts';
import catalog from '../../../catalog/advisor/best-bet-grounds.json' with {type: 'json'};
import {PORT_IDS, portName, portRegion} from '../links.ts';
import {resolvePort} from '../answers/resolve.ts';
import {regionConfig} from '../answers/regions.ts';
import {dailyFeed, feedReader, intelligenceFeed} from '../answers/feeds.ts';
import {HORIZON_DAYS, parseTripDate} from '../answers/conditions.ts';
import {forecastClock} from '../answers/forecast-clock.ts';
import {dayWord} from '../answers/planning.ts';
import {addDays, localDate} from '../answers/time.ts';
import {BLOCKS, bestBets, scoresFromCatalog, type CatalogGround, type ScoreRow} from '../score/best-bets.ts';
import {factorsFor} from '../score/explain.ts';

const GROUNDS = (catalog as {regions: Record<string, CatalogGround[]>}).regions;
const WEEK = 7;   // today and the next six days, as the offline builder scores

/** How sure, in words (BESTBET: never a percentage). Open rows are Moderate or Low; Insufficient is never ranked. */
export const SURE_WORDS: Readonly<Record<Language, Record<'Moderate' | 'Low', string>>> = Object.freeze({
  en: {Moderate: 'fairly sure on the weather and the bottom', Low: 'a fair call, but the forecast or the map is thin'},
  es: {Moderate: 'bastante seguro del clima y del fondo', Low: 'una apuesta razonable, pero el pronóstico o el mapa son limitados'},
});
const hhmm = (h: number) => `${String(h).padStart(2, '0')}:00`;
const HOURS = new Map(BLOCKS.map(b => [b.id as string, `${hhmm(b.start)}-${hhmm(b.end + 1)}`] as const));

export const getBestBets: AdvisorTool = {
  name: 'get_best_bets',
  description: 'The best calls for rockfish and lingcod by boat out of Morro Bay or Avila: which named public ground, which day and which 3-hour block, with the reasons (wind, seas, mapped reef structure) and how sure in words. Days a small craft advisory or rough seas close are listed. Call it when someone asks where or when to go for reef fish; then call get_rules before naming the day.',
  input_schema: {type: 'object', additionalProperties: false, properties: {
    port: {type: 'string', enum: [...PORT_IDS], description: 'The port the person fishes from, when they said; default their home port'},
    date: {type: 'string', description: 'YYYY-MM-DD, or a word the person used such as Saturday or this weekend; leave out for the coming week'},
  }},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'best_bets',
  async run(input, ctx) {
    const resolved = resolvePort(typeof input.port === 'string' ? input.port : '', ctx.contact, ctx.settings);
    const regionId = resolved ? portRegion(resolved.port) : null, region = regionConfig(regionId);
    const grounds = regionId && Object.hasOwn(GROUNDS, regionId) ? GROUNDS[regionId]! : [];
    if (!resolved || !region || !grounds.length) return {result: {unavailable: true, reason: 'best bets cover Morro Bay and Avila only so far',
      note: 'Say plainly you cannot make that call there yet; get_conditions still gives the weather.'}};
    const tz = region.timezone, today = localDate(ctx.now, tz), language = ctx.language;
    const asked = typeof input.date === 'string' && input.date.trim() ? input.date : null;
    const when = asked ? parseTripDate(asked, ctx.now, tz) : null;
    const head = {port: resolved.port, port_name: portName(resolved.port), asked, date_understood: when ? when.parsed : null};
    if (when?.past) return {result: {...head, error: 'that date has passed'}};
    if (when?.beyond_horizon) return {result: {...head, beyond_horizon: true, note: `The forecast only reaches ${HORIZON_DAYS} days: say so and offer to check closer to the day.`}};
    const dates = when?.parsed ? when.dates : Array.from({length: WEEK}, (_, i) => addDays(today, i));

    const read = feedReader(ctx.deps);
    const [intel, daily] = await Promise.all([intelligenceFeed(region, read), dailyFeed(region, read)]);
    if (!intel || forecastClock(intel, ctx.now).state === 'unusable') return {result: {...head, error: 'forecast not usable',
      note: 'Make no call: say the forecast is not fresh enough to pick a day and point to the NWS forecast.'}};
    const file = scoresFromCatalog({region, intel, daily, grounds, dates, now: ctx.now});
    const closed = dates.flatMap(date => {
      const rows = file.rows.filter(r => r.date === date), shut = rows.filter(r => r.gate === 'advisory' || r.gate === 'rough');
      return rows.length && shut.length === rows.length
        ? [{date, day: dayWord(date, today, language), why: shut.find(r => r.gate === 'advisory')?.conditions.reasons[0] ?? 'rough seas'}] : [];
    });
    const call = (r: ScoreRow) => ({area: r.area, date: r.date, day: dayWord(r.date, today, language), hours: HOURS.get(r.block),
      comfort: r.conditions.comfort, factors: factorsFor(r),
      confidence_words: SURE_WORDS[language][r.evidence as 'Moderate' | 'Low']});
    const best = bestBets(file, {n: 3}).map(call);
    return {result: {
      ...head, dates, best_bets: best, closed_days: closed,
      advisories_checked: file.advisories_checked, forecast_issued: file.forecast_issued, forecast_age_hours: file.forecast_age_hours,
      limitations: file.limitations,
      note: [!file.advisories_checked ? 'NWS advisories could not be checked or the check is old: make no call, say so and point to the NWS forecast.'
        : best.length ? 'Make one clear call from the first best bet (area, day, hours): say what helps and anything that hurts from its factors, in plain words, and its confidence_words word for word. Never give a neutral "not used" factor as a reason. It is a call on weather and seafloor structure, not a catch prediction.'
        : 'No open block on these days: say so, with closed_days\' reasons.',
      closed.length ? 'Name the closed days and why.' : null,
      'Never a percentage, odds or a score number.'].filter(Boolean).join(' '),
    }};
  },
};
