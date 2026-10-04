// get_trips (docs/plans/text-advisor/04-advisor-engine.md § Tools, 06 § trips for
// newcomers; AD-3): verified boats for a port from advisor_boats with their
// landing, booking link, boat page placeholder and the trip types seen in
// their reports of the last 60 days. Ordered by most recent report, never
// ranked. With fewer than two verified boats `few: true`, and the reply says
// "the boats I work with so far" and links the port page.
import type {AdvisorTool} from './tool.ts';
import {PORT_IDS, portName} from '../links.ts';
import {resolvePort} from '../answers/resolve.ts';
import {addDays, localDate} from '../answers/time.ts';

export const TRIP_TYPE_DAYS = 60, MAX_BOATS = 12;
interface BoatRow {id: string; slug: string; name: string; landing: string | null; booking_url: string | null; last_report: string | null}

export const getTrips: AdvisorTool = {
  name: 'get_trips',
  description: "Verified charter and party boats for a port, with their landing, trip types, booking link and boat page. Never rank one boat over another.",
  input_schema: {type: 'object', additionalProperties: false, required: ['port'], properties: {port: {type: 'string', enum: [...PORT_IDS]}}},
  roles: ['angler', 'skipper', 'crew'],
  intent: 'trips',
  async run(input, ctx) {
    const resolved = resolvePort(String(input.port ?? ''), ctx.contact, ctx.settings);
    if (!resolved) return {result: {error: 'unknown port'}};
    const port = resolved.port, since = addDays(localDate(ctx.now), -TRIP_TYPE_DAYS);
    const boats = (await ctx.db.prepare(`SELECT b.id,b.slug,b.name,b.landing,b.booking_url,
        (SELECT MAX(r.report_date) FROM advisor_reports r WHERE r.boat_id=b.id AND r.status='published') AS last_report
        FROM advisor_boats b WHERE b.port=? AND b.status='verified' ORDER BY last_report IS NULL, last_report DESC, b.name LIMIT ?`)
      .bind(port, MAX_BOATS).all<BoatRow>()).results;
    const types = boats.length ? (await ctx.db.prepare(`SELECT DISTINCT boat_id, trip_type FROM advisor_reports WHERE boat_id IN (${boats.map(() => '?').join(',')})
        AND status='published' AND report_date>=? AND trip_type IS NOT NULL ORDER BY trip_type`).bind(...boats.map(b => b.id), since).all<{boat_id: string; trip_type: string}>()).results : [];
    const list = boats.map(b => ({
      name: b.name, landing: b.landing, booking_url: b.booking_url && /^https:\/\//.test(b.booking_url) ? b.booking_url : null,
      boat_page: `{{link:boat:${b.slug}}}`, trip_types: types.filter(t => t.boat_id === b.id).map(t => t.trip_type), last_report: b.last_report,
    }));
    const few = list.length < 2;
    return {result: {
      port, port_name: portName(port), boats: list, few,
      note: few ? 'Say "the boats I work with so far" and link the port page. Never recommend one boat over another.' : 'Listed by most recent report, not ranked. Never recommend one boat over another.',
      link: `{{link:port:${port}}}`,
    }};
  },
};
