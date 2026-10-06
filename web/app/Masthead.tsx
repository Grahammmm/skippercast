// Masthead (FE-05, design § 6): brand, the location in mono (port name and
// centre from the region), the four views as ?view= links that navigate in
// place, the freshness dot with the oldest age, and sign in (v1's #account
// passkey dialog, dist/account.js, until the account menu moves into v2).
// The pieces are exported so the mobile shell (FE-06) composes the same
// brand, location, views and freshness into its top strip, sheet and tabs.
import {Icon, type IconName} from '../ui/icons.tsx';
import {APP_VIEWS, appView, region, setParams, withParams, type AppView} from '../state.ts';
import {freshness, regionInfo} from './App.tsx';

export const VIEW_LABELS: Readonly<Record<AppView, string>> = {coast: 'Coast', conditions: 'Conditions', history: 'History', fleet: 'Fleet', reports: 'Reports'};
/** The tab icons of the mobile nav (§ 6 mobile). */
export const VIEW_ICONS: Readonly<Record<AppView, IconName>> = {coast: 'map', conditions: 'wind', history: 'history', fleet: 'fleet', reports: 'chart'};
/** The masthead's views; Reports is a Phase 4 page and is not listed. */
export const MASTHEAD_VIEWS: readonly AppView[] = APP_VIEWS.filter(v => v !== 'reports');
const FRESHNESS_LABEL = {ok: 'Every reading is fresh', stale: 'A reading is stale', offline: 'Offline', unknown: 'No readings yet'} as const;

/** The ?view= value for a masthead view: coast is the default and is not written. */
export const viewParam = (v: AppView): string | null => (v === 'coast' ? null : v);

/** "35.34N 120.97W" for a [latitude, longitude] centre. */
export const coordinates = ([lat, lon]: readonly [number, number]): string =>
  `${Math.abs(lat).toFixed(2)}${lat < 0 ? 'S' : 'N'} ${Math.abs(lon).toFixed(2)}${lon < 0 ? 'W' : 'E'}`;

/** "Morro Bay" for a region id, until the region's name loads. */
export const titleCase = (id: string): string => id.split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');

export function Brand() {
  return (
    <a class="app-brand" href="/">
      <Icon name="compass" size={22} />
      <span>SkipperCast</span>
    </a>
  );
}

export function Location() {
  const info = regionInfo.value;
  return (
    <span class="app-location ui-mono" data-region={region.value ?? ''}>
      {info ? `${info.name} ${coordinates(info.center)}` : region.value ? `${titleCase(region.value)} —` : 'No port chosen'}
    </span>
  );
}

/** The views as ?view= links; `icons` adds each view's tab icon (the mobile nav). */
export function ViewNav({href, icons = false, class: cls}: {href?: string; icons?: boolean; class?: string} = {}) {
  const current = appView.value;
  const base = href ?? (typeof location === 'undefined' ? 'https://skippercast.com/map' : location.href);
  return (
    <nav aria-label="Views" class={cls}>
      <ul class="app-views">
        {MASTHEAD_VIEWS.map(v => (
          <li key={v}>
            <a href={withParams(base, {view: viewParam(v)})} aria-current={v === current ? 'page' : undefined} data-view={v}
              onClick={event => { event.preventDefault(); setParams({view: viewParam(v)}); }}>
              {icons ? <Icon name={VIEW_ICONS[v]} size={18} /> : null}{VIEW_LABELS[v]}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function FreshnessDot() {
  const fresh = freshness.value;
  return (
    <span class="app-fresh" role="status" data-state={fresh.state} aria-label={`Freshness: ${FRESHNESS_LABEL[fresh.state]}`}>
      <span class="app-fresh-dot" aria-hidden="true"></span>
      <span class="ui-mono">{fresh.age ?? '—'}</span>
    </span>
  );
}

export function SignIn() {
  return <a class="ui-button ui-button--quiet" href="/#account"><Icon name="user" size={18} />Sign in</a>;
}

export function Masthead({href}: {href?: string} = {}) {
  return (
    <header class="app-masthead">
      <Brand />
      <Location />
      <ViewNav href={href} />
      <FreshnessDot />
      <SignIn />
    </header>
  );
}
