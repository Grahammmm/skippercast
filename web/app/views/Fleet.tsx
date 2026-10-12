// Fleet view (FE-53, docs/plans/front-end/design.md § 6 and § 9): the home of
// v1's fleet controls. It takes the brief column's place on the desktop and the
// sheet's on a phone, so the map it drives stays in view.
//
// Public part: the charter grounds (the Charter fleet rail entry, `?layers=fleet`)
// with their status and basis sentence, the entry's Commercial AIS 2024 option
// where the region has the file, and the boat directory link while the public
// port pages answer (web/fleet.ts). No boat is named here.
//
// Admin part, only once the server admitted the viewer (v1's `fleetAccess`
// through web/map/fleet.ts: /api/session says admin, then the admin-only filters
// probe, a 404 while FLEET_ENABLED or FLEET_MAP_ENABLED is off): v1's filter
// form (dist/index.html `#fleet-filters`), the three activity layers, the
// planning-only checkbox, v1's status line and how the activity is inferred.
// "Apply filters" sets `activityFilters`, which FE-24's layers send to the map
// API with v1's own query builder; "Show on map" also turns the events layer on
// when no activity layer is, as v1's button does.
import {useEffect, useState} from 'preact/hooks';
import {Button} from '../../ui/Button.tsx';
import {boatDirectory, dateBounds, directoryHref, FILTER_LABELS, filterChoices, HOW_INFERRED, PLANNING_LABEL, readFilters, VESSELS_NOTE,
  type Choice, type SelectName} from '../../fleet.ts';
import {groundsState} from '../../map/charter-grounds.ts';
import {aisOn, aisState} from '../../map/commercial-ais.ts';
import {ACTIVITY, ACTIVITY_ENTRY, activityAccess, activityChoices, activityFilters, activityOn, activityStatus, hidePlanning, toggleActivity} from '../../map/fleet.ts';
import {layerEntry} from '../../map/layers.ts';
import {savedPortId, type Port} from '../../ports.ts';
import {layers, layersParam, region, setParams} from '../../state.ts';
import {toggled} from '../rail.ts';

/** v1's status line while no activity layer is on (dist/fleet-activity.js `statusText`). */
export const ACTIVITY_OFF = 'Fleet activity is off. Turn on a layer to load it.';

const checked = (event: Event): boolean => (event.currentTarget as HTMLInputElement).checked;
/** Turn the Charter fleet entry on or off (the rail's own toggle). */
const showGrounds = (on: boolean): void => { setParams({layers: layersParam(toggled(layers.value, 'fleet', on))}); };

function Check({label, on, onChange}: {label: string; on: boolean; onChange: (on: boolean) => void}) {
  return <label class="app-rail-option app-fleet-check"><input type="checkbox" checked={on} onChange={event => onChange(checked(event))} />{label}</label>;
}

/** The public part: grounds, the AIS option and the directory link. */
function Public({directory}: {directory: readonly Port[]}) {
  const on = layers.value.includes('fleet'), grounds = groundsState.value, ais = aisState.value;
  const status = !on ? 'Off. Turn it on to draw the grounds on the map.' : grounds.drawn ? `${grounds.drawn} charter ground${grounds.drawn === 1 ? '' : 's'} on the map` : grounds.note;
  return (
    <>
      <h2 class="ui-eyebrow">Charter grounds</h2>
      <Check label="Show charter grounds" on={on} onChange={showGrounds} />
      <p class="app-empty" role="status">{status}{grounds.audit ? ` · audited ${grounds.audit}` : ''}</p>
      <p class="app-fleet-basis">{layerEntry('charter-grounds').basis}</p>
      {ais.offered ? (
        <>
          <Check label={layerEntry('commercial-ais').label} on={on && aisOn.value} onChange={next => { aisOn.value = next; if (next && !on) showGrounds(true); }} />
          {on && aisOn.value && ais.note ? <p class="app-empty">{ais.note}</p> : null}
          <p class="app-fleet-basis">{layerEntry('commercial-ais').basis}</p>
        </>
      ) : null}
      {directory.length ? (
        <>
          <h2 class="ui-eyebrow">Boat directory</h2>
          <ul class="app-fleet-links">{directory.map(p => <li key={p.id}><a href={directoryHref(p)}>Boats out of {p.name}</a></li>)}</ul>
        </>
      ) : null}
    </>
  );
}

type Draft = Readonly<Record<string, string>>;
type Edit = (name: string, value: string) => void;
const typed = (event: Event): string => (event.currentTarget as HTMLInputElement | HTMLSelectElement).value;

function Select({name, choices, draft, edit}: {name: SelectName; choices: readonly Choice[]; draft: Draft; edit: Edit}) {
  return (
    <label class="app-fleet-field">{FILTER_LABELS[name]}
      <select name={name} value={draft[name] ?? ''} onChange={event => edit(name, typed(event))}>
        {choices.map(c => <option key={c.value} value={c.value}>{c.label}</option>)}
      </select>
    </label>
  );
}

/** The admin part: v1's filter form driving FE-24's layers. Rendered only for a viewer the server admitted. */
function Admin({onShowMap}: {onShowMap?: () => void}) {
  const data = activityChoices.value, choices = filterChoices(data), dates = dateBounds(data), on = activityOn.value;
  const [draft, setDraft] = useState<Draft>(activityFilters.value);
  const edit: Edit = (name, value) => setDraft(d => ({...d, [name]: value}));
  const apply = () => { activityFilters.value = readFilters(draft); };
  const select = (name: SelectName) => <Select name={name} choices={choices[name]} draft={draft} edit={edit} />;
  const date = (name: 'from' | 'to') => (
    <label class="app-fleet-field">{FILTER_LABELS[name]}
      <input name={name} type="date" value={draft[name] ?? ''} min={dates.min} max={dates.max} onInput={event => edit(name, typed(event))} />
    </label>
  );
  return (
    <section class="app-fleet-admin" aria-labelledby="app-fleet-admin-title">
      <h2 id="app-fleet-admin-title" class="ui-eyebrow">Fleet activity · admin</h2>
      <p class="app-fleet-basis">{layerEntry('fleet-events').basis}</p>
      {ACTIVITY.map(name => <Check key={name} label={layerEntry(ACTIVITY_ENTRY[name]).label} on={on.includes(name)} onChange={next => toggleActivity(name, next)} />)}
      <form class="app-fleet-form" onSubmit={event => { event.preventDefault(); apply(); }}>
        {select('vessel')}
        {data?.truncated ? <p class="app-empty">{VESSELS_NOTE}</p> : null}
        {select('port')}{select('class')}{select('trip_type')}{select('kind')}
        {date('from')}{date('to')}
        {select('season')}{select('season_part')}
        <Check label={PLANNING_LABEL} on={hidePlanning.value} onChange={next => { hidePlanning.value = next; }} />
        <div class="app-fleet-actions">
          <Button type="submit">Apply filters</Button>
          <Button variant="primary" onClick={() => {
            apply();
            if (!layers.value.includes('fleet')) showGrounds(true);
            if (!activityOn.value.length) toggleActivity('events', true);
            onShowMap?.();
          }}>Show on map</Button>
        </div>
      </form>
      <p class="app-empty" role="status">{activityStatus.value || ACTIVITY_OFF}</p>
      <details class="app-fleet-how"><summary>How fleet activity is inferred</summary><p>{HOW_INFERRED}</p></details>
    </section>
  );
}

/** The Fleet view; `onShowMap` lets the phone lower its sheet after "Show on map". */
export function Fleet({onShowMap}: {onShowMap?: () => void} = {}) {
  const id = region.value;
  const [directory, setDirectory] = useState<{region: string | null; ports: readonly Port[]}>({region: null, ports: []});
  useEffect(() => {
    let live = true;
    void boatDirectory(id, savedPortId()).then(ports => { if (live) setDirectory({region: id, ports}); });
    return () => { live = false; };
  }, [id]);
  return (
    // Not a landmark of its own: the desktop's aside and the phone's sheet are already labelled "Fleet".
    <div class="app-fleet">
      <h1 id="app-fleet-title">Fleet</h1>
      <Public directory={directory.region === id ? directory.ports : []} />
      {activityAccess.value ? <Admin onShowMap={onShowMap} /> : null}
    </div>
  );
}
