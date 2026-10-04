// get_conditions (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 §
// planning steps 1-3; FR-2 data, AD-4): the fishing window's wind, gusts, seas,
// swell period and direction for a port on a date, the comfort word for a
// mid-size center console, and any small craft advisory, gale warning or
// hazardous seas statement the daily feed recorded for the region's marine
// zones, listed first. Dates in the person's words (answers/conditions.ts);
// beyond seven days → beyond_horizon. Never a catch number or a clearance.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS, portName, portRegion} from '../links.ts';
import {resolvePort} from '../answers/resolve.ts';
import {regionConfig} from '../answers/regions.ts';
import {dailyFeed, intelligenceFeed, feedReader} from '../answers/feeds.ts';
import {advisoriesFrom, parseTripDate, regionZones, windowConditions, windowEpochs, WINDOW} from '../answers/conditions.ts';
import ports from '../../../catalog/home-ports.json' with {type: 'json'};

const FORECAST_POINT = new Map(ports.ports.map(p => [p.id, p.forecast_point] as const));
const hourOf = (v: unknown): number | null => Number.isInteger(v) && (v as number) >= 0 && (v as number) <= 23 ? v as number : null;

export const getConditions: AdvisorTool = {
  name: 'get_conditions',
  description: "Wind, gusts, seas, swell period and direction for a port's fishing window on a date, and any small craft advisory, gale warning or hazardous seas statement. Call it before any trip-planning answer; lead with an advisory when there is one.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {
    port: {type: 'string', enum: [...PORT_IDS]},
    date: {type: 'string', description: 'YYYY-MM-DD, or a word the person used such as Saturday or tomorrow'},
    start_hour: {type: 'integer', minimum: 0, maximum: 23, description: 'Local start hour when the person gave one; default 6'},
    end_hour: {type: 'integer', minimum: 0, maximum: 23, description: 'Local end hour; default 14'},
  }},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'conditions',
  async run(input, ctx) {
    const resolved = resolvePort(String(input.port ?? ''), ctx.contact, ctx.settings);
    const region = resolved ? regionConfig(portRegion(resolved.port)) : null;
    if (!resolved || !region) return {result: {error: 'unknown port'}};
    const port = resolved.port, tz = region.timezone;
    const start = hourOf(input.start_hour) ?? WINDOW.start, end = hourOf(input.end_hour) ?? WINDOW.end;
    const window = start < end ? {start, end} : WINDOW;
    const when = parseTripDate(typeof input.date === 'string' ? input.date : '', ctx.now, tz);
    const head = {port, port_name: portName(port), asked: input.date ?? null, dates: when.dates, date_understood: when.parsed};
    if (when.past) return {result: {...head, error: 'that date has passed'}};
    if (when.beyond_horizon) return {result: {...head, beyond_horizon: true, note: 'The forecast only reaches 7 days. Say so and offer to check closer to the day.'}};

    const read = feedReader(ctx.deps);
    const [intel, daily] = await Promise.all([intelligenceFeed(region, read), dailyFeed(region, read)]);
    const pointId = FORECAST_POINT.get(port) ?? region.forecast_points[0]?.id ?? '';
    const days = when.dates.map(date => windowConditions(intel, region, pointId, date, window));
    const [from] = windowEpochs(when.dates[0]!, tz, window), [, to] = windowEpochs(when.dates.at(-1)!, tz, window);
    const alerts = daily ? advisoriesFrom(daily, regionZones(region), from, to) : null;
    return {result: {
      ...head, beyond_horizon: false,
      advisories: alerts ?? [],
      advisories_checked: alerts !== null,
      advisories_as_of: daily?.sources ? (Object.entries(daily.sources).find(([k]) => k.startsWith('alerts-'))?.[1] as {checked_at?: string} | undefined)?.checked_at ?? null : null,
      lead_with_advisory: Boolean(alerts?.length),
      days,
      forecast_issued: intel?.completed_at ?? null,
      note: [alerts?.length ? 'Start the reply with the advisory, the word in capitals (SMALL CRAFT ADVISORY), and end with "Check the latest NWS forecast before you go."' : null,
        alerts === null ? 'NWS advisories could not be checked: say so and point to the NWS forecast.' : null,
        'Comfort is for a mid-size center console; the person\'s own boat may differ. Never say the harbor bar is open or closed. Never give a percentage or a catch number.'].filter(Boolean).join(' '),
    }};
  },
};
