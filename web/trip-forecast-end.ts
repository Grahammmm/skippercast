// The Trip dialog's line saying how far a saved pack's forecast reaches, from the pack's own `forecast_end` (dist/offline-pack.js).
// Erasable syntax only (tests import it by type stripping).
import type {PackMeta} from './trip.ts';
import {frameTime} from './map/currents.ts';
import {DEFAULT_ZONE} from './zone.ts';

/** "Forecast saved through Sat 2 pm" in the region zone, the ended words once `now` reaches it, or "not recorded" when absent or unreadable. */
export function forecastEndLine(meta: Pick<PackMeta, 'forecast_end'>, now: Date, zone: string = DEFAULT_ZONE): string {
  const end = typeof meta.forecast_end === 'string' ? Date.parse(meta.forecast_end) : NaN;
  if (!Number.isFinite(end)) return 'Forecast end not recorded';
  return end > now.getTime() ? `Forecast saved through ${frameTime(meta.forecast_end!, zone)}` : 'The saved forecast has ended; save again with a connection';
}
