// The brief's tide curve, trend and sparkline arguments (FE-33, design § 10).
//
// The curve is the station's CO-OPS prediction series as packages/coast reads
// it into the coast report (`report.tides`) and buildDaily cuts to the day
// (`DailyBrief.tides`, carried on the brief). This module adds nothing to that
// series; it states two rules packages/coast `ui/briefing.ts` applies, so v2
// can use them without importing that module (it does not yet type-check
// under web/tsconfig.json, see web/app/CoastMarkup.tsx):
// - the trend (`tideAt`): the curve point within 4 minutes of the selected
//   time and the next point, if it follows within 15 minutes, decide Rising,
//   Falling or Turning (a change under 0.005 ft); otherwise there is no trend;
// - the sparkline (`tideChart`): `chart()` in mini mode over the day's curve
//   with night shading, a 15-minute gap rule and the curve's range; fewer
//   than two points draw nothing and read "Tide series unavailable".
// tests/test_tides.mjs pins both against briefing.ts.
//
// Erasable syntax only: Node tests import this file by type stripping.
import type {Series} from '../packages/coast/src/charts/series.ts';
import type {TideEvent, TidePoint} from '../packages/coast/src/types.ts';

export type TideTrend = 'Rising' | 'Falling' | 'Turning';
export const TIDE_UNAVAILABLE = 'Tide series unavailable';
/** The curve point must sit this close to the selected time. */
export const TREND_MATCH_MS = 4 * 60_000;
/** The next point must follow within this, or the curve is too coarse to call a trend. */
export const TREND_STEP_MS = 15 * 60_000;
/** A change smaller than this between the two points reads Turning. */
export const TURNING_FT = 0.005;
/** The sparkline's colour: the tide hue through the token bridge. */
export const TIDE_COLOUR = 'var(--coast-amber)';

/** Rising, Falling or Turning at `at` by the 15-minute rule; null when the curve has no point within 4 minutes or no next point within 15. */
export function tideTrend(points: readonly TidePoint[], at: string | number): TideTrend | null {
  const t = typeof at === 'number' ? at : Date.parse(at);
  if (!Number.isFinite(t)) return null;
  const i = points.findIndex(p => Math.abs(Date.parse(p.at) - t) <= TREND_MATCH_MS);
  const point = points[i], next = points[i + 1];
  if (!point || !next || Date.parse(next.at) - Date.parse(point.at) > TREND_STEP_MS) return null;
  const change = next.heightFt - point.heightFt;
  return Math.abs(change) < TURNING_FT ? 'Turning' : change > 0 ? 'Rising' : 'Falling';
}

/** The parts of the brief the sparkline reads. */
export interface TideDay {
  readonly tides: readonly TidePoint[];
  readonly tideEvents: readonly TideEvent[];
  readonly tideDatum: string;
  readonly sunrise: string | null;
  readonly sunset: string | null;
}

/** The arguments of `chart()` for the day's sparkline, as briefing.ts `tideChart` builds them; null with fewer than two points. */
export function sparkArgs(day: TideDay, selected: string, tz: string, colour = TIDE_COLOUR):
  [Series[], string, string, string, string, {mini: boolean; sunrise: string | null; sunset: string | null}] | null {
  const first = day.tides[0], last = day.tides.at(-1);
  if (day.tides.length < 2 || !first || !last) return null;
  const heights = [...day.tides, ...day.tideEvents].map(p => p.heightFt).filter(Number.isFinite);
  const min = heights.length ? Math.min(...heights) : 0, max = (heights.length ? Math.max(...heights) : 5) + 0.3;
  const row: Series = {label: 'Tide', unit: `ft ${day.tideDatum}`, color: colour, points: day.tides.map(p => ({at: p.at, value: p.heightFt})), gapMs: TREND_STEP_MS, min, max};
  return [[row], first.at, last.at, selected, tz, {mini: true, sunrise: day.sunrise, sunset: day.sunset}];
}
