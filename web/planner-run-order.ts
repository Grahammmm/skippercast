import {distanceM} from '../dist/geo-screen.js';

type Point = {lat: number; lon: number};
type Stop = Point & {id: string};
const finite = ({lat, lon}: Point) => Number.isFinite(lat) && Number.isFinite(lon);
const coordinates = ({lat, lon}: Point) => ({type: 'Point', coordinates: [lon, lat]});

/** Shorten the straight-line itinerary without changing the chosen stops. */
export function shorterRunOrder(stops: readonly Stop[], start: Point | null): {
  ids: string[]; totalNm: number; improved: boolean;
} {
  const ids = stops.map(stop => stop.id);
  if (stops.some(stop => !finite(stop)) || (stops.length > 0 && start && !finite(start))) {
    return {ids, totalNm: NaN, improved: false};
  }

  const points = stops.map(coordinates);
  const origin = start && coordinates(start);
  const input = stops.map((_, i) => i);
  // Index -1 represents the origin, or an uncharged endpoint on an open path.
  const leg = (a: number, b: number): number => {
    const from = a === -1 ? origin : points[a]!;
    const to = b === -1 ? origin : points[b]!;
    return from && to ? distanceM(from, to)! / 1852 : 0;
  };
  const total = (order: readonly number[]) => {
    let nm = 0, previous = -1;
    for (const stop of order) {
      nm += leg(previous, stop);
      previous = stop;
    }
    return order.length ? nm + leg(previous, -1) : 0;
  };
  const inputNm = total(input);
  if (stops.length <= 2) return {ids, totalNm: inputNm, improved: false};

  const remaining = [...input];
  const order = origin ? [] : [remaining.shift()!];
  while (remaining.length) {
    const previous = order.at(-1) ?? -1;
    let best = 0, nearest = leg(previous, remaining[0]!);
    for (let i = 1; i < remaining.length; i++) {
      const nm = leg(previous, remaining[i]!);
      if (nm < nearest) {
        best = i;
        nearest = nm;
      }
    }
    order.push(remaining.splice(best, 1)[0]!);
  }

  // Take the first shortening 2-opt reversal, then restart. A path without
  // an origin locks its first stop but can still change its final stop.
  let candidate = order, candidateNm = total(candidate);
  search: for (;;) {
    for (let i = origin ? 0 : 1; i < candidate.length - 1; i++) {
      const before = candidate[i - 1] ?? -1, first = candidate[i]!;
      for (let j = i + 1; j < candidate.length; j++) {
        const last = candidate[j]!, after = candidate[j + 1] ?? -1;
        const oldEdges = leg(before, first) + leg(last, after);
        const newEdges = leg(before, last) + leg(first, after);
        // Don't reorder ties due to roundoff in equivalent edge sums.
        if (!(oldEdges - newEdges > 8 * Number.EPSILON * oldEdges)) continue;
        const reversed = [...candidate.slice(0, i), ...candidate.slice(i, j + 1).reverse(), ...candidate.slice(j + 1)];
        const nm = total(reversed);
        // Guard against roundoff: the summed planner distance must fall too.
        if (nm < candidateNm) {
          candidate = reversed;
          candidateNm = nm;
          continue search;
        }
      }
    }
    break;
  }

  return candidateNm < inputNm
    ? {ids: candidate.map(i => ids[i]!), totalNm: candidateNm, improved: true}
    : {ids, totalNm: inputNm, improved: false};
}
