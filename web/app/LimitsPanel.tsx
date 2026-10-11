// Your limits (issue #542): the active profile's comfort limits, set by the
// user and kept on this device (web/limits.ts). Opened from the command bar
// (desktop) or beside the profile switch (mobile) into a native modal dialog
// (the port dialog's pattern), so Escape, the focus trap and focus return are
// the browser's.
// The brief's windows use the saved limits at once; Reset to defaults clears
// them for the profile. Each field shows its default and its range; values
// outside the range are clamped on save (packages/coast/src/limits.ts).
import {useEffect, useId, useRef, useState} from 'preact/hooks';
import type {ComponentChildren} from 'preact';
import {Button, IconButton} from '../ui/Button.tsx';
import {defaultLimits, LIMIT_BOUNDS, LIMIT_FIELDS, LIMIT_SURGE_BANDS, type ComfortLimits, type LimitField, type LimitSurge} from '../../packages/coast/src/limits.ts';
import {PROFILE_TABLE, type Profile} from '../profile.ts';
import {hasOwnLimits, limitsFor, resetLimits, saveLimits} from '../limits.ts';
import {profile} from '../state.ts';

const fmt = (n: number) => Number(n.toFixed(1)).toString();

/** Field labels for a profile: shore reads surf, the rest seas. */
export function fieldLabel(p: Profile, field: LimitField): {label: string; unit: string} {
  if (field === 'wind') return {label: 'Highest sustained wind', unit: 'kt'};
  if (field === 'gust') return {label: 'Highest gust', unit: 'kt'};
  return {label: p === 'shore' ? 'Highest surf' : 'Highest seas', unit: 'ft'};
}

type Draft = Record<LimitField, string> & {surge?: LimitSurge};
const draftOf = (limits: ComfortLimits): Draft => ({wind: fmt(limits.wind), gust: fmt(limits.gust), seas: fmt(limits.seas), ...(limits.surge ? {surge: limits.surge} : {})});

/** The form: one number field per limit (and the surge band for spear), Save and Reset to defaults. */
export function LimitsForm({profile: p, onDone}: {profile: Profile; onDone?: () => void}) {
  const id = useId();
  const [draft, setDraft] = useState<Draft>(() => draftOf(limitsFor(p)));
  useEffect(() => setDraft(draftOf(limitsFor(p))), [p]);
  const base = defaultLimits(p), bounds = LIMIT_BOUNDS[p], own = hasOwnLimits(p);
  const set = (field: keyof Draft, value: string) => setDraft(prev => ({...prev, [field]: value}));
  const submit = (event: Event) => {
    event.preventDefault();
    saveLimits(p, draft);
    onDone?.();
  };
  const reset = () => { resetLimits(p); setDraft(draftOf(base)); };
  return (
    <form class="app-limits" onSubmit={submit} aria-describedby={`${id}-note`}>
      <p class="app-limits-status" role="status">{own ? `${PROFILE_TABLE[p].label} uses your limits.` : `${PROFILE_TABLE[p].label} uses the default limits.`}</p>
      {LIMIT_FIELDS.map(field => {
        const {label, unit} = fieldLabel(p, field), b = bounds[field];
        return (
          <div class="app-limits-field" key={field}>
            <label for={`${id}-${field}`}>{label} <span class="ui-mono">({unit})</span></label>
            <input id={`${id}-${field}`} name={field} type="number" inputMode="decimal" min={b.min} max={b.max} step={b.step} required
              value={draft[field]} onInput={event => set(field, (event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-${field}-hint`} />
            <span id={`${id}-${field}-hint`} class="app-limits-hint ui-mono">Default {fmt(base[field])} · {fmt(b.min)}–{fmt(b.max)}</span>
          </div>
        );
      })}
      {p === 'spear' ? (
        <div class="app-limits-field">
          <label for={`${id}-surge`}>Highest surge</label>
          <select id={`${id}-surge`} name="surge" value={draft.surge ?? base.surge} onChange={event => set('surge', (event.currentTarget as HTMLSelectElement).value)} aria-describedby={`${id}-surge-hint`}>
            {LIMIT_SURGE_BANDS.map(band => <option key={band} value={band}>{band}</option>)}
          </select>
          <span id={`${id}-surge-hint`} class="app-limits-hint ui-mono">Default {base.surge}</span>
        </div>
      ) : null}
      <p id={`${id}-note`} class="app-limits-note">
        Kept on this device only. Suggested windows use these limits. Marine alerts, long-period swell, a hazardous bar, offshore wind and launch surf for a kayak, and daylight still rule hours out whatever you set.
      </p>
      <div class="app-limits-actions">
        <Button variant="primary" type="submit">Save</Button>
        <Button variant="quiet" onClick={reset}>Reset to defaults</Button>
      </div>
    </form>
  );
}

/** A native modal dialog with a heading and Close, open while `open` is true. */
function LimitsDialog({open, onClose, title, children}: {open: boolean; onClose: () => void; title: string; children: ComponentChildren}) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog ref={ref} class="app-limits-dialog" aria-labelledby={id} onClose={onClose}>
      <div class="app-limits-head">
        <h2 id={id}>{title}</h2>
        <IconButton icon="close" label="Close" onClick={onClose} />
      </div>
      {open ? children : null}
    </dialog>
  );
}

/** The trigger and its dialog. `compact` shows an icon button (mobile top bar). */
export function LimitsControl({compact = false}: {compact?: boolean} = {}) {
  const [open, setOpen] = useState(false);
  const p = profile.value, own = hasOwnLimits(p);
  const name = `Your limits for ${PROFILE_TABLE[p].label}${own ? ' (set)' : ''}`;
  return (
    <>
      {compact
        ? <IconButton icon="settings" label={name} variant="ghost" class="app-limits-trigger" aria-haspopup="dialog" data-own={own ? 'true' : undefined} onClick={() => setOpen(true)} />
        : <Button icon="settings" variant="quiet" class="app-limits-trigger" title={name} aria-haspopup="dialog" data-own={own ? 'true' : undefined} onClick={() => setOpen(true)}>{own ? 'Your limits · set' : 'Your limits'}</Button>}
      <LimitsDialog open={open} onClose={() => setOpen(false)} title={`Your limits · ${PROFILE_TABLE[p].label}`}>
        <LimitsForm profile={p} onDone={() => setOpen(false)} />
      </LimitsDialog>
    </>
  );
}
