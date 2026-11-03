// Measured gaps beside, never an input to, the comfort score.
import {MODEL_GAP, type FeedHour} from '../score.ts';

export interface Agreement {
  state: 'agree' | 'partial' | 'differ' | 'one-model' | 'none';
  hours: number;
  compared: number;
  gap: {wind: number; sea: number} | null;
  worst: {ms: number; wind: number; sea: number} | null;
  differing: number;
}

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v);
const round = (n: number) => Number(n.toFixed(1));

export function modelAgreement(rows: readonly {ms: number; hour: FeedHour}[]): Agreement {
  const timed = rows.filter(row => finite(row.ms));
  const unique = [...new Map([...timed].reverse().map(row => [row.ms, row])).values()].sort((a, b) => a.ms - b.ms);
  let compared = 0, differing = 0, largest = -1, maxWind = 0, maxSea = 0;
  let worst: Agreement['worst'] = null;
  for (const {ms, hour: h} of unique) {
    if (!finite(h.wind) || !finite(h.other_wind) || !finite(h.sea) || !finite(h.other_sea)) continue;
    const wind = Math.abs(h.wind - h.other_wind), sea = Math.abs(h.sea - h.other_sea);
    compared++;
    if (wind > MODEL_GAP.wind || sea > MODEL_GAP.sea) differing++;
    maxWind = Math.max(maxWind, wind); maxSea = Math.max(maxSea, sea);
    const severity = Math.max(wind / MODEL_GAP.wind, sea / MODEL_GAP.sea);
    if (severity > largest) { largest = severity; worst = {ms, wind: round(wind), sea: round(sea)}; }
  }
  const hours = unique.length;
  return {state: !hours ? 'none' : !compared ? 'one-model' : differing ? 'differ' : compared === hours ? 'agree' : 'partial',
    hours, compared, differing, gap: compared ? {wind: round(maxWind), sea: round(maxSea)} : null, worst};
}
