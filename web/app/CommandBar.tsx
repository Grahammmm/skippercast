// Command bar (FE-05, design § 6 and § 8): the Boat / Shore / Spear switch
// (FE-20: a switch restores that profile's own layers, stored or default),
// the target species, the area and the time window, each bound to the store.
// The target list (FE-30, web/species.ts) is the profile's species, the
// region's search plans fitting its method and the coast targets; the area
// list is the current choice until FE-31 reads coasts.json. Both menus keep
// whatever the link names so nothing is lost.
// The area group also holds the port (FE-08, § 7): a button that opens the
// port chooser with search, "Use my location" and "Explore the coast"; a
// choice saves the port for v1 and v2 and navigates in place.
// FE-54 (§ 6 "Species select, filters, Find a spot search"): the target menu
// groups the search plans, the profile's own species and the coast habitat
// targets under their own headings, never merging their scores, and a search
// field narrows it by name; the chosen target always stays listed.
// The switch and the menus are exported for the mobile shell (FE-06).
// #542: "Your limits" beside the switch opens the active profile's own comfort
// limits (web/app/LimitsPanel.tsx).
import {useEffect, useRef, useState} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Segmented} from '../ui/Chip.tsx';
import {Popover} from '../ui/Popover.tsx';
import {PortDialog, PortInput} from '../landing/PortInput.tsx';
import {language, t, type Language} from '../i18n.ts';
import {PROFILES, PROFILE_TABLE, type Profile} from '../profile.ts';
import {optionText, regionMenu, regionTargets, type TargetOption} from '../species.ts';
import {currentPort, exploreURL, linkedPort, loadPorts, portURL, savedPortId, savePort, type Port} from '../ports.ts';
import {shareLink, shareOrCopy} from '../share-link.ts';
import {area, navigate, port, profile, profilePatch, region, setParams, species} from '../state.ts';
import {track} from '../telemetry.ts';
import {zone} from './App.tsx';
import {dayOptions, dockState, readout} from './TimeDock.tsx';
import {titleCase} from './Masthead.tsx';
import {LimitsControl} from './LimitsPanel.tsx';

/** A profile's name in `lang` (the catalogue's where.profile.* values; the table's own label is English). */
const profileName = (p: Profile, lang: Language): string => t(`where.profile.${p}`, lang);

/**
 * A target menu option in `lang`: the published target name is never translated, only the state that follows it.
 * English is the picker's own optionText, byte for byte.
 */
export function shellTargetText(option: TargetOption, lang: Language = 'en'): string {
  if (lang !== 'es' || !option.state) return optionText(option);
  return `${option.label} · ${t(`command.state.${option.state}`, lang)}`;
}

/** A menu group's heading in `lang`. English returns the picker's label verbatim; the group is read from its stable key, not its words. */
export function shellGroupLabel(group: {readonly label: string; readonly options: readonly TargetOption[]}, p: Profile, lang: Language = 'en'): string {
  if (lang !== 'es') return group.label;
  return t(`command.group.${group.options[0]?.group ?? 'profile'}`, lang, {profile: profileName(p, lang)});
}

/** The profile's target list in the current region, plus the link's target when it is not in it. */
export function targetList(p: Profile, current: string | null): TargetOption[] {
  return regionTargets(p, region.value, current);
}
export const targetOptions = (p: Profile, current: string | null): string[] => targetList(p, current).map(t => t.id);

/** "Today · 2 pm" or "Tue · 6 am": the time window the dock has selected. */
export function windowText(now: Date, tz: string, lang: Language = 'en'): string {
  const state = dockState(now, tz);
  const label = dayOptions(now, tz, state.day, lang).find(o => o.value === state.day)?.label ?? state.day;
  return `${label} · ${readout(state, tz, lang)}`;
}

export function ProfileSwitch({class: cls}: {class?: string} = {}) {
  const lang = language.value;
  const options = PROFILES.map(id => ({value: id, label: profileName(id, lang), icon: id} as const));
  return <Segmented label={t('command.profile', lang)} options={options} value={profile.value} onChange={next => setParams(profilePatch(next))} class={cls} />;
}

export function TargetSelect() {
  const p = profile.value, target = species.value ?? PROFILE_TABLE[p].defaultTarget, lang = language.value;
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const groups = regionMenu(p, region.value, species.value).map(g => ({...g, options: g.options.filter(t => !q || t.id === target || t.label.toLowerCase().includes(q))}))
    .filter(g => g.options.length);
  return (
    <div class="app-target" role="group" aria-label={t('command.targetSpecies', lang)}>
      <input type="search" class="app-target-search" aria-label={t('command.findTarget', lang)} placeholder={t('command.findTarget', lang)} value={query}
        onInput={event => setQuery((event.currentTarget as HTMLInputElement).value)} />
      <label>{t('command.target', lang)}
        <select value={target} onChange={event => setParams({target: (event.currentTarget as HTMLSelectElement).value})}>
          {groups.map(g => (
            <optgroup key={g.label} label={shellGroupLabel(g, p, lang)}>{g.options.map(o => <option key={o.id} value={o.id} disabled={!!o.unavailable}>{shellTargetText(o, lang)}</option>)}</optgroup>
          ))}
        </select>
      </label>
    </div>
  );
}

/** The Area picker offers a choice only when a link selected an area: that area or the whole region.
 * With no area it would be a select whose only option is "Whole region", so it draws nothing and
 * takes no slot in the command bar (UX audit S4-35). */
export function AreaSelect() {
  const a = area.value, lang = language.value;
  if (!a) return null;
  return (
    <label>{t('command.area', lang)}
      <select value={a ?? ''} onChange={event => setParams({area: (event.currentTarget as HTMLSelectElement).value || null})}>
        <option value="">{t('command.wholeRegion', lang)}</option>
        {a ? <option value={a}>{titleCase(a)}</option> : null}
      </select>
    </label>
  );
}

/** Save `port` and open the app there, keeping the profile; the v2 store swaps the region without a reload. */
export function choosePort(port: Port, href: string = location.href): void {
  savePort(port.id);
  track('port_selected', {region: port.region, flush: true});
  navigate(portURL(href, port, profile.peek()));
}

/** BF-deep-links: Share hands the canonical link (web/share-link.ts) to the share sheet, else copies it, else shows it to copy. */
export function ShareControl() {
  const [copied, setCopied] = useState(false), lang = language.value;
  const [manual, setManual] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined), wrap = useRef<HTMLSpanElement>(null);
  const press = async () => {
    const ports = await loadPorts().catch(() => null);
    const link = shareLink({href: location.href, origin: location.origin, ports, region: region.peek(), savedId: savedPortId(), profile: profile.peek(), now: new Date(), tz: zone()});
    const outcome = await shareOrCopy(link);
    if (outcome === 'copied') { clearTimeout(timer.current); setCopied(true); timer.current = setTimeout(() => setCopied(false), 3000); }
    if (outcome === 'manual') setManual(link.url);
  };
  useEffect(() => {
    const input = wrap.current?.querySelector('input'), details = wrap.current?.querySelector('details');
    if (details) details.open = true; input?.focus(); input?.select();
  }, [manual]);
  useEffect(() => () => clearTimeout(timer.current), []);
  const dismiss = (event: KeyboardEvent) => { if (event.key === 'Escape') { setManual(null); wrap.current?.querySelector('button')?.focus(); } };
  return (
    <span class="app-share" ref={wrap}>
      <IconButton icon="arrow" label={t('command.share', lang)} onClick={() => void press()} />
      <span class="app-share-status" role="status">{copied ? t('command.linkCopied', lang) : ''}</span>
      {manual ? <Popover summary={t('command.link', lang)} sources={false} class="app-share-popover"><input readOnly value={manual} aria-label={t('command.linkToCopy', lang)} onKeyDown={dismiss} /></Popover> : null}
    </span>
  );
}

/** The port control and its dialog; the directory loads on the first open (or at once for a linked ?port=) and a failed load still offers "Explore the coast". */
export function PortControl() {
  const [open, setOpen] = useState<'closed' | 'search' | 'locate'>('closed');
  const [ports, setPorts] = useState<readonly Port[] | null>(null);
  const current = ports ? currentPort(ports, region.value, savedPortId(), port.value) : null;
  const show = (how: 'search' | 'locate') => { setOpen(how); if (!ports) loadPorts().then(setPorts, () => setPorts([])); };
  useEffect(() => {
    // A failed load cannot judge the link, so its port stays; a listed one is read at arrival, after any choice since.
    if (new URL(location.href).searchParams.has('port')) loadPorts().then(list => {
      setPorts(list);
      if (new URL(location.href).searchParams.has('port') && !linkedPort(list, region.peek(), port.peek())) setParams({port: null});
    }, () => setPorts([]));
  }, []);
  const close = () => setOpen('closed'), lang = language.value;
  return (
    <>
      <Button icon="pin" class="app-port" aria-label={current ? t('command.changePort', lang, {name: current.name}) : t('command.choosePort', lang)} onClick={() => show('search')}>{current?.name ?? t('command.port', lang)}</Button>
      <IconButton icon="target" label={t('command.useLocation', lang)} onClick={() => show('locate')} />
      <ShareControl />
      <PortDialog open={open !== 'closed'} onClose={close}>
        <PortInput ports={ports} autoFocus locate={open === 'locate'} onChoose={port => { close(); choosePort(port); }} onExplore={() => { close(); navigate(exploreURL(location.href)); }} />
      </PortDialog>
    </>
  );
}

export function CommandBar({now = new Date()}: {now?: Date} = {}) {
  const lang = language.value;
  return (
    <section class="app-command" aria-label={t('command.bar', lang)}>
      {/* The limits trigger is an icon beside the switch, so the bar stays one row on a 1280 px laptop. */}
      <div class="app-profile-limits">
        <ProfileSwitch />
        <LimitsControl compact />
      </div>
      <TargetSelect />
      <div class="app-area" role="group" aria-label={t('command.areaPort', lang)}>
        <AreaSelect />
        <PortControl />
      </div>
      <output class="app-window ui-mono" aria-label={t('command.timeWindow', lang)}>{windowText(now, zone(), lang)}</output>
    </section>
  );
}
