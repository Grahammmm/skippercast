// Your limits (issue #542): the active profile's comfort limits, set by the
// user and kept on this device (web/limits.ts). Opened from the command bar
// (desktop) or beside the profile switch (mobile) into a native modal dialog
// (the port dialog's pattern), so Escape, the focus trap and focus return are
// the browser's.
// The brief's windows use the saved limits at once; Reset to defaults clears
// them for the profile. Each field shows its default and its range; values
// outside the range are clamped on save (packages/coast/src/limits.ts).
// Boat adds the cruise speed the brief's run times use (web/brief/run.ts):
// blank until the user types one, with no default, and kept apart from the
// limits so Reset to defaults leaves it alone.
// Boat and Kayak add the range to consider (#644, web/reach.ts): how far out,
// one way, "Where to look" and the Chart's reach ring use; blank until the
// user types one, no default, and also left alone by Reset to defaults.
// Spear adds the deepest dive (default the table's 60 ft), where the diver
// dives from, and the farthest swim from shore; Kayak adds the launch the range
// runs from, one of the region's reviewed launch points (#644, part 2). Reset
// to defaults leaves these alone too.
import {useEffect, useId, useRef, useState} from 'preact/hooks';
import type {ComponentChildren} from 'preact';
import {Button, IconButton} from '../ui/Button.tsx';
import {defaultLimits, LIMIT_BOUNDS, LIMIT_FIELDS, LIMIT_SURGE_BANDS, type ComfortLimits, type LimitField, type LimitSurge} from '../../packages/coast/src/limits.ts';
import {depthLimitFt, PROFILE_TABLE, type Profile} from '../profile.ts';
import {CRUISE_BOUNDS, cruiseSpeed, hasOwnLimits, limitsFor, resetLimits, saveCruise, saveLimits} from '../limits.ts';
import {isReachProfile, launchChoice, REACH_BOUNDS, reachFor, saveLaunch, saveReach, saveSpear, SHORE_SWIM_BOUNDS, SPEAR_DEPTH_BOUNDS, spearPlan} from '../reach.ts';
import {launchPoints} from '../launches.ts';
import {profile, region} from '../state.ts';

const fmt = (n: number) => Number(n.toFixed(1)).toString();

/** Field labels for a profile: shore reads surf, the rest seas. */
export function fieldLabel(p: Profile, field: LimitField): {label: string; unit: string} {
  if (field === 'wind') return {label: 'Highest sustained wind', unit: 'kt'};
  if (field === 'gust') return {label: 'Highest gust', unit: 'kt'};
  return {label: p === 'shore' ? 'Highest surf' : 'Highest seas', unit: 'ft'};
}

type Draft = Record<LimitField, string> & {surge?: LimitSurge};
const draftOf = (limits: ComfortLimits): Draft => ({wind: fmt(limits.wind), gust: fmt(limits.gust), seas: fmt(limits.seas), ...(limits.surge ? {surge: limits.surge} : {})});

/**
 * The form: one number field per limit (and the surge band for spear, the cruise speed for boat, the range to
 * consider for boat and kayak, the launch for kayak, the dive limits for spear), Save and Reset to defaults.
 * `focusCruise`, `focusReach` or `focusDepth` marks that field autofocus, so the modal opens on it.
 */
export function LimitsForm({profile: p, onDone, focusCruise = false, focusReach = false, focusDepth = false}: {profile: Profile; onDone?: () => void; focusCruise?: boolean; focusReach?: boolean; focusDepth?: boolean}) {
  const id = useId();
  const [draft, setDraft] = useState<Draft>(() => draftOf(limitsFor(p)));
  const [cruise, setCruise] = useState(() => cruiseSpeed.peek() === null ? '' : fmt(cruiseSpeed.peek()!));
  const [reach, setReach] = useState(() => { const nm = reachFor(p); return nm === null ? '' : fmt(nm); });
  const [depth, setDepth] = useState(() => String(depthLimitFt('spear') ?? PROFILE_TABLE.spear.maxDepthFt));
  const [from, setFrom] = useState<string>(() => spearPlan.peek().from ?? '');
  const [swim, setSwim] = useState(() => { const yd = spearPlan.peek().shoreYd; return yd === null ? '' : String(yd); });
  const area = region.value, launches = launchPoints.value && launchPoints.value.region === area ? launchPoints.value.points : [];
  const [launch, setLaunch] = useState(() => (area && launchChoice.peek()[area]) || '');
  useEffect(() => setDraft(draftOf(limitsFor(p))), [p]);
  const base = defaultLimits(p), bounds = LIMIT_BOUNDS[p], own = hasOwnLimits(p);
  const set = (field: keyof Draft, value: string) => setDraft(prev => ({...prev, [field]: value}));
  const submit = (event: Event) => {
    event.preventDefault();
    saveLimits(p, draft);
    if (p === 'boat') saveCruise(cruise);
    if (isReachProfile(p)) saveReach(p, reach);
    if (p === 'spear') saveSpear({depthFt: depth, from, shoreYd: from === 'shore' ? swim : ''});
    if (p === 'kayak' && area && launches.length) saveLaunch(area, launches.some(l => l.id === launch) ? launch : '');
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
      {p === 'boat' ? (
        <div class="app-limits-field">
          <label for={`${id}-cruise`}>Cruise speed <span class="ui-mono">(kt)</span></label>
          <input id={`${id}-cruise`} autoFocus={focusCruise} name="cruise" type="number" inputMode="decimal" min={CRUISE_BOUNDS.min} max={CRUISE_BOUNDS.max} step={CRUISE_BOUNDS.step}
            value={cruise} onInput={event => setCruise((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-cruise-hint`} />
          <span id={`${id}-cruise-hint`} class="app-limits-hint ui-mono">No default · {fmt(CRUISE_BOUNDS.min)}–{fmt(CRUISE_BOUNDS.max)} · run times only · blank clears it</span>
        </div>
      ) : null}
      {isReachProfile(p) ? (
        <div class="app-limits-field">
          <label for={`${id}-reach`}>Range to consider <span class="ui-mono">(nm, one way)</span></label>
          <input id={`${id}-reach`} autoFocus={focusReach} name="reach" type="number" inputMode="decimal" min={REACH_BOUNDS[p].min} max={REACH_BOUNDS[p].max} step={REACH_BOUNDS[p].step}
            value={reach} onInput={event => setReach((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-reach-hint`} />
          <span id={`${id}-reach-hint`} class="app-limits-hint ui-mono">No default · {fmt(REACH_BOUNDS[p].min)}–{fmt(REACH_BOUNDS[p].max)} · straight line from {p === 'kayak' && launch ? 'the launch' : 'the harbor'}, not a route · blank clears it</span>
        </div>
      ) : null}
      {p === 'kayak' && launches.length ? (
        <div class="app-limits-field">
          <label for={`${id}-launch`}>Launch from</label>
          <select id={`${id}-launch`} name="launch" value={launch} onChange={event => setLaunch((event.currentTarget as HTMLSelectElement).value)} aria-describedby={`${id}-launch-hint`}>
            <option value="">The harbor</option>
            {launches.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
          <span id={`${id}-launch-hint`} class="app-limits-hint ui-mono">Listed public launches · the range and distances start here</span>
        </div>
      ) : null}
      {p === 'spear' ? (
        <>
          <div class="app-limits-field">
            <label for={`${id}-depth`}>Deepest dive <span class="ui-mono">(ft)</span></label>
            <input id={`${id}-depth`} autoFocus={focusDepth} name="depth" type="number" inputMode="numeric" min={SPEAR_DEPTH_BOUNDS.min} max={SPEAR_DEPTH_BOUNDS.max} step={SPEAR_DEPTH_BOUNDS.step}
              value={depth} onInput={event => setDepth((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-depth-hint`} />
            <span id={`${id}-depth-hint`} class="app-limits-hint ui-mono">Default {PROFILE_TABLE.spear.maxDepthFt} · {SPEAR_DEPTH_BOUNDS.min}–{SPEAR_DEPTH_BOUNDS.max} · places deeper are left out</span>
          </div>
          <div class="app-limits-field">
            <label for={`${id}-from`}>Diving from</label>
            <select id={`${id}-from`} name="from" value={from} onChange={event => setFrom((event.currentTarget as HTMLSelectElement).value)}>
              <option value="">Not set</option>
              <option value="shore">Shore</option>
              <option value="boat">A boat</option>
            </select>
          </div>
          {from === 'shore' ? (
            <div class="app-limits-field">
              <label for={`${id}-swim`}>Farthest swim from shore <span class="ui-mono">(yd)</span></label>
              <input id={`${id}-swim`} name="swim" type="number" inputMode="numeric" min={SHORE_SWIM_BOUNDS.min} max={SHORE_SWIM_BOUNDS.max} step={SHORE_SWIM_BOUNDS.step}
                value={swim} onInput={event => setSwim((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-swim-hint`} />
              <span id={`${id}-swim-hint`} class="app-limits-hint ui-mono">No default · {SHORE_SWIM_BOUNDS.min}–{SHORE_SWIM_BOUNDS.max} · approximate, from the mapped shoreline where the region has one · blank clears it</span>
            </div>
          ) : null}
        </>
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
export function LimitsDialog({open, onClose, title, children}: {open: boolean; onClose: () => void; title: string; children: ComponentChildren}) {
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
