import type {Profile} from '../profile.ts';
import type {Route} from '../route.ts';
import {runBearings} from './heading.ts';

type Mark = {deg: number; wedge: number};
type HeadingCardPlan =
  | {show: false; reason: 'not-boat'}
  | {show: true; out: Mark | null; back: Mark | null};

export function wedgeOf(bearing: number): number | null {
  if (!Number.isFinite(bearing)) return null;
  const remainder = bearing % 360;
  const b = remainder < 0 ? (remainder + 360) % 360 : remainder || 0;
  return Math.round(b / 45) % 8;
}

function mark(deg: number | null): Mark | null {
  // A non-null result from runBearings is a whole, finite course.
  return deg === null ? null : {deg, wedge: wedgeOf(deg)!};
}

export function headingCardPlan(profile: Profile, route: Route | null): HeadingCardPlan {
  if (profile !== 'boat') return {show: false, reason: 'not-boat'};
  if (route === null) return {show: true, out: null, back: null};
  const {out, back} = runBearings(route);
  return {show: true, out: mark(out), back: mark(back)};
}
