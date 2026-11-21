import type {Route, RoutePoint} from '../route.ts';

const RAD = Math.PI / 180;

function initialBearing(from: RoutePoint, to: RoutePoint, deltaLongitude: number): number {
  const a = from.latitude * RAD, b = to.latitude * RAD, d = deltaLongitude * RAD;
  const east = Math.sin(d) * Math.cos(b);
  const north = Math.cos(a) * Math.sin(b) - Math.sin(a) * Math.cos(b) * Math.cos(d);
  return (Math.round(Math.atan2(east, north) / RAD) + 360) % 360;
}

/** Initial great-circle courses between the route's snapped ends, not along its first or last leg. */
export function runBearings(route: Route): {out: number | null; back: number | null} {
  const unavailable = {out: null, back: null};
  if (!route.ok || route.points.length < 2) return unavailable;
  if (!route.points.every(p => Number.isFinite(p.latitude) && Number.isFinite(p.longitude))) return unavailable;

  const start = route.points[0]!, end = route.points[route.points.length - 1]!;
  const delta = (end.longitude % 360 - start.longitude % 360) % 360;
  const bothPoles = Math.abs(start.latitude) === 90 && Math.abs(end.latitude) === 90;
  if (start.latitude === end.latitude && (delta === 0 || bothPoles)) return unavailable;
  // Antipodal ends have no unique initial course either.
  if (start.latitude === -end.latitude && (Math.abs(delta) === 180 || bothPoles)) return unavailable;

  return {out: initialBearing(start, end, delta), back: initialBearing(end, start, -delta)};
}
