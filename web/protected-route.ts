// SCFEAT-ROUTE-1: bounded, opt-in planning route. No position tracking, depth,
// hazard, tide or passage clearance. All edges (including snapped connectors
// and smoothing shortcuts) use the existing whole-geometry, 70 m screen.
import {waterRoute, type RoutePoint} from './route.ts';
import type {LandWaterLines, LandWaterModel} from './land-water.ts';
import {xml} from '../dist/gpx.js';

export interface RouteScreen {
  ready(): boolean;
  coversGeometry(g: unknown): boolean;
  geometryAllowed(g: unknown): boolean;
  exportExclusions(): {checked_at: string} | null;
}
export const ROUTE_WARNING = 'NOT FOR NAVIGATION. Planning only: no depth, hazards, tides or passage clearance. Check official charts and current rules.';
export const ROUTE_SOURCES = 'CDFW MPA boundaries: https://wildlife.ca.gov/Conservation/Marine/MPAs; NOAA supplemental closures where supplied: https://www.fisheries.noaa.gov/west-coast/sustainable-fisheries/west-coast-groundfish-closed-areas. Water routing: region NOAA shoreline land-water screen.';
// GPX lat/lon are xsd:decimal: spell JS exponent notation (1e-7) as plain digits, without rounding. Mirrors dist/gpx.js.
const dec = (v: number): string => {
  const s = String(v), m = /^(-?)(\d+)(?:\.(\d+))?[eE]([+-]?\d+)$/.exec(s);
  if (!m) return s;
  const [, sign, int, frac = '', exp] = m, digits = int! + frac, point = int!.length + Number(exp);
  return sign + (point <= 0 ? '0.' + '0'.repeat(-point) + digits
    : point >= digits.length ? digits + '0'.repeat(point - digits.length)
    : digits.slice(0, point) + '.' + digits.slice(point));
};
const geometry = (ps: readonly RoutePoint[]) => ps.length === 1
  ? {type:'Point', coordinates:[ps[0]!.longitude, ps[0]!.latitude]}
  : {type:'LineString', coordinates:ps.map(p=>[p.longitude,p.latitude])};

export function buildProtectedRoute({model, lines, screen, stops, title, now = new Date(), maxNodes = 40_000}: {
  model: LandWaterModel | null; lines: LandWaterLines | null | false; screen: RouteScreen;
  stops: readonly RoutePoint[]; title: string; now?: Date; maxNodes?: number;
}): {gpx: string; points: RoutePoint[]; checkedAt: string; nm: number} {
  const snapshot = screen?.exportExclusions?.(), checkedAt = snapshot?.checked_at;
  const age = now.getTime() - Date.parse(checkedAt ?? '');
  if (!screen?.ready?.() || !Number.isFinite(age) || age < -300_000 || age > 36*3600_000)
    throw Error('Current protected-area boundaries unavailable. Refresh before routing.');
  if (!Array.isArray(stops) || stops.length < 2 || stops.length > 12)
    throw Error('Choose 2–12 stops for the planning route, in visit order.');
  const allows = (ps: readonly RoutePoint[]): boolean => {
    const g = geometry(ps);
    return screen.coversGeometry(g) === true && screen.geometryAllowed(g) === true;
  };
  if (stops.some(p=>!Number.isFinite(p?.latitude) || !Number.isFinite(p?.longitude) || Math.abs(p.latitude)>85 || Math.abs(p.longitude)>180 || !allows([p])))
    throw Error('A route stop is outside the current boundary screen or within its protected-area margin.');
  const points: RoutePoint[] = [stops[0]!];
  let nm = 0;
  for (let i=1;i<stops.length;i++) {
    const r = waterRoute(model,lines,stops[i-1]!,stops[i]!,maxNodes,allows);
    if (!r.ok) throw Error(`Planning route unavailable for leg ${i} (${r.reason}). No straight-line fallback is exported.`);
    points.push(...r.points,stops[i]!); nm += r.nm;
  }
  if (points.length>3000 || !allows(points)) throw Error('Planning route unavailable: full-route check failed.');
  // Recheck at serialization; an expired or replaced boundary screen cannot export.
  if (!screen.ready() || screen.exportExclusions()?.checked_at !== checkedAt) throw Error('Protected-area boundaries changed. Try routing again.');
  const description = `${ROUTE_WARNING} Avoids screened polygons plus the 70 m planning margin. Boundary check: ${checkedAt}. ${ROUTE_SOURCES} Water-screen source: ${model?.source}.`;
  const gpx = `<?xml version="1.0" encoding="UTF-8"?>\n<gpx version="1.1" creator="SkipperCast" xmlns="http://www.topografix.com/GPX/1/1"><metadata><name>${xml(title)}</name><desc>${xml(description)}</desc><time>${now.toISOString()}</time></metadata><rte><name>${xml(title)}</name><desc>${xml(description)}</desc>${points.map(p=>`<rtept lat="${dec(p.latitude)}" lon="${dec(p.longitude)}"/>`).join('')}</rte></gpx>`;
  return {gpx,points,checkedAt:checkedAt!,nm};
}
