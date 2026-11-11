// Masthead (FE-05, design § 6): brand, the location in mono (port name and
// centre from the region), the views as ?view= links that navigate in
// place (FE-52 adds Reports), the freshness dot with the oldest age, and the account menu (FE-50:
// sign in through v1's passkey dialog, the boat, trip alerts, downloads).
// The pieces are exported so the mobile shell (FE-06) composes the same
// brand, location, views and freshness into its top strip, sheet and tabs.
// FE-55: the chat entry links to the Text Advisor's web chat, and only while
// the advisor is on (SC0452-02: read from the shared /api/session answer).
import {useEffect} from 'preact/hooks';
import {CHAT_PATH} from '../advisor/entry.ts';
import {language, t, type Language} from '../i18n.ts';
import {Icon, type IconName} from '../ui/icons.tsx';
import {ensureSession, session} from '../account.ts';
import {appView, navigate, region, withParams, type AppView} from '../state.ts';
import {currentRegionInfo, freshness, regionLoad, retryRegion} from './App.tsx';
import {AccountMenu} from './AccountMenu.tsx';
import {DegradedNotice} from '../degraded-notice.tsx';
import {loadRegionPorts} from '../ports.ts';
import {currentRegionPreview} from '../region-preview.ts';

/** A view's name in `lang` (the catalogue's shell.view.*); rendering passes the language it reads from the signal. */
export const viewLabel = (view: AppView, lang: Language = 'en'): string => t(`shell.view.${view}`, lang);
/** The English names, kept for callers that compare against them; the catalogue is their source. */
export const VIEW_LABELS: Readonly<Record<AppView, string>> = {coast: viewLabel('coast'), conditions: viewLabel('conditions'), history: viewLabel('history'), fleet: viewLabel('fleet'), reports: viewLabel('reports'), plan: viewLabel('plan')};
/** The tab icons of the mobile nav (§ 6 mobile). */
export const VIEW_ICONS: Readonly<Record<AppView, IconName>> = {coast: 'map', conditions: 'wind', history: 'history', fleet: 'fleet', reports: 'chart', plan: 'chart'};
/** The masthead's views: all five (FE-52 adds Reports). */
export const MASTHEAD_VIEWS: readonly AppView[] = ['coast', 'conditions', 'history', 'fleet', 'reports'];
/** The mobile nav's four tabs (§ 6 mobile). Fleet leaves the bar while it has nothing a user can act on
 * (G 2026-11-01, AIS research-only); re-add it when it does. It stays on the desktop masthead and at ?view=fleet. */
export const TAB_VIEWS: readonly AppView[] = ['coast', 'conditions', 'history', 'reports'];


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
  const id = region.value, preview = currentRegionPreview();
  useEffect(() => { if (id) void loadRegionPorts(id); }, [id]);
  const info = currentRegionInfo();
  const load = regionLoad.value;
  const state = load?.id === region.value ? load.state : null;
  const missing = state === 'missing', lang = language.value;
  const location = <span class="app-location ui-mono" data-region={id ?? ''}>
    {info ? <>{info.name} <span class="app-location-coords">{coordinates(info.center)}</span></> : missing ? `"${id}"` : id ? `${titleCase(id)} —` : t('shell.location.none', lang)}
  </span>;
  return (
    <>
      {preview ? <span class="app-location-preview">
        <span class="app-location-preview-line">
          {location}
          <span class="app-region-preview-label">{t('shell.regionPreview.label', lang)}</span>
        </span>
        <span class="app-region-preview-reason">{t('shell.regionPreview.reason', lang)}</span>
      </span> : location}
      {state === 'loading' ? <span role="status">{t('shell.location.loading', lang)}</span> : null}
      {state === 'error' ? <span role="status">{t('shell.location.error', lang)}{' '}<button type="button" onClick={retryRegion}>{t('shell.location.retry', lang)}</button></span> : null}
      {missing ? <span role="status">{t('shell.location.missing', lang, {region: region.value ?? ''})}{' '}<a href="/">{t('shell.location.choose', lang)}</a></span> : null}
    </>
  );
}

/** The views as ?view= links; `icons` adds each view's tab icon and lists the four tabs (the mobile nav). */
export function ViewNav({href, icons = false, class: cls}: {href?: string; icons?: boolean; class?: string} = {}) {
  const current = appView.value, lang = language.value;
  const base = href ?? (typeof location === 'undefined' ? 'https://skippercast.com/map' : location.href);
  return (
    <nav aria-label={t('shell.views', lang)} class={cls}>
      <ul class="app-views">
        {(icons ? TAB_VIEWS : MASTHEAD_VIEWS).map(v => (
          <li key={v}>
            <a href={withParams(base, {view: viewParam(v)})} aria-current={v === current ? 'page' : undefined} data-view={v}
              onClick={event => { event.preventDefault(); if (appView.value !== v) navigate(withParams(location.href, {view: viewParam(v)})); }}>
              {icons ? <Icon name={VIEW_ICONS[v]} size={18} /> : null}{viewLabel(v, lang)}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}

export function FreshnessDot() {
  const fresh = freshness.value, lang = language.value;
  const state = {ok: t('shell.fresh.ok', lang), stale: t('shell.fresh.stale', lang), offline: t('shell.fresh.offline', lang), unknown: t('shell.fresh.unknown', lang)}[fresh.state];
  return (
    <span class="app-fresh" role="status" data-state={fresh.state} aria-label={t('shell.fresh', lang, {state})}>
      <span class="app-fresh-dot" aria-hidden="true"></span>
      {fresh.state === 'offline' ? <span data-fresh-offline>{state}</span> : null}
      <span class="ui-mono">{fresh.age ?? '—'}</span>
    </span>
  );
}

// SC1322-06: the notice lives in web/degraded-notice.tsx, shared with the landing; /map's imports are unchanged.
export {DegradedNotice};

/**
 * The chat entry: nothing until the shared session read (web/account.ts ensureSession, the one the account menu
 * also makes) says the advisor gate is open. SC0452-02: the answer rides on GET /api/session, so there is no
 * HEAD /chat.html probe; loading, offline and a failed refresh show nothing. The gate stays the authority.
 */
export function ChatEntry() {
  useEffect(() => { void ensureSession(); }, []);
  const current = session.value, lang = language.value;
  return current.state !== 'loading' && current.state !== 'offline' && current.advisor
    ? <a class="ui-button ui-button--quiet" href={CHAT_PATH} data-advisor-entry>{t('shell.chat', lang)}</a> : null;
}

export function Masthead({href}: {href?: string} = {}) {
  return (
    <header class="app-masthead">
      <Brand />
      <Location />
      <ViewNav href={href} />
      <FreshnessDot />
      <DegradedNotice />
      <ChatEntry />
      <AccountMenu />
    </header>
  );
}
