// Static shoreline (FE-07, design § 7 and § 13): the default region's NOAA
// CUSP shoreline (catalog/shoreline/, projected by
// scripts/build_landing_shoreline.mjs) drawn inline behind the hero with the
// glow treatment: a blurred wide stroke under a fine one, coloured by
// landing.css. Decorative, so hidden from assistive technology. FE-25 keeps
// it as the fallback under the live map.
import {SHORELINE} from './shoreline-path.ts';

export function Shoreline() {
  return (
    <svg class="landing-shore" viewBox={SHORELINE.viewBox} preserveAspectRatio="xMaxYMid slice" aria-hidden="true" focusable="false">
      <defs>
        <filter id="landing-glow" x="-5%" y="-5%" width="110%" height="110%">
          <feGaussianBlur stdDeviation="3" />
        </filter>
      </defs>
      <path class="landing-shore-glow" d={SHORELINE.d} filter="url(#landing-glow)" />
      <path class="landing-shore-line" d={SHORELINE.d} />
    </svg>
  );
}

/** The footer credit, from the generated module, so it always names the drawn extract's source and survey years. */
export function ShorelineCredit() {
  const [first, last] = [SHORELINE.sourceYears[0], SHORELINE.sourceYears.at(-1)];
  const years = first === last ? first : `${first}–${last}`;
  return <p class="landing-credit">Shoreline: {SHORELINE.attribution}, surveyed {years}.</p>;
}
