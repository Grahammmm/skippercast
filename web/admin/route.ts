// The admin app's hash routes (08 § Admin; TA-W2, TA-W3). Plain TypeScript so the
// Node tests load it. Views are #queue, #skippers, #rules, #posts, #funnel and
// #health; #contact/<id> opens one contact (by id only: there is no search by
// number); #rules?jurisdiction=<id> opens the Rules view on one jurisdiction
// (TA-A4, from a rule-change card). The charter fleet's views (charter-fleet
// design § 13) register below, one line per view: #<fleet view>?region=<id> and
// #<fleet detail>/<id>. Anything else is the queue.
import type {AdminView} from '../advisor/copy.ts';

export const VIEWS: readonly AdminView[] = ['queue', 'skippers', 'rules', 'posts', 'funnel', 'health'];

// ---- Charter fleet views, shown only while the fleet flag is on (one line per view) ----
export const FLEET_VIEWS = [
  'fleet-review', 'fleet-vessels',   // CF-31
  'fleet-operators',   // CF-32
  'fleet-coverage', 'fleet-ais',   // CF-35
] as const;
/** Fleet detail routes, #<head>/<id>: the list view the nav marks, and the id's pattern. */
export const FLEET_DETAILS = {
  'fleet-vessel': {nav: 'fleet-vessels', id: /^[0-9a-f]{32}$/},   // CF-31
  'fleet-operator': {nav: 'fleet-operators', id: /^[A-Za-z0-9_-]{16,64}$/},   // CF-32
} as const;
// ---- end of the fleet views ----

export type FleetView = typeof FLEET_VIEWS[number];
export type FleetDetail = keyof typeof FLEET_DETAILS;
export type RouteView = AdminView | 'contact' | FleetView | FleetDetail;
export interface Route {view: RouteView; arg: string}
const REGION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?$/;   // a regions/<id> directory name, as the server checks it
const DETAILS: Readonly<Record<string, {nav: FleetView; id: RegExp}>> = FLEET_DETAILS;
export const isFleetView = (view: string): view is FleetView => (FLEET_VIEWS as readonly string[]).includes(view);
const detailOf = (head: string): {nav: FleetView; id: RegExp} | undefined => (Object.hasOwn(DETAILS, head) ? DETAILS[head] : undefined);

/** The view a hash names: one of VIEWS or FLEET_VIEWS, contact/<id>, a fleet detail, or rules with a jurisdiction; anything else is the queue. */
export function routeOf(hash: string): Route {
  const [path = '', query = ''] = hash.replace(/^#/, '').split('?', 2);
  if (path === 'rules') {
    const jurisdiction = new URLSearchParams(query).get('jurisdiction') ?? '';
    return {view: 'rules', arg: /^[a-z][a-z-]{1,60}$/.test(jurisdiction) ? jurisdiction : ''};
  }
  if (isFleetView(path)) {
    const region = new URLSearchParams(query).get('region') ?? '';
    return {view: path, arg: REGION.test(region) ? region : ''};
  }
  const [head = '', ...rest] = path.split('/');
  let id = '';
  try { id = rest.length === 1 ? decodeURIComponent(rest[0]!) : ''; } catch { /* a malformed escape is no id */ }
  if (head === 'contact' && /^[\w-]{1,64}$/.test(id)) return {view: 'contact', arg: id};
  const detail = detailOf(head);
  if (detail && detail.id.test(id)) return {view: head as FleetDetail, arg: id};
  return {view: (VIEWS as readonly string[]).includes(head) ? head as AdminView : 'queue', arg: ''};
}

/** The admin app's link to the Rules view, on one jurisdiction when given. */
export const rulesHref = (jurisdiction?: string | null): string => (jurisdiction ? `#rules?jurisdiction=${encodeURIComponent(jurisdiction)}` : '#rules');

/** The nav entry a route marks as current: a contact belongs to Skippers, a fleet detail to its list. */
export function navOf(view: RouteView): AdminView | FleetView {
  if (view === 'contact') return 'skippers';
  return detailOf(view)?.nav ?? view as AdminView | FleetView;
}

/** The features the admin app shows views for: advisor (the Health API answers) and fleet (the fleet API answers). */
export interface AdminFlags {advisor: boolean; fleet: boolean}

/** The nav entries the flags allow: the advisor's views, then the fleet's. */
export const visibleViews = (flags: AdminFlags): (AdminView | FleetView)[] => [...(flags.advisor ? VIEWS : []), ...(flags.fleet ? FLEET_VIEWS : [])];

/** The route to render: the hash's own when its feature is on, else the first view the flags allow, or null when none is. */
export function shownRoute(route: Route, flags: AdminFlags): Route | null {
  const visible = visibleViews(flags);
  if (visible.includes(navOf(route.view))) return route;
  const first = visible[0];
  return first ? {view: first, arg: ''} : null;
}

/** The admin app's link to a fleet list view, on one region when given. */
export const fleetHref = (view: FleetView, region?: string | null): string => (region ? `#${view}?region=${encodeURIComponent(region)}` : `#${view}`);
/** The admin app's link to one registry vessel. */
export const fleetVesselHref = (id: string): string => `#fleet-vessel/${encodeURIComponent(id)}`;
