// Account menu (FE-50, design § 6 and § 7, US-R5): the masthead's sign in
// becomes one disclosure holding the account (v1's passkey dialog), the boat
// (first-run.js presets and the exact-boat sheet), saved-trip alerts (TripAlerts.tsx) and the
// take-it-with-you entries. A real button with aria-expanded; opening moves
// focus into the panel, arrows and Home/End move between its controls,
// Escape closes it and returns focus to the button; clicking or focusing
// outside closes it without moving focus back.
// The account and boat actions are web/account.ts, which wraps the v1 modules
// unchanged; the alerts are web/alerts.ts; the trip plan and the offline
// section are web/trip.ts (FE-51).
import {useEffect, useId, useRef, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Icon} from '../ui/icons.tsx';
import {PortDialog} from '../landing/PortInput.tsx';
import {language, t, type StringId} from '../i18n.ts';
import {accountLabel, boat, choosePreset, ensureSession, followAccountHash, followAlertsHash, loadBoat, openAccountDialog, openBoatSheet, session, type Session} from '../account.ts';
import {coordinates, region, setCoordinateFormat, species} from '../state.ts';
import {offlineOpen, openTrip, tripIds} from '../trip.ts';
import {tourTransition, type TourAction, type TourState} from '../tour.ts';
import {ControlsTour} from './ControlsTour.tsx';
import {LanguageChoice} from './LanguageChoice.tsx';

/** The catalogue id of the line under the account heading, by session state. */
const ACCOUNT_LINE: Readonly<Record<Session['state'], StringId>> = {
  'loading': 'accountMenu.state.loading',
  'offline': 'accountMenu.state.offline',
  'disabled': 'accountMenu.state.disabled',
  'signed-out': 'accountMenu.state.signedOut',
  'signed-in': 'accountMenu.state.signedIn',
};
/** The boat presets the catalogue names; a preset it does not know keeps the label the boat module supplied. */
const PRESET_IDS: Readonly<Record<string, StringId>> = {
  skiff: 'accountMenu.preset.skiff', console: 'accountMenu.preset.console', walkaround: 'accountMenu.preset.walkaround', cabin: 'accountMenu.preset.cabin',
};
const COORDINATE_LABELS = [['dd', 'accountMenu.coordinates.dd'], ['ddm', 'accountMenu.coordinates.ddm'], ['dms', 'accountMenu.coordinates.dms']] as const;
const FOCUSABLE = 'button:not([disabled]), a[href]';

type AlertsView = typeof import('./TripAlerts.tsx').TripAlerts;
/** The alerts dialog's body loads on first open, so the app entry carries none of it. */
function LazyAlerts({regionId}: {regionId: string}) {
  const [View, setView] = useState<{c: AlertsView} | null>(null);
  const [failed, setFailed] = useState(false), lang = language.value;
  useEffect(() => { import('./TripAlerts.tsx').then(m => setView({c: m.TripAlerts}), () => setFailed(true)); }, []);
  return View ? <View.c regionId={regionId} target={species.peek()} /> : <p role="status">{t(failed ? 'accountMenu.alertsError' : 'accountMenu.alertsLoading', lang)}</p>;
}

/** `inline`: the panel opens in the flow (the mobile sheet's footer) instead of under the button. `top`: the phone's top-card entry (UXFIX-10), the icon-sized trigger of RF2345-7 at every width; its panel exists only while open, so the page never holds two menus' regions. */
export function AccountMenu({inline = false, top = false}: {inline?: boolean; top?: boolean} = {}) {
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState(false);
  const [tour, setTour] = useState<TourState>(null);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), panel = useRef<HTMLDivElement>(null), tourWasOpen = useRef(false);
  const id = useId();
  const s = session.value, b = boat.value, regionId = region.value, lang = language.value;

  useEffect(() => {
    void ensureSession();
    const stopAccount = followAccountHash(() => { setOpen(false); setAlerts(false); });
    const stopAlerts = followAlertsHash(has => has ? setAlerts(true) : setOpen(true), () => region.peek() !== null);
    return () => { stopAccount(); stopAlerts(); };
  }, []);
  useEffect(() => {
    if (!open) return;
    void loadBoat().catch(() => undefined);
    panel.current?.querySelector<HTMLElement>(FOCUSABLE)?.focus();
    const away = (event: Event) => { if (!root.current?.contains(event.target as Node)) setOpen(false); };
    document.addEventListener('pointerdown', away);
    document.addEventListener('focusin', away);
    return () => { document.removeEventListener('pointerdown', away); document.removeEventListener('focusin', away); };
  }, [open]);

  useEffect(() => {
    if (tour !== null) tourWasOpen.current = true;
    else if (tourWasOpen.current) { tourWasOpen.current = false; trigger.current?.focus(); }
  }, [tour]);

  const close = () => { setOpen(false); trigger.current?.focus(); };
  const tourAction = (action: TourAction) => {
    const next = tourTransition(tour, action);
    setTour(next);
  };
  /** Close first so the v1 dialogs return focus to the menu button. */
  const run = (action: () => unknown) => () => { close(); void action(); };
  const onDismissKey = (event: KeyboardEvent) => {
    if (open && event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); }
  };
  const onKeyDown = (event: KeyboardEvent) => {
    const items = [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const to = event.key === 'ArrowDown' ? at + 1 : event.key === 'ArrowUp' ? at - 1 : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : null;
    if (to === null || !items.length) return;
    event.preventDefault();
    items[(to + items.length) % items.length]?.focus();
  };

  return (
    <div class="app-account" ref={root} data-inline={inline ? 'true' : undefined} data-top={top ? 'true' : undefined} onKeyDown={onDismissKey}>
      <button ref={trigger} type="button" class="ui-button ui-button--quiet app-account-trigger" aria-expanded={open} aria-controls={id} title={accountLabel(s, lang)}
        onClick={() => setOpen(!open)}><Icon name="user" size={18} /><span class="app-account-label">{accountLabel(s, lang)}</span></button>
      {top && !open ? null : <div id={id} ref={panel} class="app-account-panel" hidden={!open} onKeyDown={onKeyDown} aria-label={t('accountMenu.aria', lang)} role="group">
        <section aria-labelledby={`${id}-account`}>
          <h2 id={`${id}-account`} class="ui-eyebrow">{s.state === 'signed-in' ? (s.name ? t('accountMenu.signedInAs', lang, {name: s.name}) : t('accountMenu.signedIn', lang)) : t('accountMenu.account', lang)}</h2>
          <p>{t(ACCOUNT_LINE[s.state], lang)}</p>
          {s.state === 'signed-in' || s.state === 'signed-out'
            ? <Button variant={s.state === 'signed-out' ? 'primary' : 'ghost'} size="sm" onClick={run(openAccountDialog)}>
                {t(s.state === 'signed-out' ? 'accountMenu.signInCreate' : 'accountMenu.manage', lang)}</Button>
            : null}
        </section>
        <section aria-labelledby={`${id}-boat`}>
          <h2 id={`${id}-boat`} class="ui-eyebrow">{t('accountMenu.boat', lang)}</h2>
          <p>{b?.name ? t('accountMenu.ratingsNamed', lang, {name: b.name}) : t('accountMenu.ratingsReference', lang)}{' '}{t('accountMenu.browserOnly', lang)}</p>
          <div class="app-account-presets">
            {(b?.presets ?? []).map(p => (
              <Button key={p.id} size="sm" pressed={b?.preset === p.id} data-preset={p.id} onClick={run(() => choosePreset(p.id))}>
                <span>{lang === 'es' && Object.hasOwn(PRESET_IDS, p.id) ? t(PRESET_IDS[p.id] as StringId, lang) : p.label}</span><small>{p.detail}</small>
              </Button>
            ))}
          </div>
          <Button size="sm" variant="quiet" onClick={run(openBoatSheet)}>{t('accountMenu.exactBoat', lang)}</Button>
        </section>
        <LanguageChoice />
        <section aria-labelledby={`${id}-coordinates`}>
          <h2 id={`${id}-coordinates`} class="ui-eyebrow">{t('accountMenu.coordinates', lang)}</h2>
          <p>{t('accountMenu.coordinatesNote', lang)}</p>
          {COORDINATE_LABELS.map(([value, label]) =>
            <Button key={value} size="sm" pressed={coordinates.value === value} onClick={() => setCoordinateFormat(value)}>{t(label, lang)}</Button>)}
        </section>
        <section aria-labelledby={`${id}-alerts`}>
          <h2 id={`${id}-alerts`} class="ui-eyebrow">{t('accountMenu.alerts', lang)}</h2>
          <p>{t(regionId ? 'accountMenu.alertsBlurb' : 'accountMenu.alertsNoRegion', lang)}</p>
          <Button size="sm" icon="bell" disabled={!regionId} onClick={run(() => setAlerts(true))}>{t('accountMenu.alertsAction', lang)}</Button>
        </section>
        <section aria-labelledby={`${id}-take`}>
          <h2 id={`${id}-take`} class="ui-eyebrow">{t('accountMenu.take', lang)}</h2>
          <ul class="app-account-links">
            <li><Button size="sm" variant="quiet" icon="pin" disabled={!regionId} onClick={run(openTrip)}>
              {t('accountMenu.trip', lang)}{tripIds.value.length ? ` · ${t('accountMenu.tripSaved', lang, {n: tripIds.value.length})}` : ''}</Button></li>
            <li><Button size="sm" variant="quiet" icon="download" disabled={!regionId} onClick={run(() => { offlineOpen.value = true; })}>{t('accountMenu.offline', lang)}</Button></li>
            <li><Button size="sm" variant="quiet" onClick={run(() => tourAction('replay'))}>{t('accountMenu.replay', lang)}</Button></li>
            <li><a href="downloads/spot-notes.html" target="_blank" rel="noopener"><Icon name="download" size={16} />{t('accountMenu.spotNotes', lang)}</a></li>
          </ul>
        </section>
      </div>}
      {alerts && regionId
        ? <PortDialog open onClose={() => { setAlerts(false); trigger.current?.focus(); }} title={t('accountMenu.alerts', lang)}><LazyAlerts regionId={regionId} /></PortDialog>
        : null}
      {tour !== null ? <ControlsTour step={tour} act={tourAction} /> : null}
    </div>
  );
}
