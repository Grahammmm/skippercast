import {h} from 'preact';
import {runtime} from './runtime.mjs';
export {listPacks} from './runtime.mjs';
export const region = {value: 'fixture-harbor'};
export const regionInfo = {value: {name: 'Fixture Harbor'}};
export const zone = () => 'UTC';
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
  return {region_name: 'Fixture Harbor', bytes: 128, missing: []};
};
