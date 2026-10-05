// The SkipperCast admin app (docs/plans/text-advisor/08-website.md § Admin;
// TA-W2), mounted by dist/admin.html, which the Worker serves to admins only.
// Hash-routed views: #queue and #health (TA-W2), #skippers and
// #contact/<id> (TA-W3, a contact opens by id only, from a review or a boat);
// #funnel (TA-W4); #rules and #rules?jurisdiction=<id> (TA-A4); #posts
// (TA-S1, the social drafts). The relay-down banner shows on every view: health is fetched on load
// and every minute. Every string is in web/advisor/copy.ts (ADMIN_COPY).
//
// The charter fleet's views (charter-fleet design § 13) dispatch through FLEET_PAGES,
// one line per route, and show only while the fleet API answers (FLEET_ENABLED); the
// advisor's views show only while its Health API answers (the admin opens with either
// feature on, CF-01). Fleet strings live in the fleet views' own copy modules.
import {render} from 'preact';
import type {JSX} from 'preact';
import {useEffect, useState} from 'preact/hooks';
import {ADMIN_COPY as COPY} from '../advisor/copy.ts';
import type {AdminView} from '../advisor/copy.ts';
import {ApiError, getFleetEnabled, getHealth, when} from './api.ts';
import type {Health} from './api.ts';
import {Queue} from './queue.tsx';
import {HealthView} from './health.tsx';
import {Skippers} from './skippers.tsx';
import {ContactView} from './contact.tsx';
import {FunnelView} from './funnel.tsx';
import {RulesView} from './rules.tsx';
import {PostsView} from './posts.tsx';
import {FLEET_COPY} from './fleet-copy.ts';
import {FleetReviewView} from './fleet-review.tsx';
import {FleetVessels, FleetVesselView} from './fleet-vessels.tsx';
import {FleetOperatorsView, FleetOperatorView, OPERATORS_LABEL} from './fleet-operators.tsx';   // CF-32
import {navOf, routeOf, shownRoute, visibleViews} from './route.ts';
import type {AdminFlags, FleetDetail, FleetView, Route, RouteView} from './route.ts';

/** The fleet's routes: the nav (and title) label and the view; arg is the ?region= of a list view or a detail's id. */
const FLEET_PAGES: Record<FleetView | FleetDetail, {label: string; render: (arg: string) => JSX.Element}> = {
  'fleet-review': {label: FLEET_COPY.views['fleet-review'], render: region => <FleetReviewView region={region} />},   // CF-31
  'fleet-vessels': {label: FLEET_COPY.views['fleet-vessels'], render: region => <FleetVessels region={region} />},   // CF-31
  'fleet-vessel': {label: FLEET_COPY.views['fleet-vessels'], render: id => <FleetVesselView key={id} id={id} />},   // CF-31
  'fleet-operators': {label: OPERATORS_LABEL, render: region => <FleetOperatorsView region={region} />},   // CF-32
  'fleet-operator': {label: OPERATORS_LABEL, render: id => <FleetOperatorView key={id} id={id} />},   // CF-32
};
const fleetPage = (view: RouteView) => (Object.hasOwn(FLEET_PAGES, view) ? FLEET_PAGES[view as FleetView | FleetDetail] : undefined);
const labelOf = (view: AdminView | FleetView): string => fleetPage(view)?.label ?? COPY.views[view as AdminView];

export const HEALTH_EVERY_MS = 60000;
export function App() {
  const [route, setRoute] = useState<Route>(() => routeOf(location.hash));
  const [health, setHealth] = useState<Health | null>(null);
  const [healthFailed, setHealthFailed] = useState(false);
  const [advisor, setAdvisor] = useState<boolean | null>(null);   // null until the first Health answer
  const [fleet, setFleet] = useState<boolean | null>(null);       // null until the fleet API answers
  const [signedOut, setSignedOut] = useState(false);   // 401; both APIs answering 404 (no admin view at all) reads the same way

  async function refresh(): Promise<void> {
    try { setHealth(await getHealth()); setHealthFailed(false); setAdvisor(true); }
    catch (e) {
      setHealthFailed(true);
      if (e instanceof ApiError && e.status === 401) setSignedOut(true);
      // The advisor's admin API answers 404 while the advisor is off; anything else leaves its views up.
      setAdvisor(!(e instanceof ApiError && e.status === 404));
    }
  }
  useEffect(() => {
    const onHash = (): void => setRoute(routeOf(location.hash));
    addEventListener('hashchange', onHash);
    void refresh();
    getFleetEnabled().then(setFleet, () => setFleet(false));
    const timer = setInterval(() => void refresh(), HEALTH_EVERY_MS);
    return () => { removeEventListener('hashchange', onHash); clearInterval(timer); };
  }, []);

  const flags: AdminFlags | null = advisor === null || fleet === null ? null : {advisor, fleet};
  const shown = flags ? shownRoute(route, flags) : null;
  const view = shown?.view ?? route.view, nav = navOf(view);
  useEffect(() => { document.title = `${view === 'contact' ? COPY.contactHeading : labelOf(nav)} · ${COPY.pageTitle}`; }, [view, nav]);
  const page = shown ? fleetPage(shown.view) : undefined;

  return (
    <>
      <header class="admin-top">
        <p class="admin-brand"><a href="/">⌁ {COPY.brand}</a></p>
        <nav aria-label={COPY.navLabel}>
          <ul>
            {(flags ? visibleViews(flags) : []).map(v => <li key={v}><a href={`#${v}`} aria-current={v === nav ? 'page' : undefined}>{labelOf(v)}</a></li>)}
          </ul>
        </nav>
      </header>
      {health?.relay?.state === 'down' ? <p class="admin-banner" role="alert">{COPY.relayDown(when(health.relay.last_ok_at) || COPY.relayNever)}</p> : null}
      <main class="admin-main">
        {signedOut || (flags && !shown) ? <p class="admin-error" role="alert">{COPY.signedOut}</p>
          : !shown ? <p>{COPY.loading}</p>
          : page ? page.render(shown.arg)
          : shown.view === 'queue' ? <Queue />
          : shown.view === 'health' ? <HealthView health={health} failed={healthFailed} onRefresh={() => void refresh()} />
          : shown.view === 'skippers' ? <Skippers />
          : shown.view === 'contact' ? <ContactView id={shown.arg} />
          : shown.view === 'funnel' ? <FunnelView />
          : shown.view === 'rules' ? <RulesView jurisdiction={shown.arg} />
          : <PostsView />}
      </main>
    </>
  );
}

const host = typeof document === 'undefined' ? null : document.getElementById('admin-app');
if (host) { host.replaceChildren(); render(<App />, host); }
