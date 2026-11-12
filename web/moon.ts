// The moon's phase for an instant (SC2037-03). Pure: no imports, no clock, no network.
//
// Algorithm: Jean Meeus, "Astronomical Algorithms", 2nd ed., chapter 48 ("Illuminated Fraction of the
// Moon's Disk"), equation 48.4: the phase angle i from the mean elongation D (47.2), the Sun's mean
// anomaly M (47.3) and the Moon's mean anomaly M' (47.4) with the six-term correction, and the
// illuminated fraction k = (1 + cos i) / 2 (48.1). Stated accuracy: i is good to about 0.3 degrees, so the
// fraction is good to about 0.5 percentage points and the elongation, hence a phase time, to under an hour.
// Time is taken as UT (the ~70 s difference from dynamical time is far inside that).
// This is the phase only: no rise or set, no tide or fishing claim.

export type PhaseName = 'new' | 'waxing crescent' | 'first quarter' | 'waxing gibbous' | 'full' | 'waning gibbous' | 'last quarter' | 'waning crescent';
export interface MoonPhase {readonly name: PhaseName; readonly fraction: number}

const RAD = Math.PI / 180;
const norm = (deg: number): number => ((deg % 360) + 360) % 360;
const DAY_MS = 86400000;
/** Signed circular difference in degrees, [-180, 180). */
const wrap = (deg: number): number => ((deg + 180) % 360 + 360) % 360 - 180;
const PHASES: readonly PhaseName[] = ['new', 'waxing crescent', 'first quarter', 'waxing gibbous', 'full', 'waning gibbous', 'last quarter', 'waning crescent'];

/** The Moon's elongation east of the Sun in degrees, [0, 360): 0 new, 90 first quarter, 180 full, 270 last quarter. */
export function elongation(at: Date): number {
  const t = (at.getTime() / 86400000 + 2440587.5 - 2451545) / 36525;
  const d = norm(297.8501921 + 445267.1114034 * t - 0.0018819 * t * t + t ** 3 / 545868 - t ** 4 / 113065000);
  const m = norm(357.5291092 + 35999.0502909 * t - 0.0001536 * t * t) * RAD;
  const mp = norm(134.9633964 + 477198.8675055 * t + 0.0087414 * t * t) * RAD;
  const dr = d * RAD;
  // i = 180 - D - 6.289 sin M' + 2.100 sin M - 1.274 sin(2D - M') - 0.658 sin 2D - 0.214 sin 2M' - 0.110 sin D; elongation = 180 - i.
  return norm(d + 6.289 * Math.sin(mp) - 2.100 * Math.sin(m) + 1.274 * Math.sin(2 * dr - mp) + 0.658 * Math.sin(2 * dr) + 0.214 * Math.sin(2 * mp) + 0.110 * Math.sin(dr));
}

/** The phase name and illuminated fraction (0..1) at `at`. Within one day of a principal phase it is that phase. */
export function moonPhase(at: Date): MoonPhase {
  const e = elongation(at);
  const fraction = (1 - Math.cos(e * RAD)) / 2;
  const q = Math.round(e / 90);
  // "Within one day" is elapsed time: the modelled elongation reaches the nearest principal angle between at - 1 day and at + 1 day.
  const target = wrap(q * 90 - e);
  const near = wrap(elongation(new Date(at.getTime() - DAY_MS)) - e) <= target && target <= wrap(elongation(new Date(at.getTime() + DAY_MS)) - e);
  const name = near ? PHASES[(q * 2) % 8]! : PHASES[Math.floor(e / 90) * 2 + 1]!;
  return {name, fraction};
}

/** The instant of 12:00 local time on `day` ("YYYY-MM-DD") in the IANA zone `tz`. */
export function localNoon(day: string, tz: string): Date {
  const [y, mo, d] = day.split('-').map(Number) as [number, number, number];
  const guess = Date.UTC(y, mo - 1, d, 12);
  const f = new Intl.DateTimeFormat('en-US', {timeZone: tz, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric'});
  const offset = (ms: number): number => {
    const p = Object.fromEntries(f.formatToParts(new Date(ms)).map(x => [x.type, x.value]));
    return Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute)) - ms;
  };
  const first = guess - offset(guess);
  return new Date(guess - offset(first));
}

/** "Moon: waxing gibbous, 78% lit" for the local day `day` in `tz`, taken at local noon. */
export function moonLine(day: string, tz: string): string {
  const {name, fraction} = moonPhase(localNoon(day, tz));
  return `Moon: ${name}, ${Math.round(fraction * 100)}% lit`;
}
