// get_conditions (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 §
// planning; FR-2, AD-4): the fishing window's wind, gusts, seas, swell period
// and direction for a port on a date, the comfort word for a mid-size center
// console, and any small craft advisory, gale warning or hazardous seas
// statement the daily feed recorded for the region's marine zones, listed
// first with `advisory_line` written in the reply language. Dates in the
// person's words; beyond seven days → beyond_horizon. With `species` (TA-A2)
// the result carries the planning brief (answers/planning.ts): the season
// status, the recent activity, the one confidence phrase and the NWS closer.
// Never a catch number or a clearance.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS} from '../links.ts';
import {planningBrief, tripConditions} from '../answers/planning.ts';

export const getConditions: AdvisorTool = {
  name: 'get_conditions',
  description: "Wind, gusts, seas, swell period and direction for a port's fishing window on a date, and any small craft advisory, gale warning or hazardous seas statement. Call it before any trip-planning answer, with the species when the person names one: then it also returns the season status, the recent reports, the one confidence phrase to use and the closing line. Lead with an advisory when there is one.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {
    port: {type: 'string', enum: [...PORT_IDS]},
    date: {type: 'string', description: 'YYYY-MM-DD, or a word the person used such as Saturday, this weekend or mañana'},
    species: {type: 'string', description: 'The fish the trip is for, as a key or the person\'s word (rockfish, lings, rocote), when they named one'},
    start_hour: {type: 'integer', minimum: 0, maximum: 23, description: 'Local start hour when the person gave one; default 6'},
    end_hour: {type: 'integer', minimum: 0, maximum: 23, description: 'Local end hour; default 14'},
  }},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'conditions',
  async run(input, ctx) {
    const opts = {now: ctx.now, language: ctx.language, deps: ctx.deps, contact: ctx.contact, settings: ctx.settings};
    const date = typeof input.date === 'string' ? input.date : null;
    if (typeof input.species === 'string' && input.species.trim()) {
      const env = ctx.env?.DB ? ctx.env : {...ctx.env, DB: ctx.db};
      const hour = (v: unknown) => typeof v === 'number' ? v : null;
      return {result: await planningBrief(env, {port: String(input.port ?? ''), date, species: input.species, startHour: hour(input.start_hour), endHour: hour(input.end_hour)}, opts)};
    }
    return {result: await tripConditions({port: String(input.port ?? ''), date, start_hour: input.start_hour, end_hour: input.end_hour}, opts)};
  },
};
