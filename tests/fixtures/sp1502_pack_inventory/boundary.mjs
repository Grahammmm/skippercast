import {h} from 'preact';
import {runtime} from './runtime.mjs';
export {listPacks} from './runtime.mjs';
export const region = {value: 'fixture-harbor'};
export const regionInfo = {value: {name: 'Fixture Harbor'}};
export const zone = () => 'UTC';
export const oceanLines = () => null;   // the fixture packs carry no ocean record
export const forecastEndLine = () => '';   // the fixture packs carry no forecast end; these tests do not read the line
export const tripOpen = {value: false}, tripError = {value: ''}, plannerView = {value: null}, tripReady = {value: true}, offlineOpen = {value: true};
export function Button({children, ...props}) {
  if (props.onClick) runtime.actions.set(props['aria-label'] ?? (Array.isArray(children) ? children.join('') : children), props.onClick);
  return h('button', props, children);
}
export const IconButton = () => null;
export const PortDialog = ({children}) => h('div', {}, children);
export const canSaveCoastal = async () => false;
export const readCoastal = async () => null;
export const closeTrip = () => { throw new Error('unexpected planner action'); };
export const loadPlanner = closeTrip, deleteCoastal = closeTrip, saveCoastal = closeTrip;
export const savePack = async () => {
  runtime.saves++;
  return runtime.saveMeta ?? {region_name: 'Fixture Harbor', bytes: 128, missing: []};
};
// SC2037-05: no storage API in the fixture world: a save keeps the older words and the list shows no estimate line.
export const KEEP_WORDS = {agreed: '', already: '', refused: '', unavailable: ''};
export const storageLine = async () => null, estimateWords = () => '';
export const savePackKept = async save => ({meta: await save(), keep: 'unavailable'});
// SC-GPSOFFLINE-1: the position check is its own component (tests/test_position_check.mjs); these tests render the offline section only.
export const PositionCheck = () => null;
