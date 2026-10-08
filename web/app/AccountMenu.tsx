// Account menu (FE-50, design § 6 and § 7, US-R5): the masthead's sign in
// becomes one disclosure holding the account (v1's passkey dialog), the boat
// (first-run.js presets and the exact-boat sheet), saved-trip alerts and the
// take-it-with-you entries. A real button with aria-expanded; opening moves
// focus into the panel, arrows and Home/End move between its controls,
// Escape or a click outside closes it and returns focus to the button.
// Every action is web/account.ts, which wraps the v1 modules unchanged.
import {useEffect, useId, useRef, useState} from 'preact/hooks';
import {Button} from '../ui/Button.tsx';
import {Icon} from '../ui/icons.tsx';
import {PortDialog} from '../landing/PortInput.tsx';
import {accountLabel, boat, choosePreset, classicURL, followAccountHash, loadBoat, mountTripAlerts, openAccountDialog, openBoatSheet, refreshSession, session, type Session} from '../account.ts';
import {region, species} from '../state.ts';

const ACCOUNT_LINE: Readonly<Record<Session['state'], string>> = {
  'loading': 'Checking your account…',
  'offline': 'Accounts need a connection. Try again when you are online.',
  'disabled': 'Accounts are not available on this site. The map and forecasts stay public.',
  'signed-out': 'Accounts use a passkey: Face ID, Touch ID or your device PIN. No password.',
  'signed-in': 'Your saved trips and alerts are private to this account.',
};
const FOCUSABLE = 'button:not([disabled]), a[href]';

/** The alerts dialog's body, mounted only while open: fresh hosts each time, since trip-alerts.js binds its listeners to them. */
function TripAlerts({regionId}: {regionId: string}) {
  const [error, setError] = useState('');
  useEffect(() => { mountTripAlerts(regionId, species.peek()).catch((e: Error) => setError(e.message)); }, [regionId]);
  return (
    <div class="app-alerts">
      <label>Alert species<select id="species-select"></select></label>
      <input type="hidden" id="comfort-heading" value="" />
      <div id="trip-alerts"><p role="status">{error || 'Loading your alerts…'}</p></div>
      <div id="comfort-feedback"></div>
    </div>
  );
}

/** `inline`: the panel opens in the flow (the mobile sheet's footer) instead of under the button. */
export function AccountMenu({inline = false}: {inline?: boolean} = {}) {
  const [open, setOpen] = useState(false);
  const [alerts, setAlerts] = useState(false);
  const root = useRef<HTMLDivElement>(null), trigger = useRef<HTMLButtonElement>(null), panel = useRef<HTMLDivElement>(null);
  const id = useId();
  const s = session.value, b = boat.value, regionId = region.value;

  useEffect(() => {
    void refreshSession();
    return followAccountHash(() => { setOpen(false); setAlerts(false); });
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

  const close = () => { setOpen(false); trigger.current?.focus(); };
  /** Close first so the v1 dialogs return focus to the menu button. */
  const run = (action: () => unknown) => () => { close(); void action(); };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === 'Escape') { event.preventDefault(); event.stopPropagation(); close(); return; }
    const items = [...(panel.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
    const at = items.indexOf(document.activeElement as HTMLElement);
    const to = event.key === 'ArrowDown' ? at + 1 : event.key === 'ArrowUp' ? at - 1 : event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : null;
    if (to === null || !items.length) return;
    event.preventDefault();
    items[(to + items.length) % items.length]?.focus();
  };

  return (
    <div class="app-account" ref={root} data-inline={inline ? 'true' : undefined}>
      <button ref={trigger} type="button" class="ui-button ui-button--quiet app-account-trigger" aria-expanded={open} aria-controls={id}
        onClick={() => setOpen(!open)}><Icon name="user" size={18} />{accountLabel(s)}</button>
      <div id={id} ref={panel} class="app-account-panel" hidden={!open} onKeyDown={onKeyDown} aria-label="Account, boat and alerts" role="group">
        <section aria-labelledby={`${id}-account`}>
          <h2 id={`${id}-account`} class="ui-eyebrow">{s.state === 'signed-in' ? (s.name ? `Signed in as ${s.name}` : 'Signed in') : 'Account'}</h2>
          <p>{ACCOUNT_LINE[s.state]}</p>
          {s.state === 'signed-in' || s.state === 'signed-out'
            ? <Button variant={s.state === 'signed-out' ? 'primary' : 'ghost'} size="sm" onClick={run(openAccountDialog)}>
                {s.state === 'signed-out' ? 'Sign in or create an account' : 'Account, passkeys and sign out'}</Button>
            : null}
        </section>
        <section aria-labelledby={`${id}-boat`}>
          <h2 id={`${id}-boat`} class="ui-eyebrow">Your boat</h2>
          <p>{b?.name ? `Ratings use ${b.name}.` : 'Ratings use the reference 23 ft deep-V walkaround.'} Saved in this browser only.</p>
          <div class="app-account-presets">
            {(b?.presets ?? []).map(p => (
              <Button key={p.id} size="sm" pressed={b?.preset === p.id} data-preset={p.id} onClick={run(() => choosePreset(p.id))}>
                <span>{p.label}</span><small>{p.detail}</small>
              </Button>
            ))}
          </div>
          <Button size="sm" variant="quiet" onClick={run(openBoatSheet)}>Enter my exact boat</Button>
        </section>
        <section aria-labelledby={`${id}-alerts`}>
          <h2 id={`${id}-alerts`} class="ui-eyebrow">Trip alerts</h2>
          <p>{regionId ? 'Save a date, area and comfort limits; get material changes and a day-before assessment.' : 'Choose a port to save trip alerts for it.'}</p>
          <Button size="sm" icon="bell" disabled={!regionId} onClick={run(() => setAlerts(true))}>Saved-trip alerts</Button>
        </section>
        <section aria-labelledby={`${id}-take`}>
          <h2 id={`${id}-take`} class="ui-eyebrow">Take it with you</h2>
          <ul class="app-account-links">
            <li><a href="downloads/spot-notes.html" target="_blank" rel="noopener"><Icon name="download" size={16} />Offline spot notes (new tab)</a></li>
            <li><a href={classicURL(regionId, '#export')}><Icon name="download" size={16} />Chartplotter day plan (GPX, classic map)</a></li>
            <li><a href={classicURL(regionId, '#guide')}><Icon name="download" size={16} />Offline trip pack (classic map)</a></li>
          </ul>
        </section>
      </div>
      {alerts && regionId
        ? <PortDialog open onClose={() => { setAlerts(false); trigger.current?.focus(); }} title="Trip alerts"><TripAlerts regionId={regionId} /></PortDialog>
        : null}
    </div>
  );
}
