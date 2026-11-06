// Fleet view, admin part (FE-53, split out by SC0922-13): v1's filter form driving FE-24's layers, rendered only
// for a viewer the server admitted. Admin views are outside the Spanish work (#1512): this file stays English on
// purpose, and nothing the public Fleet part shows lives here. The shared Check box and the Charter fleet toggle are
// exported for the public part, so there is no import cycle.
import {useState} from 'preact/hooks';
import {Button} from '../../ui/Button.tsx';
import {dateBounds, FILTER_LABELS, filterChoices, HOW_INFERRED, PLANNING_LABEL, readFilters, VESSELS_NOTE,
  type Choice, type SelectName} from '../../fleet.ts';
import {ACTIVITY, ACTIVITY_ENTRY, activityChoices, activityFilters, activityOn, activityStatus, hidePlanning, toggleActivity} from '../../map/fleet.ts';
import {layerEntry} from '../../map/layers.ts';
import {layers, layersParam, setParams} from '../../state.ts';
import {toggled} from '../rail.ts';

/** v1's status line while no activity layer is on (dist/fleet-activity.js `statusText`). */
export const ACTIVITY_OFF = 'Fleet activity is off. Turn on a layer to load it.';

const checked = (event: Event): boolean => (event.currentTarget as HTMLInputElement).checked;
/** Turn the Charter fleet entry on or off (the rail's own toggle). */
export const showGrounds = (on: boolean): void => { setParams({layers: layersParam(toggled(layers.value, 'fleet', on))}); };

/** A 24 px target (WCAG 2.5.8; app.css draws rail inputs at 16 px). Preact 11 sets style values verbatim, so lengths carry their unit. */
export function Check({label, on, onChange}: {label: string; on: boolean; onChange: (on: boolean) => void}) {
  return <label class="app-rail-option app-fleet-check"><input type="checkbox" style={{minWidth: '24px', minHeight: '24px'}} checked={on} onChange={event => onChange(checked(event))} />{label}</label>;
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
export function Admin({onShowMap}: {onShowMap?: () => void}) {
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

