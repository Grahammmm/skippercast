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
import {defaultLimits, gustBelowWind, LIMIT_BOUNDS, LIMIT_FIELDS, LIMIT_SURGE_BANDS, type ComfortLimits, type LimitField, type LimitSurge} from '../../packages/coast/src/limits.ts';
import {depthLimitFt, PROFILE_TABLE, type Profile} from '../profile.ts';
import {WANTED_BOUNDS, wantedHours, saveWanted, CRUISE_BOUNDS, cruiseSpeed, hasOwnLimits, limitsFor, resetLimits, saveCruise, saveLimits} from '../limits.ts';
import {isReachProfile, launchChoice, REACH_BOUNDS, reachFor, saveLaunch, saveReach, saveSpear, SHORE_SWIM_BOUNDS, SPEAR_DEPTH_BOUNDS, spearPlan} from '../reach.ts';
import {launchPoints} from '../launches.ts';
import {profile, region} from '../state.ts';
import {language, num, t} from '../i18n.ts';
import type {Language} from '../i18n.ts';

const fmt = (n: number) => Number(n.toFixed(1)).toString();

/** A profile's display name in `lang` (the catalogue's where.profile.* values; the table's own label is English). */
const profileName = (p: Profile, lang: Language): string => t(`where.profile.${p}`, lang);

/** Field labels for a profile: shore reads surf, the rest seas. */
export function fieldLabel(p: Profile, field: LimitField, lang: Language = 'en'): {label: string; unit: string} {
  if (field === 'wind') return {label: t('limits.field.wind', lang), unit: t('limits.unit.kt', lang)};
  if (field === 'gust') return {label: t('limits.field.gust', lang), unit: t('limits.unit.kt', lang)};
  return {label: t(p === 'shore' ? 'limits.field.surf' : 'limits.field.seas', lang), unit: t('limits.unit.ft', lang)};
}

type Draft = Record<LimitField, string> & {surge?: LimitSurge};
const draftOf = (limits: ComfortLimits): Draft => ({wind: fmt(limits.wind), gust: fmt(limits.gust), seas: fmt(limits.seas), ...(limits.surge ? {surge: limits.surge} : {})});

/**
 * The form: one number field per limit (and the surge band for spear, the cruise speed for boat, the range to
 * consider for boat and kayak, the launch for kayak, the dive limits for spear), Save and Reset to defaults.
 * `focusCruise`, `focusReach` or `focusDepth` marks that field autofocus, so the modal opens on it.
 */
export function LimitsForm({profile: p, onDone, focusCruise = false, focusWanted = false, focusReach = false, focusDepth = false}: {profile: Profile; onDone?: () => void; focusCruise?: boolean; focusWanted?: boolean; focusReach?: boolean; focusDepth?: boolean}) {
  const id = useId();
  const lang = language.value;
  const [draft, setDraft] = useState<Draft>(() => draftOf(limitsFor(p)));
  const [wanted, setWanted] = useState(() => wantedHours.peek() === null ? '' : fmt(wantedHours.peek()!));
  const [cruise, setCruise] = useState(() => cruiseSpeed.peek() === null ? '' : fmt(cruiseSpeed.peek()!));
  const [reach, setReach] = useState(() => { const nm = reachFor(p); return nm === null ? '' : fmt(nm); });
  const [depth, setDepth] = useState(() => String(depthLimitFt('spear') ?? PROFILE_TABLE.spear.maxDepthFt));
  const [from, setFrom] = useState<string>(() => spearPlan.peek().from ?? '');
  const [swim, setSwim] = useState(() => { const yd = spearPlan.peek().shoreYd; return yd === null ? '' : String(yd); });
  const area = region.value, launches = launchPoints.value && launchPoints.value.region === area ? launchPoints.value.points : [];
  const [launch, setLaunch] = useState(() => (area && launchChoice.peek()[area]) || '');
  useEffect(() => setDraft(draftOf(limitsFor(p))), [p]);
  const base = defaultLimits(p), bounds = LIMIT_BOUNDS[p], own = hasOwnLimits(p), gustNote = gustBelowWind(draft);
  const set = (field: keyof Draft, value: string) => setDraft(prev => ({...prev, [field]: value}));
  const submit = (event: Event) => {
    event.preventDefault();
    saveLimits(p, draft);
    if (p === 'boat') { saveCruise(cruise); saveWanted(wanted); }
    if (isReachProfile(p)) saveReach(p, reach);
    if (p === 'spear') saveSpear({depthFt: depth, from, shoreYd: from === 'shore' ? swim : ''});
    if (p === 'kayak' && area && launches.length) saveLaunch(area, launches.some(l => l.id === launch) ? launch : '');
    onDone?.();
  };
  const reset = () => { resetLimits(p); setDraft(draftOf(base)); };
  return (
    <form class="app-limits" onSubmit={submit} aria-describedby={`${id}-note`}>
      <p class="app-limits-status" role="status">{t(own ? 'limits.status.own' : 'limits.status.default', lang, {profile: profileName(p, lang)})}</p>
      {LIMIT_FIELDS.map(field => {
        const {label, unit} = fieldLabel(p, field, lang), b = bounds[field];
        return (
          <div class="app-limits-field" key={field}>
            <label for={`${id}-${field}`}>{label} <span class="ui-mono">({unit})</span></label>
            <input id={`${id}-${field}`} name={field} type="number" inputMode="decimal" min={b.min} max={b.max} step={b.step} required
              value={draft[field]} onInput={event => set(field, (event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-${field}-hint${field === 'gust' && gustNote ? ` ${id}-gust-note` : ''}`} />
            <span id={`${id}-${field}-hint`} class="app-limits-hint ui-mono">{t('limits.hint.default', lang, {value: num(base[field], lang), min: num(b.min, lang), max: num(b.max, lang)})}</span>
          </div>
        );
      })}
      {gustNote ? <p class="app-limits-hint" role="note" id={`${id}-gust-note`}>{t('limits.gustNote', lang)}</p> : null}
      {p === 'spear' ? (
        <div class="app-limits-field">
          <label for={`${id}-surge`}>{t('limits.surge.label', lang)}</label>
          <select id={`${id}-surge`} name="surge" value={draft.surge ?? base.surge} onChange={event => set('surge', (event.currentTarget as HTMLSelectElement).value)} aria-describedby={`${id}-surge-hint`}>
            {LIMIT_SURGE_BANDS.map(band => <option key={band} value={band}>{t(`limits.surge.${band}`, lang)}</option>)}
          </select>
          <span id={`${id}-surge-hint`} class="app-limits-hint ui-mono">{t('limits.surge.hint', lang, {value: t(`limits.surge.${base.surge ?? 'Low'}`, lang)})}</span>
        </div>
      ) : null}
      {p === 'boat' ? (
        <div class="app-limits-field">
          <label for={`${id}-cruise`}>{t('limits.cruise.label', lang)} <span class="ui-mono">({t('limits.unit.kt', lang)})</span></label>
          <input id={`${id}-cruise`} autoFocus={focusCruise} name="cruise" type="number" inputMode="decimal" min={CRUISE_BOUNDS.min} max={CRUISE_BOUNDS.max} step={CRUISE_BOUNDS.step}
            value={cruise} onInput={event => setCruise((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-cruise-hint`} />
          <span id={`${id}-cruise-hint`} class="app-limits-hint ui-mono">{t('limits.cruise.hint', lang, {min: num(CRUISE_BOUNDS.min, lang), max: num(CRUISE_BOUNDS.max, lang)})}</span>
        </div>
      ) : null}
      {p === 'boat' ? <div class="app-limits-field">
        <label for={`${id}-wanted`}>{t('limits.wanted.label', lang)}</label>
        <input id={`${id}-wanted`} name="wanted" autoFocus={focusWanted} type="number" inputMode="decimal" min={WANTED_BOUNDS.min} max={WANTED_BOUNDS.max} step={WANTED_BOUNDS.step}
          value={wanted} onInput={event => setWanted(event.currentTarget.value)} aria-describedby={`${id}-wanted-hint`} />
        <span id={`${id}-wanted-hint`} class="app-limits-hint">{t('limits.wanted.hint', lang)}</span>
      </div> : null}
      {isReachProfile(p) ? (
        <div class="app-limits-field">
          <label for={`${id}-reach`}>{t('limits.reach.label', lang)} <span class="ui-mono">({t('limits.unit.reach', lang)})</span></label>
          <input id={`${id}-reach`} autoFocus={focusReach} name="reach" type="number" inputMode="decimal" min={REACH_BOUNDS[p].min} max={REACH_BOUNDS[p].max} step={REACH_BOUNDS[p].step}
            value={reach} onInput={event => setReach((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-reach-hint`} />
          <span id={`${id}-reach-hint`} class="app-limits-hint ui-mono">{t('limits.reach.hint', lang, {min: num(REACH_BOUNDS[p].min, lang), max: num(REACH_BOUNDS[p].max, lang), origin: t(p === 'kayak' && launch ? 'limits.reach.originLaunch' : 'limits.reach.originHarbor', lang)})}</span>
        </div>
      ) : null}
      {p === 'kayak' && launches.length ? (
        <div class="app-limits-field">
          <label for={`${id}-launch`}>{t('limits.launch.label', lang)}</label>
          <select id={`${id}-launch`} name="launch" value={launch} onChange={event => setLaunch((event.currentTarget as HTMLSelectElement).value)} aria-describedby={`${id}-launch-hint`}>
            <option value="">{t('limits.launch.harbor', lang)}</option>
            {launches.map(l => <option key={l.id} value={l.id}>{l.name}</option>)}
          </select>
          <span id={`${id}-launch-hint`} class="app-limits-hint ui-mono">{t('limits.launch.hint', lang)}</span>
        </div>
      ) : null}
      {p === 'spear' ? (
        <>
          <div class="app-limits-field">
            <label for={`${id}-depth`}>{t('limits.depth.label', lang)} <span class="ui-mono">({t('limits.unit.ft', lang)})</span></label>
            <input id={`${id}-depth`} autoFocus={focusDepth} name="depth" type="number" inputMode="numeric" min={SPEAR_DEPTH_BOUNDS.min} max={SPEAR_DEPTH_BOUNDS.max} step={SPEAR_DEPTH_BOUNDS.step}
              value={depth} onInput={event => setDepth((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-depth-hint`} />
            <span id={`${id}-depth-hint`} class="app-limits-hint ui-mono">{t('limits.depth.hint', lang, {value: num(PROFILE_TABLE.spear.maxDepthFt ?? 0, lang), min: num(SPEAR_DEPTH_BOUNDS.min, lang), max: num(SPEAR_DEPTH_BOUNDS.max, lang)})}</span>
          </div>
          <div class="app-limits-field">
            <label for={`${id}-from`}>{t('limits.from.label', lang)}</label>
            <select id={`${id}-from`} name="from" value={from} onChange={event => setFrom((event.currentTarget as HTMLSelectElement).value)}>
              <option value="">{t('limits.from.unset', lang)}</option>
              <option value="shore">{t('limits.from.shore', lang)}</option>
              <option value="boat">{t('limits.from.boat', lang)}</option>
            </select>
          </div>
          {from === 'shore' ? (
            <div class="app-limits-field">
              <label for={`${id}-swim`}>{t('limits.swim.label', lang)} <span class="ui-mono">({t('limits.unit.yd', lang)})</span></label>
              <input id={`${id}-swim`} name="swim" type="number" inputMode="numeric" min={SHORE_SWIM_BOUNDS.min} max={SHORE_SWIM_BOUNDS.max} step={SHORE_SWIM_BOUNDS.step}
                value={swim} onInput={event => setSwim((event.currentTarget as HTMLInputElement).value)} aria-describedby={`${id}-swim-hint`} />
              <span id={`${id}-swim-hint`} class="app-limits-hint ui-mono">{t('limits.swim.hint', lang, {min: num(SHORE_SWIM_BOUNDS.min, lang), max: num(SHORE_SWIM_BOUNDS.max, lang)})}</span>
            </div>
          ) : null}
        </>
      ) : null}
      <p id={`${id}-note`} class="app-limits-note">
        {t('limits.note', lang)}
      </p>
      <div class="app-limits-actions">
        <Button variant="primary" type="submit">{t('limits.save', lang)}</Button>
        <Button variant="quiet" onClick={reset}>{t('limits.reset', lang)}</Button>
      </div>
    </form>
  );
}

/** A native modal dialog with a heading and Close, open while `open` is true. */
export function LimitsDialog({open, onClose, title, children}: {open: boolean; onClose: () => void; title: string; children: ComponentChildren}) {
  const lang = language.value;
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
        <IconButton icon="close" label={t('limits.close', lang)} onClick={onClose} />
      </div>
      {open ? children : null}
    </dialog>
  );
}

/** The trigger and its dialog. `compact` shows an icon button (mobile top bar). */
export function LimitsControl({compact = false}: {compact?: boolean} = {}) {
  const [open, setOpen] = useState(false);
  const lang = language.value, p = profile.value, own = hasOwnLimits(p), who = profileName(p, lang);
  const name = t('limits.trigger.name', lang, {profile: who, set: own ? t('limits.trigger.set', lang) : ''});
  return (
    <>
      {compact
        ? <IconButton icon="settings" label={name} variant="ghost" class="app-limits-trigger" aria-haspopup="dialog" data-own={own ? 'true' : undefined} onClick={() => setOpen(true)} />
        : <Button icon="settings" variant="quiet" class="app-limits-trigger" title={name} aria-haspopup="dialog" data-own={own ? 'true' : undefined} onClick={() => setOpen(true)}>{t(own ? 'limits.trigger.own' : 'limits.trigger.plain', lang)}</Button>}
      <LimitsDialog open={open} onClose={() => setOpen(false)} title={t('limits.title', lang, {profile: who})}>
        <LimitsForm profile={p} onDone={() => setOpen(false)} />
      </LimitsDialog>
    </>
  );
}
