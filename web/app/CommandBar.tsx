// Command bar (FE-05, design § 6 and § 8): the Boat / Shore / Spear switch,
// the target species, the area and the time window, each bound to the store.
// The target list is the profile's defaults until FE-31 wires the region's
// search plans; the area list is the current choice until FE-31 reads
// coasts.json. Both menus keep whatever the link names so nothing is lost.
// The area group also holds the port (FE-08, § 7): a button that opens the
// port chooser with search, "Use my location" and "Explore the coast"; a
// choice saves the port for v1 and v2 and navigates in place.
// The switch and the menus are exported for the mobile shell (FE-06).
import {useState} from 'preact/hooks';
import {Button, IconButton} from '../ui/Button.tsx';
import {Segmented} from '../ui/Chip.tsx';
import {PortDialog, PortInput} from '../landing/PortInput.tsx';
import {PROFILES, PROFILE_TABLE, speciesForProfile, type Profile} from '../profile.ts';
import {currentPort, exploreURL, loadPorts, portURL, savedPortId, savePort, type Port} from '../ports.ts';
import {area, navigate, profile, region, setParams, species} from '../state.ts';
import {track} from '../telemetry.ts';
import {zone} from './App.tsx';
import {dayOptions, dockState, hourText} from './TimeDock.tsx';
import {titleCase} from './Masthead.tsx';

const PROFILE_OPTIONS = PROFILES.map(id => ({value: id, label: PROFILE_TABLE[id].label, icon: id} as const));

/** The profile's target list, plus the link's target when it is not in it. */
export function targetOptions(p: Profile, current: string | null): string[] {
  const ids = speciesForProfile({}, p);
  return current && !ids.includes(current) ? [current, ...ids] : ids;
}

/** "Today · 2 pm" or "Tue · 6 am": the time window the dock has selected. */
export function windowText(now: Date, tz: string): string {
  const state = dockState(now, tz);
  const label = dayOptions(now, tz, state.day).find(o => o.value === state.day)?.label ?? state.day;
  return `${label} · ${hourText(state.hour)}`;
}

export function ProfileSwitch({class: cls}: {class?: string} = {}) {
  return <Segmented label="Profile" options={PROFILE_OPTIONS} value={profile.value} onChange={next => setParams({profile: next, target: null})} class={cls} />;
}

export function TargetSelect() {
  const p = profile.value, target = species.value ?? PROFILE_TABLE[p].defaultTarget;
  return (
    <label>Target
      <select value={target} onChange={event => setParams({target: (event.currentTarget as HTMLSelectElement).value})}>
        {targetOptions(p, species.value).map(id => <option key={id} value={id}>{titleCase(id)}</option>)}
      </select>
    </label>
  );
}

export function AreaSelect() {
  const a = area.value;
  return (
    <label>Area
      <select value={a ?? ''} onChange={event => setParams({area: (event.currentTarget as HTMLSelectElement).value || null})}>
        <option value="">Whole region</option>
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

/** The port control and its dialog; the directory loads on the first open and a failed load still offers "Explore the coast". */
export function PortControl() {
  const [open, setOpen] = useState<'closed' | 'search' | 'locate'>('closed');
  const [ports, setPorts] = useState<readonly Port[] | null>(null);
  const current = ports ? currentPort(ports, region.value, savedPortId()) : null;
  const show = (how: 'search' | 'locate') => { setOpen(how); if (!ports) loadPorts().then(setPorts, () => setPorts([])); };
  const close = () => setOpen('closed');
  return (
    <>
      <Button icon="pin" class="app-port" aria-label={current ? `Change port (${current.name})` : 'Choose port'} onClick={() => show('search')}>{current?.name ?? 'Port'}</Button>
      <IconButton icon="target" label="Use my location" onClick={() => show('locate')} />
      <PortDialog open={open !== 'closed'} onClose={close}>
        <PortInput ports={ports} autoFocus locate={open === 'locate'} onChoose={port => { close(); choosePort(port); }} onExplore={() => { close(); navigate(exploreURL(location.href)); }} />
      </PortDialog>
    </>
  );
}

export function CommandBar({now = new Date()}: {now?: Date} = {}) {
  return (
    <section class="app-command" aria-label="Command bar">
      <ProfileSwitch />
      <TargetSelect />
      <div class="app-area" role="group" aria-label="Area and port">
        <AreaSelect />
        <PortControl />
      </div>
      <output class="app-window ui-mono" aria-label="Time window">{windowText(now, zone())}</output>
    </section>
  );
}
